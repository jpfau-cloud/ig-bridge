import os
import json
import time
import requests
from datetime import datetime, timezone
from flask import Flask, request, jsonify

app = Flask(__name__)

# ====================
# Render / Env
# ====================
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

IG_API_KEY     = os.environ.get("IG_API_KEY", "")
IG_USERNAME    = os.environ.get("IG_USERNAME", "")
IG_PASSWORD    = os.environ.get("IG_PASSWORD", "")
IG_ACCOUNT_ID  = os.environ.get("IG_ACCOUNT_ID", "")
IG_EPIC_GER40  = os.environ.get("IG_EPIC_GER40", "")

# Demo endpoint (für Live später: https://api.ig.com/gateway/deal)
IG_BASE = os.environ.get("IG_BASE", "https://demo-api.ig.com/gateway/deal")

# Persistent disk mount
LOG_DIR = os.environ.get("LOG_DIR", "/var/data")
LOG_PATH = os.path.join(LOG_DIR, "trades.jsonl")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_line(obj: dict):
    """Append one JSON line to persistent log file."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        obj = {"ts": now_iso(), **obj}
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    except Exception as e:
        # Last resort: do not crash the service if logging fails
        print("LOG_ERROR:", str(e), flush=True)


def ig_login() -> dict:
    """Login and return session headers with CST + X-SECURITY-TOKEN."""
    url = f"{IG_BASE}/session"
    headers = {
        "X-IG-API-KEY": IG_API_KEY,
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json; charset=UTF-8",
        "VERSION": "2",
    }
    payload = {"identifier": IG_USERNAME, "password": IG_PASSWORD, "encryptedPassword": False}

    r = requests.post(url, headers=headers, json=payload, timeout=20)
    log_line({"kind": "ig_login", "status": r.status_code, "body": safe_json(r)})

    r.raise_for_status()

    cst = r.headers.get("CST")
    sec = r.headers.get("X-SECURITY-TOKEN")
    if not cst or not sec:
        raise RuntimeError("IG login ok but CST / X-SECURITY-TOKEN missing")

    return {
        "X-IG-API-KEY": IG_API_KEY,
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json; charset=UTF-8",
        "CST": cst,
        "X-SECURITY-TOKEN": sec,
        "VERSION": "2",
    }


def safe_json(resp):
    try:
        return resp.json()
    except Exception:
        return resp.text


def resolve_epic(payload: dict) -> str:
    # If payload sends epic directly, prefer it
    epic = (payload.get("epic") or "").strip()
    if epic:
        return epic

    # Otherwise resolve from symbol
    sym = (payload.get("symbol") or "").strip().upper()

    # Common mappings for DAX/GER40 in your setup
    if sym in ["GER40", "DE40", "DAX", "GERMANY40", "GERMANY 40"]:
        return IG_EPIC_GER40

    # If user accidentally sends the IG epic as symbol
    if sym.startswith("IX.") or sym.startswith("CS.") or sym.startswith("UA."):
        return sym

    return ""


def ig_get_positions(h: dict) -> list:
    url = f"{IG_BASE}/positions"
    r = requests.get(url, headers=h, timeout=20)
    log_line({"kind": "ig_positions", "status": r.status_code, "body": safe_json(r)})
    r.raise_for_status()
    data = r.json()
    return data.get("positions", [])


def ig_open_market(h: dict, epic: str, side: str, qty: float, currency: str = "EUR", expiry: str = "-") -> dict:
    """Open a MARKET position."""
    url = f"{IG_BASE}/positions/otc"
    direction = "BUY" if side.lower() == "buy" else "SELL"

    payload = {
        "epic": epic,
        "expiry": expiry,
        "direction": direction,
        "size": float(qty),
        "orderType": "MARKET",
        "currencyCode": currency,
        "forceOpen": True,
        "guaranteedStop": False,
    }

    r = requests.post(url, headers=h, json=payload, timeout=20)
    log_line({"kind": "ig_entry", "status": r.status_code, "payload": payload, "body": safe_json(r)})
    r.raise_for_status()
    return r.json()


def ig_close_deal(h: dict, deal_id: str, direction: str, size: float, currency: str, expiry: str) -> dict:
    """Close a position by dealId (MARKET). direction must be opposite of open direction."""
    url = f"{IG_BASE}/positions/otc"
    payload = {
        "dealId": deal_id,
        "direction": direction,
        "size": float(size),
        "orderType": "MARKET",
        "currencyCode": currency,
        "expiry": expiry,
        "forceOpen": True,
        "guaranteedStop": False,
    }

    r = requests.delete(url, headers=h, json=payload, timeout=20)
    log_line({"kind": "ig_exit", "status": r.status_code, "payload": payload, "body": safe_json(r)})
    r.raise_for_status()
    return r.json()


def ig_close_all_for_epic(h: dict, epic: str) -> dict:
    """Close ALL open positions for a given epic (handles multiple open legs)."""
    positions = ig_get_positions(h)
    matches = []
    for p in positions:
        m = p.get("market", {})
        pos = p.get("position", {})
        if m.get("epic") == epic:
            matches.append((m, pos))

    if not matches:
        raise RuntimeError("no open position found for epic")

    closed = []
    for m, pos in matches:
        deal_id = pos.get("dealId")
        open_dir = pos.get("direction")  # BUY/SELL
        size = pos.get("size", 0)
        currency = pos.get("currency", "EUR")
        expiry = m.get("expiry", "-")

        if not deal_id or not size:
            continue

        close_dir = "SELL" if open_dir == "BUY" else "BUY"
        res = ig_close_deal(h, deal_id, close_dir, size, currency, expiry)
        closed.append({"dealId": deal_id, "closed": res})

    return {"closedCount": len(closed), "closed": closed}


@app.get("/")
def home():
    return "OK", 200


@app.get("/health")
def health():
    return jsonify({"ok": True, "ts": now_iso()}), 200


@app.post("/webhook")
def webhook():
    data = request.get_json(silent=True) or {}
    # Always log incoming webhooks (without crashing if malformed)
    log_line({"kind": "webhook_in", "data": data})

    if not WEBHOOK_SECRET:
        log_line({"kind": "config_error", "error": "WEBHOOK_SECRET missing"})
        return jsonify({"ok": False, "error": "server not configured"}), 500

    if data.get("secret") != WEBHOOK_SECRET:
        return jsonify({"ok": False, "error": "bad secret"}), 401

    wtype = (data.get("type") or "").strip().lower()

    # Allow "test" pings
    if wtype == "test":
        return jsonify({"ok": True, "ignored": True}), 200

    epic = resolve_epic(data)
    if not epic:
        return jsonify({"ok": False, "error": "epic not resolved (set IG_EPIC_GER40 or send epic)"}), 400

    # Ensure IG env is set
    missing = [k for k, v in {
        "IG_API_KEY": IG_API_KEY,
        "IG_USERNAME": IG_USERNAME,
        "IG_PASSWORD": IG_PASSWORD,
        "IG_ACCOUNT_ID": IG_ACCOUNT_ID,
    }.items() if not v]
    if missing:
        return jsonify({"ok": False, "error": f"missing env: {', '.join(missing)}"}), 500

    try:
        h = ig_login()

        # Optional: choose account (recommended)
        # IG uses PUT /session to switch currentAccountId
        try:
            url = f"{IG_BASE}/session"
            payload = {"accountId": IG_ACCOUNT_ID, "defaultAccount": True}
            r = requests.put(url, headers={**h, "VERSION": "1"}, json=payload, timeout=20)
            log_line({"kind": "ig_set_account", "status": r.status_code, "payload": payload, "body": safe_json(r)})
        except Exception as e:
            log_line({"kind": "ig_set_account_error", "error": str(e)})

        # ENTRY
        if wtype == "entry":
            side = (data.get("side") or "buy").lower()
            qty = float(data.get("qty") or 1)

            res = ig_open_market(h, epic, side, qty)
            out = {"ok": True, "entry": res}
            log_line({"kind": "webhook_out", "result": out})
            return jsonify(out), 200

        # EXIT (close all for epic)
        if wtype == "exit":
            res = ig_close_all_for_epic(h, epic)
            out = {"ok": True, "exit": res}
            log_line({"kind": "webhook_out", "result": out})
            return jsonify(out), 200

        # Unknown types -> ignore safely
        out = {"ok": True, "ignored": True, "reason": "unknown type"}
        log_line({"kind": "webhook_out", "result": out})
        return jsonify(out), 200

    except Exception as e:
        log_line({"kind": "webhook_error", "error": str(e), "data": data})
        return jsonify({"ok": False, "error": str(e)}), 500

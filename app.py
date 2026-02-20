import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# =========================
# ENV VARS (Render)
# =========================
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

IG_API_KEY     = os.environ.get("IG_API_KEY", "")
IG_USERNAME    = os.environ.get("IG_USERNAME", "")
IG_PASSWORD    = os.environ.get("IG_PASSWORD", "")
IG_ACCOUNT_ID  = os.environ.get("IG_ACCOUNT_ID", "")
IG_EPIC_GER40  = os.environ.get("IG_EPIC_GER40", "")

IG_BASE = "https://demo-api.ig.com/gateway/deal"  # Demo


# =========================
# IG HELPERS
# =========================
def ig_login_tokens():
    """Login, return (CST, X-SECURITY-TOKEN)."""
    url = f"{IG_BASE}/session"
    headers = {
        "X-IG-API-KEY": IG_API_KEY,
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json; charset=UTF-8",
        "VERSION": "2",
    }
    payload = {
        "identifier": IG_USERNAME,
        "password": IG_PASSWORD,
        "encryptedPassword": False,
    }

    r = requests.post(url, headers=headers, json=payload, timeout=20)
    r.raise_for_status()

    cst = r.headers.get("CST")
    sec = r.headers.get("X-SECURITY-TOKEN")
    if not cst or not sec:
        raise RuntimeError("IG login ok but tokens missing (CST / X-SECURITY-TOKEN)")

    return cst, sec


def ig_headers(version: str = "2", with_account: bool = False):
    """Build IG headers for authenticated requests."""
    cst, sec = ig_login_tokens()
    h = {
        "X-IG-API-KEY": IG_API_KEY,
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json; charset=UTF-8",
        "CST": cst,
        "X-SECURITY-TOKEN": sec,
        "VERSION": version,
    }
    if with_account and IG_ACCOUNT_ID:
        h["IG-ACCOUNT-ID"] = IG_ACCOUNT_ID
    return h


def ig_get_positions():
    """Return list of positions from IG (list of dicts)."""
    h = ig_headers(version="2", with_account=True)
    r = requests.get(f"{IG_BASE}/positions", headers=h, timeout=20)
    r.raise_for_status()
    payload = r.json()
    return payload.get("positions", [])


def pick_first_position_for_epic(epic: str):
    """Pick first open position matching epic. Returns IG position item or None."""
    positions = ig_get_positions()
    for p in positions:
        pos = p.get("position", {})
        if pos.get("epic") == epic:
            return p
    return None


# =========================
# ROUTES
# =========================
@app.get("/")
def home():
    return "OK", 200


@app.post("/webhook")
def webhook():
    data = request.get_json(silent=True) or {}

    # Secret check
    if data.get("secret") != WEBHOOK_SECRET:
        return jsonify({"ok": False, "error": "bad secret"}), 401

    print("WEBHOOK RECEIVED:", data, flush=True)
    t = data.get("type")

    # =========================
    # POSITIONS (Deal IDs holen)
    # =========================
    if t == "positions":
        try:
            positions = ig_get_positions()
            return jsonify({"ok": True, "positions": positions}), 200
        except Exception as e:
            print("POSITIONS ERROR:", str(e), flush=True)
            return jsonify({"ok": False, "error": str(e)}), 500

    # =========================
    # ENTRY (BUY)
    # =========================
    if t == "entry":
        try:
            h = ig_headers(version="2", with_account=True)
            qty = float(data.get("qty", 1))

            order = {
                "epic": IG_EPIC_GER40,
                "direction": "BUY",
                "size": qty,
                "orderType": "MARKET",
                "expiry": "-",
                "forceOpen": True,
                "guaranteedStop": False,
                "currencyCode": "EUR",
            }

            r = requests.post(f"{IG_BASE}/positions/otc", headers=h, json=order, timeout=20)
            print("IG ENTRY:", r.status_code, r.text, flush=True)
            r.raise_for_status()

            return jsonify({"ok": True, "entry": r.json()}), 200

        except Exception as e:
            print("ENTRY ERROR:", str(e), flush=True)
            return jsonify({"ok": False, "error": str(e)}), 500

    # =========================
    # EXIT (Close)
    # - If dealId provided -> close that
    # - Else -> close first open position for IG_EPIC_GER40
    # =========================
    if t == "exit":
        try:
            qty = float(data.get("qty", 1))

            deal_id = data.get("dealId")
            if not deal_id:
                picked = pick_first_position_for_epic(IG_EPIC_GER40)
                if not picked:
                    return jsonify({"ok": False, "error": "no open position found for epic"}), 404
                deal_id = picked.get("position", {}).get("dealId")
                if not deal_id:
                    return jsonify({"ok": False, "error": "dealId missing in picked position"}), 500

            close_order = {
                "dealId": deal_id,
                "direction": "SELL",  # closes LONG. (Short support comes later)
                "size": qty,
                "orderType": "MARKET",
                "timeInForce": "FILL_OR_KILL",
            }

            # IG expects DELETE on /positions/otc.
            # We use POST + X-HTTP-Method-Override to avoid some proxies blocking DELETE.
            h = ig_headers(version="1", with_account=False)
            h["X-HTTP-Method-Override"] = "DELETE"

            r = requests.post(f"{IG_BASE}/positions/otc", headers=h, json=close_order, timeout=20)
            print("IG EXIT:", r.status_code, r.text, flush=True)
            r.raise_for_status()

            return jsonify({"ok": True, "exit": r.json(), "dealId": deal_id}), 200

        except Exception as e:
            print("EXIT ERROR:", str(e), flush=True)
            return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({"ok": True, "ignored": True}), 200

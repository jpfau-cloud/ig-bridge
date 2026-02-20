import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# =========================
# ENV (Render)
# =========================
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

IG_API_KEY     = os.environ.get("IG_API_KEY", "")
IG_USERNAME    = os.environ.get("IG_USERNAME", "")
IG_PASSWORD    = os.environ.get("IG_PASSWORD", "")
IG_ACCOUNT_ID  = os.environ.get("IG_ACCOUNT_ID", "")
IG_EPIC_GER40  = os.environ.get("IG_EPIC_GER40", "")

IG_BASE = "https://demo-api.ig.com/gateway/deal"  # Demo


# =========================
# IG LOGIN / HEADERS
# =========================
def ig_login_tokens():
    h = {
        "X-IG-API-KEY": IG_API_KEY,
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json; charset=UTF-8",
        "VERSION": "2",
    }
    payload = {"identifier": IG_USERNAME, "password": IG_PASSWORD, "encryptedPassword": False}
    r = requests.post(f"{IG_BASE}/session", headers=h, json=payload, timeout=20)
    r.raise_for_status()
    cst = r.headers.get("CST")
    sec = r.headers.get("X-SECURITY-TOKEN")
    if not cst or not sec:
        raise RuntimeError("IG login ok but tokens missing")
    return cst, sec


def ig_headers(version="2", include_account=False):
    cst, sec = ig_login_tokens()
    h = {
        "X-IG-API-KEY": IG_API_KEY,
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json; charset=UTF-8",
        "CST": cst,
        "X-SECURITY-TOKEN": sec,
        "VERSION": str(version),
    }
    if include_account and IG_ACCOUNT_ID:
        h["IG-ACCOUNT-ID"] = IG_ACCOUNT_ID
    return h


# =========================
# ROUTES
# =========================
@app.get("/")
def home():
    return "OK", 200


@app.post("/webhook")
def webhook():
    data = request.get_json(silent=True) or {}

    if data.get("secret") != WEBHOOK_SECRET:
        return jsonify({"ok": False, "error": "bad secret"}), 401

    print("WEBHOOK:", data, flush=True)

    t = data.get("type")

    # =========================
    # POSITIONS
    # =========================
    if t == "positions":
        try:
            h = ig_headers(version="2", include_account=True)
            r = requests.get(f"{IG_BASE}/positions", headers=h, timeout=20)
            print("POSITIONS RAW:", r.status_code, r.text[:1000], flush=True)
            r.raise_for_status()
            return jsonify({"ok": True, "positions": r.json().get("positions", [])}), 200
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    # =========================
    # ENTRY (BUY market)
    # =========================
    if t == "entry":
        try:
            h = ig_headers(version="2", include_account=True)
            order = {
                "epic": IG_EPIC_GER40,
                "direction": "BUY",
                "size": float(data.get("qty", 1)),
                "orderType": "MARKET",
                "expiry": "-",
                "forceOpen": True,
                "guaranteedStop": False,
                "currencyCode": "EUR",
            }
            r = requests.post(f"{IG_BASE}/positions/otc", headers=h, json=order, timeout=20)
            print("ENTRY RAW:", r.status_code, r.text, flush=True)
            r.raise_for_status()
            return jsonify({"ok": True, "entry": r.json()}), 200
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    # =========================
    # EXIT (CLOSE) - requires dealId
    # =========================
    if t == "exit":
        try:
            deal_id = data.get("dealId")
            if not deal_id:
                return jsonify({"ok": False, "error": "dealId required"}), 400

            close_order = {
                "dealId": deal_id,
                "direction": "SELL",
                "size": float(data.get("qty", 1)),
                "orderType": "MARKET",
                "timeInForce": "FILL_OR_KILL",
                "forceOpen": False,   # <<< IMPORTANT: must not be null
            }

            # IG close expects DELETE /positions/otc
            h = ig_headers(version="1", include_account=False)
            h["X-HTTP-Method-Override"] = "DELETE"

            r = requests.post(f"{IG_BASE}/positions/otc", headers=h, json=close_order, timeout=20)
            print("EXIT RAW:", r.status_code, r.text, flush=True)
            r.raise_for_status()
            return jsonify({"ok": True, "exit": r.json()}), 200

        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({"ok": True, "ignored": True}), 200

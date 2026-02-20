import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Render Env
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
IG_API_KEY     = os.environ.get("IG_API_KEY", "")
IG_USERNAME    = os.environ.get("IG_USERNAME", "")
IG_PASSWORD    = os.environ.get("IG_PASSWORD", "")
IG_ACCOUNT_ID  = os.environ.get("IG_ACCOUNT_ID", "")
IG_EPIC_GER40   = os.environ.get("IG_EPIC_GER40", "")

IG_BASE = "https://demo-api.ig.com/gateway/deal"  # Demo

def ig_login():
    """Login and return session headers (CST + X-SECURITY-TOKEN)."""
    url = f"{IG_BASE}/session"
    headers = {
        "X-IG-API-KEY": IG_API_KEY,
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json; charset=UTF-8",
        "VERSION": "2",
    }
    payload = {"identifier": IG_USERNAME, "password": IG_PASSWORD, "encryptedPassword": False}
    r = requests.post(url, headers=headers, json=payload, timeout=20)
    r.raise_for_status()
    cst = r.headers.get("CST")
    sec = r.headers.get("X-SECURITY-TOKEN")
    if not cst or not sec:
        raise RuntimeError("IG login ok but tokens missing")
    return {
        "X-IG-API-KEY": IG_API_KEY,
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json; charset=UTF-8",
        "CST": cst,
        "X-SECURITY-TOKEN": sec,
    }

@app.get("/")
def home():
    return "OK", 200

@app.post("/webhook")
def webhook():
    data = request.get_json(silent=True) or {}

    # 1) Secret check
    if not WEBHOOK_SECRET or data.get("secret") != WEBHOOK_SECRET:
        return jsonify({"ok": False, "error": "bad secret"}), 401

    print("WEBHOOK RECEIVED:", data, flush=True)

    # 2) Only handle entry for now
    if data.get("type") != "entry":
        return jsonify({"ok": True, "ignored": True}), 200

    # 3) Place demo order (simple market BUY)
    try:
        h = ig_login()
        h["VERSION"] = "2"
        h["IG-ACCOUNT-ID"] = IG_ACCOUNT_ID  # helps if multiple accounts

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
        print("IG ORDER HTTP:", r.status_code, r.text, flush=True)
        r.raise_for_status()

        resp = r.json()
        return jsonify({"ok": True, "dealReference": resp.get("dealReference")}), 200

    except Exception as e:
        print("IG ERROR:", str(e), flush=True)
        return jsonify({"ok": False, "error": str(e)}), 500

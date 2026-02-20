import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# =========================
# ENV
# =========================
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

IG_API_KEY     = os.environ.get("IG_API_KEY", "")
IG_USERNAME    = os.environ.get("IG_USERNAME", "")
IG_PASSWORD    = os.environ.get("IG_PASSWORD", "")
IG_ACCOUNT_ID  = os.environ.get("IG_ACCOUNT_ID", "")
IG_EPIC_GER40  = os.environ.get("IG_EPIC_GER40", "")

IG_BASE = "https://demo-api.ig.com/gateway/deal"


# =========================
# IG LOGIN
# =========================
def ig_login():
    headers = {
        "X-IG-API-KEY": IG_API_KEY,
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json; charset=UTF-8",
        "VERSION": "2"
    }

    payload = {
        "identifier": IG_USERNAME,
        "password": IG_PASSWORD,
        "encryptedPassword": False
    }

    r = requests.post(f"{IG_BASE}/session", headers=headers, json=payload, timeout=20)
    r.raise_for_status()

    return {
        "X-IG-API-KEY": IG_API_KEY,
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json; charset=UTF-8",
        "CST": r.headers["CST"],
        "X-SECURITY-TOKEN": r.headers["X-SECURITY-TOKEN"]
    }


@app.get("/")
def home():
    return "OK", 200


@app.post("/webhook")
def webhook():
    data = request.get_json(silent=True) or {}

    if data.get("secret") != WEBHOOK_SECRET:
        return jsonify({"ok": False, "error": "bad secret"}), 401

    print("WEBHOOK:", data, flush=True)

    # =========================
    # POSITIONS
    # =========================
    if data.get("type") == "positions":
        try:
            h = ig_login()
            h["VERSION"] = "2"
            h["IG-ACCOUNT-ID"] = IG_ACCOUNT_ID

            r = requests.get(f"{IG_BASE}/positions", headers=h, timeout=20)
            r.raise_for_status()
            return jsonify(r.json()), 200

        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500


    # =========================
    # ENTRY
    # =========================
    if data.get("type") == "entry":
        try:
            h = ig_login()
            h["VERSION"] = "2"
            h["IG-ACCOUNT-ID"] = IG_ACCOUNT_ID

            order = {
                "epic": IG_EPIC_GER40,
                "direction": "BUY",
                "size": float(data.get("qty", 1)),
                "orderType": "MARKET",
                "expiry": "-",
                "forceOpen": True,
                "guaranteedStop": False,
                "currencyCode": "EUR"
            }

            r = requests.post(f"{IG_BASE}/positions/otc", headers=h, json=order, timeout=20)
            print("ENTRY:", r.status_code, r.text, flush=True)
            r.raise_for_status()

            return jsonify(r.json()), 200

        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500


    # =========================
    # EXIT
    # =========================
    if data.get("type") == "exit":
        try:
            h = ig_login()
            h["VERSION"] = "1"
            h["X-HTTP-Method-Override"] = "DELETE"

            deal_id = data.get("dealId")
            if not deal_id:
                return jsonify({"ok": False, "error": "dealId required"}), 400

            close_order = {
                "dealId": deal_id,
                "epic": IG_EPIC_GER40,
                "direction": "SELL",
                "size": float(data.get("qty", 1)),
                "orderType": "MARKET",
                "timeInForce": "FILL_OR_KILL",
                "forceOpen": False,
                "guaranteedStop": False,
                "currencyCode": "EUR"
            }

            r = requests.post(f"{IG_BASE}/positions/otc", headers=h, json=close_order, timeout=20)
            print("EXIT:", r.status_code, r.text, flush=True)
            r.raise_for_status()

            return jsonify(r.json()), 200

        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500


    return jsonify({"ok": True, "ignored": True}), 200

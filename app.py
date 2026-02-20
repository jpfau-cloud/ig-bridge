import os
from flask import Flask, request, jsonify

app = Flask(__name__)

SECRET = os.environ.get("WEBHOOK_SECRET", "DEIN_TOKEN")

@app.get("/")
def home():
    return "OK", 200

@app.post("/webhook")
def webhook():
    data = request.get_json(silent=True) or {}

    if data.get("secret") != SECRET:
        return jsonify({"ok": False, "error": "bad secret"}), 401

    print("WEBHOOK RECEIVED:", data, flush=True)

    return jsonify({"ok": True}), 200

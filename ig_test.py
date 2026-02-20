import requests
import json

BASE = "https://demo-api.ig.com/gateway/deal"

API_KEY = input("IG API Key: ")
USERNAME = input("IG Username: ")
PASSWORD = input("IG Password: ")

headers = {
    "X-IG-API-KEY": API_KEY,
    "Content-Type": "application/json; charset=UTF-8",
    "Accept": "application/json; charset=UTF-8",
    "VERSION": "2"
}

# Login
login_payload = {
    "identifier": USERNAME,
    "password": PASSWORD,
    "encryptedPassword": False
}

login = requests.post(BASE + "/session", headers=headers, json=login_payload)
print("Login HTTP:", login.status_code)

CST = login.headers.get("CST")
SEC = login.headers.get("X-SECURITY-TOKEN")

if not CST:
    print("Login fehlgeschlagen")
    exit()

# Header erweitern
headers["CST"] = CST
headers["X-SECURITY-TOKEN"] = SEC
headers["VERSION"] = "2"

# 🔴 TEST ORDER (Market BUY 1 Deutschland 40)
order = {
    "epic": "IX.D.DAX.IFMM.IP",
    "direction": "BUY",
    "size": 1,
    "orderType": "MARKET",
    "expiry": "-",
    "forceOpen": True,
    "guaranteedStop": False,
    "currencyCode": "EUR"
}

response = requests.post(BASE + "/positions/otc", headers=headers, json=order)

print("Order HTTP:", response.status_code)
print(response.text)
# 🔎 Deal-Status prüfen
deal_ref = response.json().get("dealReference")

headers["VERSION"] = "1"

confirm = requests.get(BASE + "/confirms/" + deal_ref, headers=headers)

print("Confirm HTTP:", confirm.status_code)
print(confirm.text)

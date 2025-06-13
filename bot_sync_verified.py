
from flask import Flask, request, jsonify
from ib_insync import *
import asyncio
import traceback
from datetime import datetime
import pytz
import os
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

print("🚀 Running FULLY SYNC CLEAN VERSION")

# Load environment (automatically from Railway or local .env)
load_dotenv()

MAILGUN_API_KEY = os.getenv("MAILGUN_API_KEY")
MAILGUN_DOMAIN = os.getenv("MAILGUN_DOMAIN")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")
SECRET_TOKEN = os.getenv("SECRET_TOKEN", "my_secure_token_123")
ACCOUNT_SIZE = float(os.getenv("ACCOUNT_SIZE", 1000))
RISK_PERCENT = float(os.getenv("RISK_PERCENT", 1)) / 100
TRADE_LOG_FILE = os.getenv("TRADE_LOG_FILE", "executed_trades.csv")
TEST_MODE = False

app = Flask(__name__)

ib = IB()

@app.before_request
def catch_all_requests():
    print("📩 Incoming Request")
    print("Method:", request.method)
    print("Path:", request.path)
    try:
        print("Payload:", request.get_json(force=True))
    except Exception as e:
        print("⚠️ Error parsing JSON:", str(e))

def send_email(subject, text):
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER
        msg.set_content(text)

        response = requests.post(
            f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages",
            auth=("api", MAILGUN_API_KEY),
            data={
                "from": EMAIL_SENDER,
                "to": EMAIL_RECEIVER,
                "subject": subject,
                "text": text
            }
        )
        print("📧 Email sent:", response.status_code)
    except Exception as e:
        print("❌ Failed to send email:", str(e))

def calculate_qty(entry, stop, risk_pct, account_size):
    risk_amount = account_size * risk_pct
    stop_diff = abs(entry - stop)
    return max(1, int(risk_amount / stop_diff)) if stop_diff else 1

def log_trade(symbol, entry, qty, stop_loss, take_profit, side, reason="entry"):
    now = datetime.now()
    with open(TRADE_LOG_FILE, mode='a') as file:
        file.write(f"{now},{symbol},{side},{qty},{entry},{stop_loss},{take_profit},{reason}\n")

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        token = data.get("token")
        if token != SECRET_TOKEN:
            return jsonify({"error": "unauthorized"}), 403

        symbol = data.get("symbol")
        side = data.get("side")
        entry = float(data.get("entry"))
        stop = float(data.get("stop"))
        qty = calculate_qty(entry, stop, RISK_PERCENT, ACCOUNT_SIZE)
        tp = entry + (entry - stop) * 2 if side == "BUY" else entry - (stop - entry) * 2

        if TEST_MODE:
            print(f"🧪 TEST MODE: {side} {qty} {symbol} at {entry}")
            return jsonify({"status": "test", "message": "Simulation successful"}), 200

        ib.connect("127.0.0.1", 7497, clientId=22)
        if not ib.isConnected():
            return jsonify({"error": "IBKR not connected"}), 500

        contract = Stock(symbol, "SMART", "USD")
        ib.qualifyContracts(contract)

        bracket = ib.bracketOrder(
            action=side,
            quantity=qty,
            limitPrice=entry,
            takeProfitPrice=tp,
            stopLossPrice=stop
        )
        bracket[0].transmit = False
        bracket[1].transmit = True
        bracket[2].transmit = True

        for order in bracket:
            ib.placeOrder(contract, order)

        send_email("Trade Executed", f"{side} {qty} {symbol} @ {entry}")
        log_trade(symbol, entry, qty, stop, tp, side)
        return jsonify({"status": "success"}), 200

    except Exception as e:
        error_msg = str(e)
        send_email("Bot Error", error_msg)
        print("❌ Error:", error_msg)
        return jsonify({"error": error_msg}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)

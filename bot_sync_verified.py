
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

# Load environment
from pathlib import Path
env_path = Path('/home/ubuntu/Desktop/.env')
load_dotenv(dotenv_path=env_path)

MAILGUN_API_KEY = os.getenv("MAILGUN_API_KEY")
MAILGUN_DOMAIN = os.getenv("MAILGUN_DOMAIN")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")
SECRET_TOKEN = os.getenv("SECRET_TOKEN", "my_secure_token_123")

ACCOUNT_SIZE = 1000
RISK_PERCENT = 0.01
TRADE_LOG_FILE = "executed_trades.csv"
TEST_MODE = False  # ⚠️ TRUE = TEST MODE ENABLED – Real trades will execute

app = Flask(__name__)

@app.before_request
def catch_and_log_everything():
    print("📩 Incoming route raw request")
    print("🟡 Method:", request.method)
    print("🟡 Path:", request.path)
    print("🟡 Content-Type:", request.content_type)
    try:
        print("📨 Raw Body:", request.data.decode("utf-8", errors="ignore"))
    except Exception as e:
        print("❌ Error decoding body:", e)

ib = IB()

def send_email(subject, text):
    try:
        print("📧 Sending email...")
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
        print("📤 Email status:", response.status_code)
        print("📤 Response:", response.text)
    except Exception as e:
        print("❌ Email send failed:", e)

def calculate_qty(entry, stop, risk_pct, account_size):
    risk_amount = account_size * risk_pct
    stop_diff = abs(entry - stop)
    return max(1, int(risk_amount / stop_diff)) if stop_diff else 1

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    token = data.get("token")
    symbol = data.get("symbol")
    side = data.get("side")
    entry = float(data.get("entry"))
    stop = float(data.get("stop"))

    if token != SECRET_TOKEN:
        return jsonify({"error": "unauthorized"}), 403

    qty = calculate_qty(entry, stop, RISK_PERCENT, ACCOUNT_SIZE)
    tp_price = entry + (entry - stop) * 2 if side == "BUY" else entry - (stop - entry) * 2
    stop_price = stop

    if TEST_MODE:
        print("🧪 TEST MODE ENABLED – No real order placed.")
        print(f"Would execute: {side} {qty} {symbol} @ {entry}")
        return jsonify({"status": "test", "message": "Test mode active"}), 200

    try:
        ib.connect("127.0.0.1", 7497, clientId=22)

        if not ib.isConnected():
            print("❌ Connection to IBKR failed.")
            return jsonify({"status": "error", "message": "IBKR connection failed"}), 500
        else:
            print("✅ Connected to IBKR")

            contract = Stock(symbol, "SMART", "USD")
            ib.qualifyContracts(contract)

            bracket = ib.bracketOrder(
                action=side,
                quantity=qty,
                limitPrice=entry,
                takeProfitPrice=tp_price,
                stopLossPrice=stop_price
            )

            bracket[0].transmit = False
            bracket[1].transmit = True
            bracket[2].transmit = True

            for order in bracket:
                ib.placeOrder(contract, order)

            print("✅ Order sent:", bracket)
            send_email("Trade Executed", f"{side} {qty} {symbol} @ {entry}")
            return jsonify({"status": "success", "message": "Order executed"}), 200

    except Exception as e:
        print("❌ Bot Error:", str(e))
        send_email("Bot Error", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)



def log_trade(symbol, entry, qty, stop_loss, take_profit, side, reason="entry"):
    now = datetime.now()
    file_exists = os.path.isfile(TRADE_LOG_FILE)
    with open(TRADE_LOG_FILE, mode='a', newline='') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(["Date", "Time", "Symbol", "Side", "Qty", "Entry", "Stop Loss", "Take Profit", "Reason"])
        writer.writerow([
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S"),
            symbol.upper(),
            side.upper(),
            qty,
            round(entry, 4),
            round(stop_loss, 4),
            round(take_profit, 4),
            reason
        ])

def log_exit(symbol, exit_price, qty, reason="exit"):
    now = datetime.now()
    file_exists = os.path.isfile(TRADE_LOG_FILE)
    with open(TRADE_LOG_FILE, mode='a', newline='') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(["Date", "Time", "Symbol", "Side", "Qty", "Entry", "Stop Loss", "Take Profit", "Reason"])
        writer.writerow([
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S"),
            symbol.upper(),
            "SELL",
            qty,
            round(exit_price, 4),
            "-", "-",  # No SL/TP on exit logs
            reason
        ])

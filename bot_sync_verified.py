from flask import Flask, request, jsonify
from ib_insync import *
from datetime import datetime
import pytz
import os
import requests
import csv
from dotenv import load_dotenv
import pathlib
import traceback
import json

print("✅ Running FULLY SYNC CLEAN VERSION")

# Load environment
env_path = pathlib.Path("C:/Users/kb767/OneDrive/Desktop/.env")
load_dotenv(dotenv_path=env_path)

MAILGUN_API_KEY = os.getenv("MAILGUN_API_KEY")
MAILGUN_DOMAIN = os.getenv("MAILGUN_DOMAIN")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")
SECRET_TOKEN = os.getenv("SECRET_TOKEN") or "my_secure_token_123"

ACCOUNT_SIZE = 1000
RISK_PERCENT = 0.01
TRADE_LOG_FILE = "executed_trades.csv"
TEST_MODE = False  # 🔴 LIVE MODE ENABLED – Real trades will execute


app = Flask(__name__)
@app.before_request
def catch_and_log_everything():
    print("🛑 Pre-route raw request")
    print("🛑 Method:", request.method)
    print("🛑 Path:", request.path)
    print("🛑 Content-Type:", request.content_type)
    try:
        print("🛑 Raw Body:", request.data.decode('utf-8', errors='ignore'))
    except Exception as e:
        print("🛑 Error decoding body:", e)

ib = IB()

def is_trading_hours():
    eastern = pytz.timezone('US/Eastern')
    now = datetime.now(eastern)
    return now.weekday() < 5 and 7 <= now.hour < 19

def send_email(subject, text):
    try:
        print("📧 Sending email...")
        print("Subject:", subject)
        print("Body:", text)

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

        print("📬 Email status:", response.status_code)
        print("📬 Response:", response.text)

    except Exception as e:
        print("📧 Email error:", e)

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

def calculate_qty(entry, stop, risk_pct, account_size):
    risk_amount = account_size * risk_pct
    stop_diff = abs(entry - stop)
    return max(1, int(risk_amount / stop_diff)) if stop_diff else 1

def execute_trade(data):
    symbol = data["symbol"]
    side = data["side"].upper()
    entry = float(data["entry"])
    stop = float(data["stop"])
    qty = calculate_qty(entry, stop, RISK_PERCENT, ACCOUNT_SIZE)

    sl_buffer = 0.02 * entry
    tp_buffer = 0.04 * entry
    stop_price = round(entry - sl_buffer, 2)
    tp_price = round(entry + tp_buffer, 2)

    if TEST_MODE:
        print("🧪 TEST MODE ENABLED – No real order placed.")
        print(f"Would execute: {side} {qty} {symbol} @ {entry}")
    else:
        ib.connect("127.0.0.1", 7497, clientId=22)
        contract = Stock(symbol, "SMART", "USD")
        ib.qualifyContracts(contract)

        bracket = ib.bracketOrder(
            action=side,
            quantity=qty,
            limitPrice=entry,
            takeProfitPrice=tp_price,
            stopLossPrice=stop_price
        )

        # Ensure proper order chaining with transmit flags
        bracket[0].transmit = False  # Entry order
        bracket[1].transmit = False  # Take profit
        bracket[2].transmit = True   # Stop loss (last leg triggers full bracket)

        for order in bracket:
            ib.placeOrder(contract, order)

        log_trade(symbol, entry, qty, stop_price, tp_price, side, reason="entry")
        send_email("✅ Trade Executed", f"{side} {qty} {symbol} @ {entry}")


@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        print("📥 Incoming webhook request...")
        content_type = request.content_type
        raw_body = request.data.decode('utf-8')

        print("🔍 Content-Type:", content_type)
        print("🔍 Raw Body:", raw_body)

        # ✅ Validate raw JSON body
        if not raw_body.strip():
            raise ValueError("Empty body received in webhook")

        try:
            data = json.loads(raw_body)
        except Exception as e:
            print("❌ JSON parsing failed:", e)
            raise ValueError("Invalid JSON format: " + str(e))

        print("📥 Parsed data:", data)

        if data.get("token") != SECRET_TOKEN:
            return jsonify({"status": "unauthorized", "message": "Invalid token"}), 403

        if not is_trading_hours():
            send_email("⏰ Blocked Outside Hours", f"Blocked alert:\n{data}")
            return jsonify({"status": "blocked", "message": "Outside trading hours"}), 403

        import asyncio
        asyncio.set_event_loop(asyncio.new_event_loop())

        execute_trade(data)
        return jsonify({"status": "executed", "message": f"Trade executed for {data['symbol']}"}), 200

    except Exception as e:
        traceback.print_exc()
        send_email("❌ Bot Error", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500


        print("📥 Parsed data:", data)

        if data.get("token") != SECRET_TOKEN:
            return jsonify({"status": "unauthorized", "message": "Invalid token"}), 403

        if not is_trading_hours():
            send_email("⏰ Blocked Outside Hours", f"Blocked alert:\n{data}")
            return jsonify({"status": "blocked", "message": "Outside trading hours"}), 403

        import asyncio
        asyncio.set_event_loop(asyncio.new_event_loop())

        execute_trade(data)
        return jsonify({"status": "executed", "message": f"Trade executed for {data['symbol']}"}), 200

    except Exception as e:
        traceback.print_exc()
        send_email("❌ Bot Error", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500

@app.errorhandler(404)
def route_not_found(e):
    print("❌ 404 - Not Found")
    print("🔍 Path:", request.path)
    print("🔍 Method:", request.method)
    print("🔍 Raw Body:", request.data.decode('utf-8', errors='ignore'))
    return jsonify({"error": "Not Found"}), 404

@app.errorhandler(405)
def method_not_allowed(e):
    print("❌ 405 - Method Not Allowed")
    print("🔍 Path:", request.path)
    print("🔍 Method:", request.method)
    return jsonify({"error": "Method Not Allowed"}), 405

@app.route("/", methods=["GET", "POST"])
def root_debug():
    print("⚠️  Hit root path '/'")
    print("⚠️  Method:", request.method)
    print("⚠️  Content-Type:", request.content_type)
    try:
        print("⚠️  Raw Body:", request.data.decode('utf-8', errors='ignore'))
    except Exception as e:
        print("⚠️  Body decode error:", e)
    return "Root path hit — expected /webhook", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)


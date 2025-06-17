from flask import Flask, request, jsonify
from ib_insync import *
import asyncio, os, traceback
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
ib = IB()
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

SECRET_TOKEN = os.getenv("SECRET_TOKEN")
ACCOUNT_SIZE = float(os.getenv("ACCOUNT_SIZE", "1000"))
RISK_PERCENT = float(os.getenv("RISK_PERCENT", "1"))

def calculate_qty(entry, stop, risk_percent, account_size):
    risk_amount = (risk_percent / 100) * account_size
    risk_per_share = abs(entry - stop)
    if risk_per_share == 0:
        raise ValueError("Risk per share is 0. Entry and Stop can't be equal.")
    return max(1, int(risk_amount / risk_per_share))

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True)
        token = data.get("token")
        if token != SECRET_TOKEN:
            return jsonify({"error": "unauthorized"}), 403

        symbol = data["symbol"]
        side = data["side"].upper()
        entry = float(data["entry"])
        stop = float(data["stop"])
        qty = calculate_qty(entry, stop, RISK_PERCENT, ACCOUNT_SIZE)
        tp = entry + (entry - stop) * 2 if side == "BUY" else entry - (stop - entry) * 2

        print(f"✅ Token matched – processing trade: {data}")

        ib.disconnect()
        ib.connect("127.0.0.1", 4002, clientId=22, timeout=10)

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

        # Required to allow fills after hours
        for o in bracket:
            o.outsideRth = True

        for order in bracket:
            ib.placeOrder(contract, order)

        print(f"✅ Order logged and sent for {symbol}")
        return jsonify({"status": "success", "message": "Order sent"}), 200

    except Exception as e:
        print("❌ Webhook error:", e)
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

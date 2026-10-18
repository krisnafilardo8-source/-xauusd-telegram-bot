import os
import threading
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()

def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        app.logger.error("Telegram token/chat ID belum diatur.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        response = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=8,
        )
        response.raise_for_status()
    except requests.RequestException:
        app.logger.exception("Gagal mengirim pesan Telegram")

@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "xauusd-alert-relay"})

@app.post("/tv-webhook")
def tv_webhook():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "JSON object diperlukan"}), 400

    # TradingView alert message harus menyertakan field secret yang sama
    # dengan WEBHOOK_SECRET di .env. Jangan pernah masukkan token Telegram di Pine Script.
    if not WEBHOOK_SECRET or data.get("secret") != WEBHOOK_SECRET:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    action = str(data.get("action", "")).upper()
    symbol = str(data.get("symbol", "XAUUSD"))
    timeframe = str(data.get("timeframe", ""))
    price = data.get("price")
    entry = data.get("entry")
    sl = data.get("sl")
    tp = data.get("tp")
    reason = str(data.get("reason", "Konfirmasi support/resistance + candlestick"))
    timestamp = str(data.get("time", ""))

    if action not in {"BUY", "SELL"}:
        return jsonify({"ok": False, "error": "Action harus BUY atau SELL"}), 400

    message = (
        f"📊 XAUUSD {action} — ALERT\n"
        f"Simbol: {symbol}\n"
        f"Timeframe: {timeframe}\n"
        f"Harga saat sinyal: {price}\n"
        f"Entry acuan: {entry}\n"
        f"Stop Loss: {sl}\n"
        f"Take Profit: {tp}\n"
        f"Alasan: {reason}\n"
        f"Waktu chart: {timestamp}\n\n"
        "Catatan: notifikasi otomatis, bukan jaminan profit. Periksa spread dan chart broker sebelum entry."
    )

    # Balas webhook cepat; pengiriman Telegram berjalan di thread terpisah.
    threading.Thread(target=send_telegram, args=(message,), daemon=True).start()
    return jsonify({"ok": True, "received": True}), 200

if __name__ == "__main__":
    # Untuk uji lokal saja. Produksi perlu HTTPS dan server WSGI/reverse proxy.
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=False)

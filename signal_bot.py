
import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd
import requests

DATA_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/"
    "GC%3DF?range=5d&interval=15m"
)
WEBHOOK_URL = "https://krisnafilardo.pythonanywhere.com/tv-webhook"
STATE_FILE = "last_signal.txt"


def main():
    secret = os.environ.get("WEBHOOK_SECRET", "").strip()
    if not secret:
        raise RuntimeError("WEBHOOK_SECRET belum diatur di GitHub Secrets")

    response = requests.get(
        DATA_URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    response.raise_for_status()

    result = response.json()["chart"]["result"]
    if not result:
        raise RuntimeError("Yahoo Finance tidak mengembalikan data")

    data = result[0]
    timestamps = data.get("timestamp", [])
    quote = data["indicators"]["quote"][0]

    df = pd.DataFrame({
        "timestamp": timestamps,
        "close": quote["close"],
        "high": quote["high"],
        "low": quote["low"],
    }).dropna().copy()

    if len(df) < 60:
        raise RuntimeError("Data candle tidak cukup untuk analisis")

    # Hanya gunakan candle yang sudah selesai.
    now = datetime.now(timezone.utc).timestamp()
    df = df[df["timestamp"] + 15 * 60 <= now].copy()

    if len(df) < 60:
        print("Belum tersedia cukup candle yang sudah selesai.")
        return

    # Tolak data lama agar tidak menghasilkan sinyal dari harga usang.
    last_ts = int(df["timestamp"].iloc[-1])
    age_minutes = (now - (last_ts + 15 * 60)) / 60

    if age_minutes > 45:
        print("Data candle terakhir terlalu lama; tidak mengirim sinyal.")
        return

    close = df["close"]
    df["ema9"] = close.ewm(span=9, adjust=False).mean()
    df["ema21"] = close.ewm(span=21, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss
    df["rsi14"] = 100 - 100 / (1 + rs)

    previous_close = close.shift()
    true_range = pd.concat([
        df["high"] - df["low"],
        (df["high"] - previous_close).abs(),
        (df["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)

    df["atr14"] = true_range.ewm(
        alpha=1 / 14, adjust=False
    ).mean()

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    buy = (
        prev["ema9"] <= prev["ema21"]
        and curr["ema9"] > curr["ema21"]
        and curr["close"] > curr["ema50"]
        and curr["rsi14"] > 50
    )

    sell = (
        prev["ema9"] >= prev["ema21"]
        and curr["ema9"] < curr["ema21"]
        and curr["close"] < curr["ema50"]
        and curr["rsi14"] < 50
    )

    candle_id = str(last_ts)

    print(
        f"GC=F M15 | close={curr['close']:.2f} "
        f"| EMA9={curr['ema9']:.2f} "
        f"| EMA21={curr['ema21']:.2f} "
        f"| EMA50={curr['ema50']:.2f} "
        f"| RSI={curr['rsi14']:.2f}"
    )

    if not buy and not sell:
        print("Tidak ada sinyal baru.")
        return

    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as file:
            previous_id = file.read().strip()
        if previous_id == candle_id:
            print("Sinyal candle ini sudah diproses.")
            return

    action = "BUY" if buy else "SELL"
    entry = float(curr["close"])
    atr = float(curr["atr14"])

    if action == "BUY":
        sl = entry - 1.5 * atr
        tp = entry + 1.5 * atr * 1.5
    else:
        sl = entry + 1.5 * atr
        tp = entry - 1.5 * atr * 1.5

    candle_time = datetime.fromtimestamp(
        last_ts + 15 * 60, timezone.utc
    ).isoformat()

    payload = {
        "secret": secret,
        "symbol": "GC=F (Gold Futures COMEX)",
        "action": action,
        "timeframe": "15m",
        "price": round(entry, 2),
        "entry": round(entry, 2),
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "reason": "EMA 9/21 crossover + EMA 50 + RSI 14",
        "time": candle_time,
    }

    result = requests.post(
        WEBHOOK_URL, json=payload, timeout=20
    )
    result.raise_for_status()

    if not result.json().get("ok"):
        raise RuntimeError("Endpoint tidak mengonfirmasi penerimaan sinyal")

    # Simpan ID candle setelah server menerima sinyal.
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        file.write(candle_id)

    print(f"Sinyal {action} berhasil diterima endpoint.")


if __name__ == "__main__":
    main()

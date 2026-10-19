
import os
from datetime import datetime, timezone

import pandas as pd
import requests

WEBHOOK_URL = (
    "https://krisnafilardo.pythonanywhere.com/tv-webhook"
)
STATE_FILE = "last_signal.txt"


def get_candles(interval, period, minutes):
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        "GC%3DF"
    )
    response = requests.get(
        url,
        params={"range": period, "interval": interval},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=25,
    )
    response.raise_for_status()

    result = response.json()["chart"]["result"]
    if not result:
        raise RuntimeError("Data emas tidak tersedia")

    data = result[0]
    quote = data["indicators"]["quote"][0]

    df = pd.DataFrame({
        "timestamp": data.get("timestamp", []),
        "close": quote.get("close", []),
        "high": quote.get("high", []),
        "low": quote.get("low", []),
    }).dropna().copy()

    now = datetime.now(timezone.utc).timestamp()
    df = df[
        df["timestamp"] + minutes * 60 <= now
    ].copy()

    return df.reset_index(drop=True)


def add_indicators(df):
    df = df.copy()
    close = df["close"]

    df["ema9"] = close.ewm(
        span=9, adjust=False
    ).mean()
    df["ema21"] = close.ewm(
        span=21, adjust=False
    ).mean()
    df["ema50"] = close.ewm(
        span=50, adjust=False
    ).mean()
    df["ema200"] = close.ewm(
        span=200, adjust=False
    ).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(
        alpha=1 / 14, adjust=False
    ).mean()
    loss = (-delta.clip(upper=0)).ewm(
        alpha=1 / 14, adjust=False
    ).mean()

    rs = gain / loss
    df["rsi14"] = 100 - (100 / (1 + rs))

    previous_close = close.shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - previous_close).abs(),
        (df["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)

    df["atr14"] = tr.ewm(
        alpha=1 / 14, adjust=False
    ).mean()

    return df


def main():
    secret = os.environ.get("WEBHOOK_SECRET", "").strip()
    if not secret:
        raise RuntimeError("GitHub Secret WEBHOOK_SECRET belum ada")

    # H1 untuk arah tren; M15 untuk entry.
    h1 = get_candles("60m", "3mo", 60)
    m15 = get_candles("15m", "5d", 15)

    if len(h1) < 210 or len(m15) < 60:
        raise RuntimeError("Jumlah candle belum cukup")

    h1 = add_indicators(h1)
    m15 = add_indicators(m15)

    trend = h1.iloc[-1]
    prev = m15.iloc[-2]
    curr = m15.iloc[-1]

    # Tolak data yang terlalu lama.
    now = datetime.now(timezone.utc).timestamp()
    age = (now - (int(curr["timestamp"]) + 900)) / 60
    if age > 45:
        print("Data M15 terlalu lama. Tidak mengirim sinyal.")
        return

    uptrend = (
        trend["ema50"] > trend["ema200"]
        and trend["close"] > trend["ema50"]
    )
    downtrend = (
        trend["ema50"] < trend["ema200"]
        and trend["close"] < trend["ema50"]
    )

    buy = (
        uptrend
        and prev["ema9"] <= prev["ema21"]
        and curr["ema9"] > curr["ema21"]
        and curr["close"] > curr["ema50"]
        and 50 < curr["rsi14"] < 70
    )

    sell = (
        downtrend
        and prev["ema9"] >= prev["ema21"]
        and curr["ema9"] < curr["ema21"]
        and curr["close"] < curr["ema50"]
        and 30 < curr["rsi14"] < 50
    )

    print(
        f"GC=F M15 close={curr['close']:.2f} "
        f"RSI={curr['rsi14']:.2f} "
        f"| H1 EMA50={trend['ema50']:.2f} "
        f"EMA200={trend['ema200']:.2f}"
    )

    if not buy and not sell:
        print("Tidak ada sinyal yang memenuhi semua filter.")
        return

    candle_id = str(int(curr["timestamp"]))
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            if f.read().strip() == candle_id:
                print("Sinyal candle ini sudah pernah diproses.")
                return

    action = "BUY" if buy else "SELL"
    entry = float(curr["close"])
    atr = float(curr["atr14"])

    if not pd.notna(atr) or atr <= 0:
        raise RuntimeError("Nilai ATR tidak valid")

    # Risiko 1.5 ATR; target keuntungan 3 ATR.
    if action == "BUY":
        sl = entry - 1.5 * atr
        tp = entry + 3.0 * atr
    else:
        sl = entry + 1.5 * atr
        tp = entry - 3.0 * atr

    candle_time = datetime.fromtimestamp(
        int(curr["timestamp"]) + 900,
        timezone.utc,
    ).strftime("%Y-%m-%d %H:%M UTC")

    message = (
        f"XAUUSD SIGNAL BOT v2\n"
        f"Data: GC=F Gold Futures (bukan spot broker)\n"
        f"Timeframe: M15 | Trend: H1\n"
        f"Sinyal: {action}\n"
        f"Entry indikatif: {entry:.2f}\n"
        f"Stop Loss: {sl:.2f}\n"
        f"Take Profit: {tp:.2f}\n"
        f"RSI 14: {curr['rsi14']:.2f}\n"
        f"ATR 14: {atr:.2f}\n"
        f"Rasio risiko/target: 1:2\n"
        f"Waktu candle: {candle_time}\n"
        f"Catatan: Sinyal analisis, bukan jaminan profit."
    )

    payload = {
        "secret": secret,
        "symbol": "GC=F (Gold Futures COMEX)",
        "action": action,
        "timeframe": "15m",
        "price": round(entry, 2),
        "entry": round(entry, 2),
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "reason": "H1 trend + M15 EMA crossover + RSI + ATR",
        "time": candle_time,
        "message": message,
    }

    response = requests.post(
        WEBHOOK_URL, json=payload, timeout=25
    )
    response.raise_for_status()

    if not response.json().get("ok"):
        raise RuntimeError("Server belum mengonfirmasi sinyal")

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write(candle_id)

    print(f"Sinyal {action} terkirim ke endpoint.")


if __name__ == "__main__":
    main()


import os
import sys
import time
import requests
import pandas as pd

CHART_URL = "https://xaus.com/api/v1/chart"
RELAY_URL = "https://krisnafilardo.pythonanywhere.com/tv-webhook"

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
STATE_FILE = "last_candle.txt"

TIMEFRAME_SECONDS = 15 * 60
ATR_MULTIPLIER = 1.5
MAX_CANDLE_AGE_SECONDS = 45 * 60


def fetch_candles():
    response = requests.get(
        CHART_URL,
        params={
            "symbol": "xau",
            "range": "5d",
            "interval": "15m",
        },
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()
    points = data.get("points", [])

    if not points:
        raise RuntimeError("API XAUS tidak mengembalikan candle.")

    df = pd.DataFrame(points)

    required = ["t", "o", "h", "l", "c"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise RuntimeError(
            f"Kolom candle tidak lengkap: {missing}"
        )

    for col in required:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=required)
    df = df.sort_values("t").drop_duplicates("t")
    df["t"] = df["t"].astype("int64")

    now = int(time.time())

    # Gunakan hanya candle yang sudah selesai.
    df = df[df["t"] + TIMEFRAME_SECONDS <= now].copy()

    if len(df) < 60:
        raise RuntimeError(
            f"Candle tertutup tidak cukup: {len(df)}"
        )

    latest_age = now - int(df.iloc[-1]["t"])

    if latest_age > MAX_CANDLE_AGE_SECONDS:
        raise RuntimeError(
            f"Data candle terlalu lama: {latest_age} detik."
        )

    return df.reset_index(drop=True)


def calculate_indicators(df):
    close = df["c"]
    high = df["h"]
    low = df["l"]

    df["ema9"] = close.ewm(
        span=9, adjust=False
    ).mean()

    df["ema21"] = close.ewm(
        span=21, adjust=False
    ).mean()

    df["ema50"] = close.ewm(
        span=50, adjust=False
    ).mean()

    previous_close = close.shift(1)

    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    df["atr14"] = true_range.ewm(
        alpha=1 / 14,
        adjust=False,
        min_periods=14,
    ).mean()

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / 14,
        adjust=False,
        min_periods=14,
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / 14,
        adjust=False,
        min_periods=14,
    ).mean()

    rs = avg_gain / avg_loss
    df["rsi14"] = 100 - (100 / (1 + rs))

    # Kasus pergerakan satu arah ekstrem.
    df.loc[
        (avg_loss == 0) & (avg_gain > 0), "rsi14"
    ] = 100

    df.loc[
        (avg_gain == 0) & (avg_loss > 0), "rsi14"
    ] = 0

    df.loc[
        (avg_gain == 0) & (avg_loss == 0), "rsi14"
    ] = 50

    return df


def determine_signal(row):
    if row[
        ["ema9", "ema21", "ema50", "rsi14", "atr14"]
    ].isna().any():
        return "WAIT"

    buy = (
        row["ema9"] > row["ema21"]
        and row["ema21"] > row["ema50"]
        and row["rsi14"] > 50
        and row["c"] > row["ema9"]
    )

    sell = (
        row["ema9"] < row["ema21"]
        and row["ema21"] < row["ema50"]
        and row["rsi14"] < 50
        and row["c"] < row["ema9"]
    )

    if buy:
        return "BUY"

    if sell:
        return "SELL"

    return "WAIT"


def build_message(row, signal):
    candle_time = pd.to_datetime(
        int(row["t"]), unit="s", utc=True
    )

    lines = [
        "📊 XAUUSD SPOT SIGNAL | M15",
        f"Waktu candle: {candle_time:%d-%m-%Y %H:%M} UTC",
        f"Sinyal: {signal}",
        f"Close: {row['c']:.2f}",
        f"EMA 9: {row['ema9']:.2f}",
        f"EMA 21: {row['ema21']:.2f}",
        f"EMA 50: {row['ema50']:.2f}",
        f"RSI 14: {row['rsi14']:.2f}",
        f"ATR 14: {row['atr14']:.2f}",
    ]

    if signal == "BUY":
        entry = row["c"]
        sl = entry - ATR_MULTIPLIER * row["atr14"]
        lines.extend([
            f"Entry indikatif: {entry:.2f}",
            f"Stop Loss (1.5 x ATR): {sl:.2f}",
        ])
    elif signal == "SELL":
        entry = row["c"]
        sl = entry + ATR_MULTIPLIER * row["atr14"]
        lines.extend([
            f"Entry indikatif: {entry:.2f}",
            f"Stop Loss (1.5 x ATR): {sl:.2f}",
        ])
    else:
        lines.append("Entry/SL: belum ada — tunggu konfirmasi")

    lines.append(
        "Catatan: sinyal indikator, bukan jaminan hasil trading."
    )

    return "\n".join(lines)


def send_to_telegram(action, message):
    if action not in ("BUY", "SELL"):
        print(f"Tidak mengirim sinyal {action}.")
        return

    if not WEBHOOK_SECRET:
        raise RuntimeError(
            "Secret WEBHOOK_SECRET belum diatur."
        )

    # Catatan: format payload ini harus sesuai dengan app.py.
    # Relay sebelumnya menolak WAIT; respons berikut membantu
    # memeriksa format payload jika BUY/SELL juga ditolak.
    response = requests.post(
        RELAY_URL,
        json={
            "secret": WEBHOOK_SECRET,
            "action": action,
            "message": message,
        },
        timeout=30,
    )

    print("Status relay:", response.status_code)
    print("Respons relay:", response.text[:1000])

    response.raise_for_status()
    print("Relay menerima permintaan.")


def read_last_candle():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            return file.read().strip()
    except FileNotFoundError:
        return ""


def save_last_candle(candle_timestamp):
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        file.write(str(candle_timestamp))


def main():
    df = fetch_candles()
    df = calculate_indicators(df)

    row = df.iloc[-1]
    candle_id = str(int(row["t"]))

    print("Candle UTC:", pd.to_datetime(
        int(row["t"]), unit="s", utc=True
    ).isoformat())

    signal = determine_signal(row)
    message = build_message(row, signal)

    print(message)

    previous_candle = read_last_candle()

    if previous_candle == candle_id:
        print("Candle ini sudah diproses sebelumnya.")
        return

    if signal in ("BUY", "SELL"):
        send_to_telegram(signal, message)
    else:
        print("Sinyal WAIT — tidak dikirim ke Telegram.")

    # Simpan candle setelah analisis selesai.
    # Jika pengiriman BUY/SELL gagal, exception terjadi sebelum
    # penyimpanan sehingga candle bisa dicoba kembali.
    save_last_candle(candle_id)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise

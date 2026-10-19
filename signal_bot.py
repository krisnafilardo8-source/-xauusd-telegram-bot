import os
import sys
from datetime import datetime, timezone

import requests
import pandas as pd

# ==============================
# KONFIGURASI
# ==============================
CHART_URL = "https://xaus.com/api/v1/chart"
RELAY_URL = "https://krisnafilardo.pythonanywhere.com/tv-webhook"

ATR_MULTIPLIER = 1.5
MAX_CANDLE_AGE_SECONDS = 45 * 60
STATE_FILE = "last_candle.txt"

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()


def get_closed_candles():
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

    payload = response.json()
    points = payload.get("points", [])

    if not points:
        raise RuntimeError("API tidak mengembalikan candle")

    df = pd.DataFrame(points)
    required = {"t", "o", "h", "l", "c"}

    if not required.issubset(df.columns):
        raise RuntimeError("Kolom OHLC tidak lengkap")

    now = datetime.now(timezone.utc).timestamp()

    # Timestamp t adalah waktu pembukaan candle.
    # Hanya gunakan candle yang interval 15 menitnya telah selesai.
    df["t"] = pd.to_numeric(df["t"], errors="coerce")
    df = df.dropna(subset=["t"])
    df = df[df["t"] + 900 <= now].copy()

    for col in ["o", "h", "l", "c"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = (
        df.dropna(subset=["o", "h", "l", "c"])
        .sort_values("t")
        .drop_duplicates("t")
        .reset_index(drop=True)
    )

    if len(df) < 60:
        raise RuntimeError("Candle tertutup kurang dari 60")

    latest_open_time = float(df.iloc[-1]["t"])
    candle_close_time = latest_open_time + 900
    candle_age = now - candle_close_time

    if candle_age < 0:
        raise RuntimeError("Candle terakhir belum selesai")

    if candle_age > MAX_CANDLE_AGE_SECONDS:
        raise RuntimeError(
            f"Candle terakhir terlalu lama: {candle_age:.0f} detik"
        )

    return df


def calculate_indicators(df):
    close = df["c"]
    previous_close = close.shift(1)

    df["EMA9"] = close.ewm(span=9, adjust=False).mean()
    df["EMA21"] = close.ewm(span=21, adjust=False).mean()
    df["EMA50"] = close.ewm(span=50, adjust=False).mean()

    # RSI 14 menggunakan Wilder smoothing
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / 14, adjust=False, min_periods=14
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / 14, adjust=False, min_periods=14
    ).mean()

    rs = avg_gain / avg_loss
    df["RSI14"] = 100 - (100 / (1 + rs))

    df.loc[(avg_loss == 0) & (avg_gain > 0), "RSI14"] = 100
    df.loc[(avg_loss == 0) & (avg_gain == 0), "RSI14"] = 50

    # ATR 14 menggunakan True Range dan Wilder smoothing
    true_range = pd.concat(
        [
            df["h"] - df["l"],
            (df["h"] - previous_close).abs(),
            (df["l"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    df["ATR14"] = true_range.ewm(
        alpha=1 / 14, adjust=False, min_periods=14
    ).mean()

    return df


def read_last_candle():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            return file.read().strip()
    except FileNotFoundError:
        return ""


def save_last_candle(candle_id):
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        file.write(candle_id)


def decide_signal(row):
    if (
        row["EMA9"] > row["EMA21"] > row["EMA50"]
        and row["RSI14"] > 50
        and row["c"] > row["EMA9"]
    ):
        return "BUY"

    if (
        row["EMA9"] < row["EMA21"] < row["EMA50"]
        and row["RSI14"] < 50
        and row["c"] < row["EMA9"]
    ):
        return "SELL"

    return "WAIT"


def send_to_telegram(message):
    if not WEBHOOK_SECRET:
        raise RuntimeError("Secret WEBHOOK_SECRET belum diatur")

    # Asumsi format ini sesuai dengan relay yang sebelumnya diuji.
    response = requests.post(
        RELAY_URL,
        json={
            "secret": WEBHOOK_SECRET,
            "message": message,
        },
        timeout=20,
    )
    response.raise_for_status()
    print("Relay menerima permintaan:", response.status_code)


def main():
    df = get_closed_candles()
    df = calculate_indicators(df)

    row = df.iloc[-1]
    candle_id = str(int(row["t"]))

    print("Candle UTC:", datetime.fromtimestamp(
        row["t"], timezone.utc
    ).isoformat())

    # Hindari mengirim pesan berulang untuk candle yang sama.
    previous_id = read_last_candle()
    if previous_id == candle_id:
        print("Candle ini sudah diproses; tidak mengirim duplikat.")
        return

    values = [
        row["EMA9"], row["EMA21"], row["EMA50"],
        row["RSI14"], row["ATR14"], row["c"],
    ]
    if any(pd.isna(value) for value in values):
        raise RuntimeError("Indikator belum lengkap")

    signal = decide_signal(row)
    entry = float(row["c"])
    atr = float(row["ATR14"])

    if signal == "BUY":
        stop_loss = entry - ATR_MULTIPLIER * atr
    elif signal == "SELL":
        stop_loss = entry + ATR_MULTIPLIER * atr
    else:
        stop_loss = None

    candle_time = datetime.fromtimestamp(
        row["t"], timezone.utc
    ).strftime("%d-%m-%Y %H:%M UTC")

    lines = [
        "📊 XAUUSD SPOT SIGNAL | M15",
        f"Waktu candle: {candle_time}",
        f"Sinyal: {signal}",
        f"Close: {entry:.2f}",
        f"EMA 9: {row['EMA9']:.2f}",
        f"EMA 21: {row['EMA21']:.2f}",
        f"EMA 50: {row['EMA50']:.2f}",
        f"RSI 14: {row['RSI14']:.2f}",
        f"ATR 14: {atr:.2f}",
    ]

    if stop_loss is not None:
        lines.extend([
            f"Entry indikatif: {entry:.2f}",
            f"Stop Loss (1.5 x ATR): {stop_loss:.2f}",
        ])
    else:
        lines.append("Entry/SL: belum ada — tunggu konfirmasi")

    lines.append(
        "Catatan: sinyal indikator, bukan jaminan hasil trading."
    )

    message = "\n".join(lines)

    print(message)
    def send_to_telegram(message):
    if not WEBHOOK_SECRET:
        raise RuntimeError("Secret WEBHOOK_SECRET belum diatur")

    response = requests.post(
        RELAY_URL,
        json={
            "secret": WEBHOOK_SECRET,
            "message": message,
        },
        timeout=20,
    )

    print("Status relay:", response.status_code)
    print("Respons relay:", response.text[:1500])

    response.raise_for_status()
    print("Relay menerima permintaan.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

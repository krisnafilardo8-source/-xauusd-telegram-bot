import requests
import pandas as pd
from datetime import datetime, timezone

URL = "https://xaus.com/api/v1/chart"

def main():
    response = requests.get(
        URL,
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
        raise RuntimeError("Data candle kosong")

    df = pd.DataFrame(points)

    required = {"t", "o", "h", "l", "c"}
    if not required.issubset(df.columns):
        raise RuntimeError("Data OHLC tidak lengkap")

    # Pastikan hanya candle yang sudah selesai digunakan.
    now = datetime.now(timezone.utc).timestamp()
    df = df[df["t"] + 900 <= now].copy()
    df = df.sort_values("t").drop_duplicates("t")

    for col in ["o", "h", "l", "c"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["o", "h", "l", "c"]).reset_index(drop=True)

    if len(df) < 60:
        raise RuntimeError("Candle tertutup kurang dari 60")

    close = df["c"]

    # Exponential Moving Average
    df["EMA9"] = close.ewm(span=9, adjust=False).mean()
    df["EMA21"] = close.ewm(span=21, adjust=False).mean()
    df["EMA50"] = close.ewm(span=50, adjust=False).mean()

    # Relative Strength Index (Wilder smoothing)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1/14, adjust=False, min_periods=14
    ).mean()
    avg_loss = loss.ewm(
        alpha=1/14, adjust=False, min_periods=14
    ).mean()

    rs = avg_gain / avg_loss
    df["RSI14"] = 100 - (100 / (1 + rs))
    df.loc[(avg_loss == 0) & (avg_gain > 0), "RSI14"] = 100
    df.loc[(avg_loss == 0) & (avg_gain == 0), "RSI14"] = 50

    # Average True Range (Wilder smoothing)
    prev_close = close.shift(1)
    true_range = pd.concat([
        df["h"] - df["l"],
        (df["h"] - prev_close).abs(),
        (df["l"] - prev_close).abs(),
    ], axis=1).max(axis=1)

    df["ATR14"] = true_range.ewm(
        alpha=1/14, adjust=False, min_periods=14
    ).mean()

    latest = df.iloc[-1]
    candle_time = datetime.fromtimestamp(
        latest["t"], timezone.utc
    ).isoformat()

    print("Candle tertutup:", len(df))
    print("Waktu candle UTC:", candle_time)
    print("Open:", round(latest["o"], 2))
    print("High:", round(latest["h"], 2))
    print("Low:", round(latest["l"], 2))
    print("Close:", round(latest["c"], 2))
    print("EMA 9:", round(latest["EMA9"], 3))
    print("EMA 21:", round(latest["EMA21"], 3))
    print("EMA 50:", round(latest["EMA50"], 3))
    print("RSI 14:", round(latest["RSI14"], 2))
    print("ATR 14:", round(latest["ATR14"], 3))

    print("\nLULUS: indikator berhasil dihitung.")
    print("Ini pengujian indikator, belum sinyal BUY/SELL.")

if __name__ == "__main__":
    main()

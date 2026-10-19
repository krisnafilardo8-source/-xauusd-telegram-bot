
import os
import sys
import time
import requests
import pandas as pd

# ============================================================
# ARDSNIPER BOT - XAUUSD SUPPORT/RESISTANCE + CANDLESTICK
# Timeframe: M15
# ============================================================

CHART_URL = "https://xaus.com/api/v1/chart"
RELAY_URL = "https://krisnafilardo.pythonanywhere.com/tv-webhook"

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()

STATE_FILE = "last_candle.txt"

TIMEFRAME = "M15"
TIMEFRAME_SECONDS = 15 * 60

CANDLE_RANGE = 30
ATR_PERIOD = 14
ATR_SL_BUFFER = 0.25
RR_RATIO = 2.0

MAX_CANDLE_AGE_SECONDS = 45 * 60
REQUEST_TIMEOUT = 30


def fetch_candles():
    """Mengambil candle XAUUSD dari XAUS."""

    response = requests.get(
        CHART_URL,
        params={
            "symbol": "xau",
            "range": "5d",
            "interval": "15m",
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    payload = response.json()
    points = payload.get("points", [])

    if not points:
        raise RuntimeError("API tidak mengembalikan data candle.")

    df = pd.DataFrame(points)

    required = ["t", "o", "h", "l", "c"]
    missing = [column for column in required if column not in df.columns]

    if missing:
        raise RuntimeError(f"Kolom candle tidak lengkap: {missing}")

    for column in required:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.dropna(subset=required)
    df = df.sort_values("t").drop_duplicates("t")
    df["t"] = df["t"].astype("int64")

    # Menggunakan candle yang sudah benar-benar tertutup.
    now = int(time.time())
    df = df[df["t"] + TIMEFRAME_SECONDS <= now].copy()

    if len(df) < 60:
        raise RuntimeError(
            f"Candle tertutup tidak cukup untuk analisis: {len(df)}"
        )

    candle_age = now - int(df.iloc[-1]["t"])

    if candle_age > MAX_CANDLE_AGE_SECONDS:
        raise RuntimeError(
            f"Data candle terlalu lama: {candle_age} detik."
        )

    return df.reset_index(drop=True)


def calculate_atr(df):
    """Menghitung ATR untuk buffer Stop Loss."""

    previous_close = df["c"].shift(1)

    true_range = pd.concat(
        [
            df["h"] - df["l"],
            (df["h"] - previous_close).abs(),
            (df["l"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return true_range.ewm(
        alpha=1 / ATR_PERIOD,
        adjust=False,
        min_periods=ATR_PERIOD,
    ).mean()


def is_bullish_engulfing(previous, current):
    """Candle bullish menelan body candle bearish sebelumnya."""

    previous_bearish = previous["c"] < previous["o"]
    current_bullish = current["c"] > current["o"]

    return (
        previous_bearish
        and current_bullish
        and current["o"] <= previous["c"]
        and current["c"] >= previous["o"]
    )


def is_bearish_engulfing(previous, current):
    """Candle bearish menelan body candle bullish sebelumnya."""

    previous_bullish = previous["c"] > previous["o"]
    current_bearish = current["c"] < current["o"]

    return (
        previous_bullish
        and current_bearish
        and current["o"] >= previous["c"]
        and current["c"] <= previous["o"]
    )


def is_bullish_pinbar(candle):
    candle_range = candle["h"] - candle["l"]

    if candle_range <= 0:
        return False

    body = abs(candle["c"] - candle["o"])
    lower_wick = min(candle["o"], candle["c"]) - candle["l"]
    upper_wick = candle["h"] - max(candle["o"], candle["c"])

    return (
        lower_wick >= body * 2
        and lower_wick >= candle_range * 0.45
        and upper_wick <= candle_range * 0.30
        and candle["c"] > candle["l"] + candle_range * 0.55
    )


def is_bearish_pinbar(candle):
    candle_range = candle["h"] - candle["l"]

    if candle_range <= 0:
        return False

    body = abs(candle["c"] - candle["o"])
    upper_wick = candle["h"] - max(candle["o"], candle["c"])
    lower_wick = min(candle["o"], candle["c"]) - candle["l"]

    return (
        upper_wick >= body * 2
        and upper_wick >= candle_range * 0.45
        and lower_wick <= candle_range * 0.30
        and candle["c"] < candle["l"] + candle_range * 0.45
    )


def determine_signal(df):
    """
    Support/resistance sederhana dari 30 candle sebelumnya.
    Candle sinyal tidak dimasukkan dalam perhitungan level.
    """

    current = df.iloc[-1]
    previous = df.iloc[-2]

    atr = current["atr"]

    if pd.isna(atr) or atr <= 0:
        return None

    history = df.iloc[-(CANDLE_RANGE + 1):-1]

    support = float(history["l"].min())
    resistance = float(history["h"].max())

    # Level dianggap dekat jika berada dalam 0.35 ATR.
    proximity = atr * 0.35

    near_support = (
        current["l"] <= support + proximity
        and current["c"] >= support
    )

    near_resistance = (
        current["h"] >= resistance - proximity
        and current["c"] <= resistance
    )

    bullish_pattern = (
        is_bullish_engulfing(previous, current)
        or is_bullish_pinbar(current)
    )

    bearish_pattern = (
        is_bearish_engulfing(previous, current)
        or is_bearish_pinbar(current)
    )

    if near_support and bullish_pattern:
        if is_bullish_engulfing(previous, current):
            pattern = "Bullish engulfing"
        else:
            pattern = "Bullish pin bar"

        entry = float(current["c"])
        sl = support - (atr * ATR_SL_BUFFER)
        risk = entry - sl

        if risk <= 0:
            return None

        tp = entry + (risk * RR_RATIO)

        return {
            "action": "BUY",
            "price": float(current["c"]),
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "support": support,
            "resistance": resistance,
            "reason": (
                f"Pantulan support + {pattern}; "
                f"risiko:imbalan 1:{RR_RATIO:.0f}"
            ),
        }

    if near_resistance and bearish_pattern:
        if is_bearish_engulfing(previous, current):
            pattern = "Bearish engulfing"
        else:
            pattern = "Bearish pin bar"

        entry = float(current["c"])
        sl = resistance + (atr * ATR_SL_BUFFER)
        risk = sl - entry

        if risk <= 0:
            return None

        tp = entry - (risk * RR_RATIO)

        return {
            "action": "SELL",
            "price": float(current["c"]),
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "support": support,
            "resistance": resistance,
            "reason": (
                f"Penolakan resistance + {pattern}; "
                f"risiko:imbalan 1:{RR_RATIO:.0f}"
            ),
        }

    return None


def send_signal(signal, candle_timestamp):
    """Mengirim field yang dibutuhkan app.py."""

    if not WEBHOOK_SECRET:
        raise RuntimeError(
            "WEBHOOK_SECRET belum tersedia di environment."
        )

    chart_time = pd.to_datetime(
        candle_timestamp,
        unit="s",
        utc=True,
    ).strftime("%Y-%m-%d %H:%M UTC")

    payload = {
        "secret": WEBHOOK_SECRET,
        "action": signal["action"],
        "symbol": "XAUUSD",
        "timeframe": TIMEFRAME,
        "price": round(signal["price"], 2),
        "entry": round(signal["entry"], 2),
        "sl": round(signal["sl"], 2),
        "tp": round(signal["tp"], 2),
        "reason": signal["reason"],
        "time": chart_time,
    }

    response = requests.post(
        RELAY_URL,
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )

    print("Status relay:", response.status_code)
    print("Respons relay:", response.text[:500])

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError("Relay menolak sinyal.")

    print("Sinyal berhasil diterima relay.")


def read_last_candle():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            return file.read().strip()
    except FileNotFoundError:
        return ""


def save_last_candle(timestamp):
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        file.write(str(timestamp))


def main():
    df = fetch_candles()
    df["atr"] = calculate_atr(df)

    current = df.iloc[-1]
    candle_id = str(int(current["t"]))

    print(
        "Candle terakhir UTC:",
        pd.to_datetime(
            int(current["t"]), unit="s", utc=True
        ).isoformat(),
    )
    print("Close:", round(float(current["c"]), 2))
    print("ATR:", round(float(current["atr"]), 2))

    previous_candle = read_last_candle()

    if previous_candle == candle_id:
        print("Candle ini sudah diproses.")
        return

    signal = determine_signal(df)

    if signal is None:
        print("Tidak ada konfirmasi support/resistance + candlestick.")
        save_last_candle(candle_id)
        return

    print("Sinyal:", signal["action"])
    print("Entry:", round(signal["entry"], 2))
    print("SL:", round(signal["sl"], 2))
    print("TP:", round(signal["tp"], 2))
    print("Alasan:", signal["reason"])

    # Simpan candle hanya setelah relay menerima sinyal.
    send_signal(signal, int(current["t"]))
    save_last_candle(candle_id)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise

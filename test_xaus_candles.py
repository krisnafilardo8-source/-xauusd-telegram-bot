import requests
from datetime import datetime, timezone

URL = "https://xaus.com/api/v1/chart"

def main():
    params = {
        "symbol": "xau",
        "range": "5d",
        "interval": "15m",
    }

    response = requests.get(URL, params=params, timeout=30)
    print("HTTP status:", response.status_code)
    response.raise_for_status()

    data = response.json()

    print("Kunci respons:", list(data.keys()))
    print("Simbol:", data.get("symbol"))
    print("Interval:", data.get("interval"))

    candles = data.get("points", [])
    print("Jumlah candle:", len(candles))

    if not candles:
        print("BELUM LULUS: data candle kosong.")
        print(str(data)[:2000])
        return

    print("Contoh candle terbaru:")
    for candle in candles[-3:]:
        timestamp = candle.get("t")
        if timestamp is not None:
            candle["waktu_utc"] = datetime.fromtimestamp(
                timestamp, timezone.utc
            ).isoformat()
        print(candle)

    required = {"t", "o", "h", "l", "c"}
    valid = all(required.issubset(c.keys()) for c in candles[-3:])

    if valid:
        print("LULUS: struktur candle memiliki waktu, O, H, L, C.")
    else:
        print("PERLU DICEK: format candle berbeda dari yang diharapkan.")

if __name__ == "__main__":
    main()

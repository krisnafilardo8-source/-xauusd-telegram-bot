import requests
from datetime import datetime, timezone

url = "https://xaus.com/api/v1/chart"
params = {
    "symbol": "xau",
    "range": "5d",
    "interval": "15m",
}

response = requests.get(url, params=params, timeout=30)
print("HTTP status:", response.status_code)
response.raise_for_status()

data = response.json()
points = data.get("points", [])

if not points:
    raise RuntimeError("Data candle kosong")

now = datetime.now(timezone.utc).timestamp()
interval = 15 * 60

# Candle dianggap selesai hanya jika seluruh intervalnya telah berlalu.
closed = [
    p for p in points
    if isinstance(p.get("t"), (int, float))
    and p["t"] + interval <= now
]

if len(closed) < 60:
    raise RuntimeError("Candle tertutup tidak cukup untuk indikator")

closed.sort(key=lambda p: p["t"])

print("Total candle:", len(points))
print("Candle tertutup:", len(closed))

print("\nTiga candle tertutup terbaru:")
for p in closed[-3:]:
    print({
        "waktu_utc": datetime.fromtimestamp(
            p["t"], timezone.utc
        ).isoformat(),
        "open": p.get("o"),
        "high": p.get("h"),
        "low": p.get("l"),
        "close": p.get("c"),
        "volume": p.get("v"),
    })

print("\nLULUS: candle tertutup tersedia untuk pengujian indikator.")

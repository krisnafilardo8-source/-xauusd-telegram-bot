
import os
from datetime import datetime, timezone

import requests

API_URL = "https://api.metalcharts.org/v1/prices"


def main():
    api_key = os.environ.get("METALCHARTS_API_KEY", "").strip()

    if not api_key:
        raise RuntimeError("Secret METALCHARTS_API_KEY belum diatur")

    response = requests.get(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=20,
    )

    print("HTTP status:", response.status_code)
    response.raise_for_status()

    payload = response.json()

    if not payload.get("success"):
        raise RuntimeError("API tidak menyatakan permintaan berhasil")

    gold = payload.get("data", {}).get("XAU")

    if not gold:
        raise RuntimeError("Data XAU tidak ditemukan")

    timestamp = gold.get("timestamp") or gold.get("asOf")

    if not timestamp:
        raise RuntimeError("Timestamp harga tidak tersedia")

    observed = datetime.fromisoformat(
        timestamp.replace("Z", "+00:00")
    )

    if observed.tzinfo is None:
        raise RuntimeError("Timestamp tidak memiliki zona waktu")

    age_seconds = (
        datetime.now(timezone.utc) - observed.astimezone(timezone.utc)
    ).total_seconds()

    print("Instrumen:", gold.get("symbol"))
    print("Jenis pasar:", gold.get("marketType") or gold.get("exchange"))
    print("Harga spot USD/oz:", gold.get("price"))
    print("Bid indikatif:", gold.get("bid"))
    print("Ask indikatif:", gold.get("ask"))
    print("Timestamp UTC:", timestamp)
    print("Usia data (detik):", round(age_seconds, 1))
    print("Flag stale:", gold.get("stale"))
    print("Sisa kuota per menit:", response.headers.get("X-RateLimit-Remaining"))
    print("Sisa kuota bulanan:", response.headers.get("X-RateLimit-Month-Remaining"))

    if age_seconds < -60:
        raise RuntimeError("Timestamp berada terlalu jauh di masa depan")

    if age_seconds > 600:
        raise RuntimeError("Data lebih tua dari 10 menit; jangan digunakan")

    if gold.get("stale") is True:
        raise RuntimeError("API menandai harga sebagai stale")

    print("LULUS: harga spot cukup segar untuk pengujian awal.")
    print("Catatan: ini belum membuktikan data OHLC M15/H1 tersedia.")


if __name__ == "__main__":
    main()

import requests
from datetime import datetime, timezone

URL = "https://xaus.com/api/v1/intraday"

def main():
    response = requests.get(
        URL,
        params={"symbol": "xau", "hours": 6},
        timeout=30,
    )

    print("HTTP status:", response.status_code)
    response.raise_for_status()

    data = response.json()
    print("Tipe respons:", type(data).__name__)
    print("Kunci respons:", list(data.keys()) if isinstance(data, dict) else "bukan objek")

    # Tampilkan struktur data tanpa mencetak informasi sensitif.
    print("Contoh respons:")
    print(str(data)[:5000])

    print("Waktu tes UTC:", datetime.now(timezone.utc).isoformat())

if __name__ == "__main__":
    main()

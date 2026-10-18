# XAUUSD Telegram Alert Bot — Starter

Starter ini menghubungkan TradingView alert -> endpoint Python -> Telegram. Ia **tidak** membuka posisi trading.

## Logika sinyal awal
- Dijalankan pada chart XAUUSD M15.
- Support/resistance menggunakan pivot terakhir.
- BUY: bullish engulfing dekat support + filter arah H1 (harga H1 di atas EMA H1).
- SELL: bearish engulfing dekat resistance + filter arah H1 (harga H1 di bawah EMA H1).
- SL memakai ekstrem candle + buffer ATR; TP memakai target risk/reward.
- Alert hanya saat candle M15 ditutup.

Ini adalah aturan contoh untuk diuji, bukan strategi yang terbukti menguntungkan. Pivot baru diketahui setelah beberapa candle, jadi level support/resistance dapat tertinggal.

## 1. Buat bot Telegram
1. Buka Telegram dan cari `@BotFather`.
2. Jalankan `/newbot`, ikuti petunjuk, lalu simpan token secara rahasia.
3. Buka chat bot baru tersebut dan tekan Start.
4. Dapatkan chat ID melalui layanan `getUpdates` setelah mengirim pesan ke bot, atau gunakan bot pencari chat ID yang tepercaya. Jangan kirim token ke orang lain.

## 2. Jalankan server Python lokal
Disarankan Python 3.10+.

```bash
python -m venv .venv
# Windows:
.venv\\Scripts\\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
```

Salin `.env.example` menjadi `.env`, kemudian isi token Telegram, chat ID, dan secret acak panjang yang sama-sama kamu tentukan.

```bash
python app.py
```

Tes lokal:
```bash
curl http://127.0.0.1:8000/health
```

Server lokal belum bisa menerima webhook dari TradingView di internet. Untuk integrasi live, deploy ke VPS/hosting yang punya domain HTTPS, lalu jalankan dengan WSGI server seperti Gunicorn di belakang reverse proxy HTTPS. TradingView menerima webhook pada port 80/443 dan membatalkan request yang memakan waktu terlalu lama.

## 3. Pasang indikator di TradingView
1. Buka chart simbol XAUUSD dari penyedia data yang kamu gunakan.
2. Pilih timeframe 15 menit.
3. Buka Pine Editor, tempel `tradingview_xauusd_sr.pine`, lalu Save dan Add to chart.
4. Di pengaturan indikator, ubah `Webhook secret` agar sama dengan `WEBHOOK_SECRET` di `.env`.
5. Buat alert dengan Condition indikator ini -> `Any alert() function call`.
6. Aktifkan Webhook URL dan isi `https://DOMAIN-KAMU/tv-webhook`.
7. Simpan alert. Pastikan akun TradingView kamu mendukung webhook alerts dan 2FA aktif.

Jangan masukkan token Telegram ke Pine Script atau URL webhook. Secret bersama adalah perlindungan dasar; untuk produksi, tambahkan pembatasan akses, logging, rate limiting, dan verifikasi sumber webhook.

## 4. Tes end-to-end
Setelah server HTTPS aktif, kirim POST uji (ganti URL dan secret):

```bash
curl -X POST https://DOMAIN-KAMU/tv-webhook \
  -H "Content-Type: application/json" \
  -d '{"secret":"SECRET_SAMA","action":"BUY","symbol":"XAUUSD","timeframe":"15","price":"2500.00","entry":"2500.00","sl":"2495.00","tp":"2510.00","reason":"Tes integrasi","time":"test"}'
```

Respons seharusnya `{"ok":true,"received":true}` dan pesan muncul di Telegram. Jika tidak, cek log server, token/chat ID, dan `Webhook status` di Alert Log TradingView.

## Batasan penting
- Nama simbol berbeda antar penyedia (mis. `XAUUSD`, `OANDA:XAUUSD`, atau simbol broker); pilih chart yang sesuai.
- Alert hanya berjalan ketika alert TradingView aktif dan data tersedia. Webhook dapat gagal sesekali; pantau log.
- `price` adalah harga chart TradingView, yang bisa berbeda dari harga broker akibat spread/feed.
- Strategi perlu backtest/forward-test di akun demo; jangan menganggap sinyal pasti benar.
- Untuk versi berikutnya, tambahkan deteksi zona S/R yang lebih robust, filter berita, spread broker, deduplikasi alert, database dan statistik hasil sinyal.

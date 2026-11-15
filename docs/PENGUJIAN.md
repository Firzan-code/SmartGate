# Pengujian software tanpa perangkat

## Apa yang diuji?

- Geometri EAR, aturan waktu kedipan, cache basi dan pelepasan resource.
- Parser paket ADC, pembentukan window, validasi model/fitur dan status error.
- API Flask dan tampilan dashboard dengan data uji.
- Serializer C++ produksi → parser Python → RF asli pada **sinyal buatan dan UDP loopback**.
- Firmware dengan fake HAL: task pemilik ADC, kegagalan startup/recovery, reconnect, antrean dan hasil basi.

Tes tidak membuka webcam, mikrofon atau COM, tidak upload dan tidak reset board. Ada tes inferensi model pada frame kosong; itu bukan bukti kedipan manusia. Ada tes jaringan loopback; itu bukan bukti radio Wi-Fi ESP atau MAX9814 fisik.

## Persiapan tes

Selesaikan setup pada [README](../README.md). Untuk tes kontrak C++ dan firmware diperlukan **uv** serta compiler Zig. Ikuti [instalasi uv](https://docs.astral.sh/uv/getting-started/installation/), atau pasang uv pada lingkungan proyek:

```bat
.venv\Scripts\python.exe -m pip install uv
set "PATH=%CD%\.venv\Scripts;%PATH%"
uv --version
```

Tes menyediakan compiler terpisah melalui `uv run --with ziglang==0.14.1`, bukan memasang toolchain global. Unduhan pertama memerlukan Internet. Gunakan interpreter `.venv` yang sama untuk semua perintah.

## Tes Python

Dari root repo pada cmd Windows:

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m unittest discover -s smart_gate_full/tests -v
```

Suite kedua mencakup kontrak C++ sehingga `uv` harus dapat ditemukan pada PATH. Tes untuk kamera menggunakan mock/frame kosong, bukan kamera fisik.

### Tes browser opsional

```bat
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m unittest discover -s smart_gate_full/tests -p test_dashboard_ui.py -v
.venv\Scripts\python.exe -m unittest discover -s smart_gate_full/tests -p test_dashboard_integration.py -v
```

Tes browser saat ini mengarah ke Google Chrome pada lokasi standar Windows. Tanpa Playwright, tes browser ditandai **skip**, bukan lulus. Tanpa Chrome di lokasi itu, perbaiki environment/lokasi executable sebelum mengklaim tes browser berjalan. Tes non-browser tetap terpisah.

## Simulasi firmware

```bat
.venv\Scripts\python.exe scripts\test_firmware_host.py
```

Log ditulis ke `reports/firmware_host/` (diabaikan Git). Compiler memuat **`.ino` produksi yang sama**, tetapi dengan stub ADC, Wi-Fi dan FreeRTOS; tidak memakai hardware.

Runner mengambil daftar kasus dari program C++ lalu menjalankan matriks kegagalan:
- Startup ADC: indeks 1–7.
- Recovery: indeks 1–3.
- Setup jaringan: indeks 1–8.

Indeks 8 pada startup ADC **bukan** tahap startup ADC; jangan menambahkannya karena menargetkan API berikutnya, yaitu Wi-Fi. Snapshot perbaikan yang diaudit memiliki 74 eksekusi HAL dan 9 kasus protokol. Hitung dari manifest/hasil aktual jika suite berubah.

## Kompilasi Arduino

Buka sketch integrasi pada Arduino IDE, lalu klik **Verify** dengan board ESP32S3 Dev Module/core 3.3.11. Konfigurasi kosong tetap bisa dikompilasi, tetapi sengaja tidak memulai ADC/jaringan saat dijalankan.

Tiga konfigurasi yang lulus saat pengembangan: USB native default, native terkonfigurasi dummy, serta UART terkonfigurasi dummy. Settings USB harus cocok dengan konektor yang dipakai. Keberhasilan Verify tidak membuktikan board terhubung atau firmware terbaru sudah terpasang.

## Hasil yang boleh dilaporkan

Pisahkan:
1. **Lulus tes logika/simulasi.**
2. **Model asli dapat melakukan inferensi pada fixture.**
3. **Dashboard/HTTP terbaca browser.**
4. **Firmware berhasil dikompilasi.**
5. **Perangkat fisik dan manusia benar-benar diuji.**

Hasil 1–4 tidak otomatis membuat nomor 5 lulus. Bukti fisik setelah fix terbaru masih perlu diambil melalui [checklist uji](UJI_FISIK.md). Hasil pemeriksaan paket publik dicatat pada [Verifikasi repo](VERIFIKASI_REPO.md).

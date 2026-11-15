# Verifikasi paket repo

Pemeriksaan ini dilakukan dari checkout `SmartGate` dengan lingkungan Python 3.11 baru, bukan hanya menjalankan kode dari folder pengembangan lama. Ini catatan software, **bukan hasil uji fisik ESP/MAX9814**.

## Hasil eksekusi saat menyiapkan repo

| Pemeriksaan | Hasil |
|---|---|
| Instalasi dependensi pada `.venv` baru | Berhasil; perintah `python -m pip install -r requirements.txt` juga selesai dengan exit 0. |
| Unduh model wajah dari URL Google | Berhasil, ukuran dan SHA256 sesuai model yang diharapkan. |
| Tes vision, CLI kamera, lifecycle, downloader dan portabilitas repo | **44 tes, OK**; tidak membuka webcam fisik. |
| Tes backend, API, browser, audio/UDP loopback, kontrak C++ dan layout | **42 tes, OK**; tidak ada skip pada eksekusi ini. |
| Simulasi firmware dengan task/ADC/Wi-Fi palsu | **74 eksekusi HAL dan 9 kasus protokol lulus**. |
| Bantuan CLI `run_dashboard.py` dan `run_camera.py` | Berhasil tanpa membuka perangkat. |
| Firmware publik | SHA256 cocok dengan snapshot perbaikan ADC yang sudah diaudit; tiga nilai konfigurasi publik kosong. |

Tes browser menggunakan Chrome lokal dan Playwright 1.58.0. Pada penutupan salah satu fixture browser, Playwright mencetak callback `asyncio.exceptions.CancelledError`, tetapi semua assertion selesai `OK` dan proses exit 0. Catatan ini tidak disembunyikan dan tidak dipakai sebagai bukti kegagalan/keberhasilan perangkat. Jalur API/HTTP dan browser benar-benar dijalankan, bukan hasil gambar dashboard buatan.

## Kecocokan sumber firmware

SHA256 `.ino` publik:

```text
e97310d86eabc6a8e226d112b3c3b1907e0f82528c806c10911dcade5e5faa44
```

Firmware ini tetap satu `.ino`. Snapshot dengan konfigurasi kosong dipakai untuk publikasi, bukan sketch kerja pengguna yang memuat SSID/password/IP lokal. Kompilasi tiga konfigurasi Arduino sudah dibuktikan dalam audit pengembangan sebelumnya; persiapan repo ini mengulang simulasi host dan kontrak, **tidak mengklaim tiga build Arduino baru dijalankan ulang**.

## Yang sengaja tidak masuk Git

- Konfigurasi Wi-Fi/IP laptop pengguna dan backup sketch yang masih berisi konfigurasi.
- Folder/aset proyek lama yang tidak dibutuhkan demo, termasuk `Asli/`.
- Gambar wajah, video, audio mentah, dataset pribadi dan hasil uji manusia.
- Cache, virtual environment, binary hasil compiler, ZIP, log serta audit internal mesin pengembang.
- Model wajah Google: diambil melalui downloader dengan checksum, bukan disimpan di repo.

Kode Python, firmware, artifact RF/scaler, metrik sintetis, dependensi, tes dan dokumentasi yang diperlukan untuk demo disertakan. `.gitignore` membantu mencegah file sementara terunggah, tetapi **bukan penyaring password pada file `.ino` yang sudah dilacak**.

## Batas penerimaan

Belum ada bukti fisik setelah fix terbaru bahwa ESP stabil, rate ADC terukur 16 kHz, suara MAX9814 kontinu, hasil Serial/dashboard cocok pada perangkat, atau model akurat pada sirene nyata. Checklist itu ada pada [Uji fisik](UJI_FISIK.md), dan status proyek dijelaskan pada [Progres dosen](PROGRES_DOSEN.md).

Cara mengulang tes: [Pengujian software](PENGUJIAN.md).

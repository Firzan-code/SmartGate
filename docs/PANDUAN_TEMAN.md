# Panduan teman: memahami dan menjalankan SmartGate

## 1. Gambaran paling sederhana

Anggap proyek ini punya **dua pengamat**, belum penggerak gerbang:
1. Webcam melihat wajah dan bukaan mata.
2. MAX9814 mendengar suara; ESP mengirim angka suaranya ke laptop.

Laptop mengolah dua input itu dan memperlihatkan hasil di web. ESP tidak menjalankan model ML; tugasnya mengambil suara, mengirim paket, dan menampilkan ringkasan dari laptop di Serial Monitor.

**Jangan tertukar:**
- Wajah terdeteksi ≠ identitas orang sudah dikenal.
- Kedipan terpenuhi ≠ izin masuk.
- Tegangan mikrofon berubah ≠ sirene terdeteksi.
- Kompilasi berhasil ≠ board fisik pasti stabil.
- Demo ini ≠ gerbang otomatis sudah jadi.

## 2. Urutan baca kode

| Urutan | Berkas | Apa yang dipahami |
|---|---|---|
| 1 | [`../run_dashboard.py`](../run_dashboard.py) | Menghidupkan server, runtime dan kamera; menghentikannya saat Ctrl+C. |
| 2 | [`../smart_gate_full/backend/runtime.py`](../smart_gate_full/backend/runtime.py) | Mengatur worker UDP/audio, status bersama dan ringkasan untuk ESP. |
| 3 | [`../smart_gate_full/backend/protocol.py`](../smart_gate_full/backend/protocol.py) | Memeriksa bentuk dan isi paket audio. |
| 4 | [`../smart_gate_full/backend/stream.py`](../smart_gate_full/backend/stream.py) | Menyatukan paket menjadi jendela suara satu detik. |
| 5 | [`../smart_gate_full/backend/audio_model.py`](../smart_gate_full/backend/audio_model.py) | Memuat RF yang sudah dilatih, mengambil fitur dan memprediksi sirene. |
| 6 | [`../ml_engine/train_siren_model.py`](../ml_engine/train_siren_model.py) | Bagaimana 30 fitur dan model Random Forest dibuat. |
| 7 | [`../ml_engine/vision_ear.py`](../ml_engine/vision_ear.py) dan [`eye_blink.py`](../ml_engine/eye_blink.py) | Landmark wajah, EAR, dan urutan buka–tutup–buka mata. |
| 8 | [`../smart_gate_full/backend/app.py`](../smart_gate_full/backend/app.py) | API status, halaman dashboard, dan video lokal. |
| 9 | [`../smart_gate_full/backend/static_dashboard.html`](../smart_gate_full/backend/static_dashboard.html) | Tampilan browser; membaca API, bukan melakukan inferensi ML. |
| 10 | [`Firmware ESP32-S3`](../smart_gate_full/firmware/tes_dua_model_esp32s3/tes_dua_model_esp32s3.ino) | ADC DMA, antrean paket, Wi-Fi dan ringkasan Serial. |

Tidak harus membaca seluruh kode sekaligus. Pahami alur di [arsitektur](ARSITEKTUR.md), lalu pilih bagian yang ingin dikerjakan.

## 3. Setup pertama di laptop teman

Buka Command Prompt pada Windows dan ikuti [README](../README.md#1-ambil-repo-dan-siapkan-python). Ringkasnya:

```bat
git clone https://github.com/Firzan-code/SmartGate.git
cd SmartGate
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe scripts\download_models.py
.venv\Scripts\python.exe run_dashboard.py
```

Jika repo sudah pernah diambil, gunakan `git pull` dari folder repo, bukan clone lagi ke folder yang sama. Jangan menimpa perubahan teman; periksa `git status` lebih dahulu.

Buka http://127.0.0.1:5000. Awalnya audio MENUNGGU sampai ESP mengirim paket. Untuk kamera lain gunakan `--camera 1`, atau diagnosis driver dengan `--backend msmf`. Untuk tanpa webcam gunakan `--no-camera`.

## 4. Menyiapkan ESP

1. Wiring hanya ESP32-S3 + MAX9814: VDD → 3V3, GND → GND, OUT → GPIO1. Cabut daya saat mengubah kabel.
2. Salin folder `tes_dua_model_esp32s3` ke **luar repo**. Isi SSID/password dan IP laptop hanya di salinan itu.
3. Laptop dan ESP harus berada pada LAN yang saling terhubung. ESP memerlukan Wi-Fi 2,4 GHz.
4. Jalankan Python, baca kandidat `SERVER_IP`, lalu cocokkan dengan `ipconfig`. Jangan memakai alamat dashboard sebagai IP firmware.
5. Pilih board/USB/port yang benar di Arduino IDE dan upload manual. Buka Serial Monitor 115200.
6. Amati dulu apakah board berhenti restart; setelah itu periksa paket pada dashboard.

Rincian dan titik berhenti ketika gagal: [uji fisik](UJI_FISIK.md).

## 5. Cara membaca dashboard

| Label | Artinya |
|---|---|
| MENUNGGU | Belum ada data yang bisa dinilai. Bukan prediksi negatif. |
| BUFFERING | Data suara sedang dikumpulkan menjadi satu detik utuh. |
| LIVE / aktif | Ada hasil baru yang masih segar menurut runtime. Ini bukan jaminan hasil benar. |
| BASI / stale | Hasil sudah kedaluwarsa; jangan digunakan sebagai hasil baru. |
| ERROR | Ada kegagalan nyata yang perlu dibaca dari pesan/terminal. |
| Probabilitas sirene | Nilai dari Random Forest, bukan persentase kepastian dunia nyata. |
| P2P ADC | Selisih sampel terbesar dan terkecil; bukan satuan dB. |
| Kedipan terpenuhi | Aturan dua kedipan terpenuhi, bukan identitas atau izin membuka gerbang. |

## 6. Jika bermasalah

| Gejala | Periksa dulu |
|---|---|
| `ModuleNotFoundError` | Jalankan dari `.venv\Scripts\python.exe`; pasang `requirements.txt` di interpreter yang sama. |
| Model wajah tidak ditemukan | Jalankan `scripts\download_models.py` dari root repo. |
| Model RF hilang | Ambil kembali file model dari repo yang dipercaya; dashboard tidak otomatis training ulang. |
| Kamera tidak tampil | Tutup aplikasi lain yang memakai webcam, cek izin Windows, indeks kamera dan backend. |
| Paket audio selalu nol | Firmware yang terpasang, SSID/IP laptop, UDP5006, izin jaringan privat dan client isolation hotspot. |
| Serial kosong | Port yang benar, 115200, jenis konektor USB dan CDC. Port setelah upload dapat berubah. |
| `xTaskPriorityDisinherit` / reboot berulang | Pastikan membuka firmware perbaikan terbaru, bukan buffer IDE lama. Simpan log crash lengkap dan hentikan penilaian ML dulu. |
| Suara masuk tetapi salah klasifikasi | Bedakan transport sehat dari kualitas model. Model sintetis masih perlu data mikrofon nyata; jangan langsung menurunkan threshold. |

## 7. Bekerja bersama lewat Git

```bat
git status
git pull
git switch -c docs/perjelas-panduan
REM Edit hanya file yang menjadi tugasmu
git add docs/PANDUAN_TEMAN.md
git diff --cached
git commit -m "docs: perjelas panduan teman"
git push -u origin docs/perjelas-panduan
```

Buat pull request di GitHub agar perubahan dapat dibaca teman. Contoh nama branch di atas hanya contoh, bukan pembagian orang yang sudah disepakati.

**Sebelum commit:** jangan pakai `git add .` tanpa memeriksa isinya, jangan masukkan password/IP lokal, model dari sumber asing, foto/video wajah atau rekaman suara orang tanpa izin. File `.ino` yang sudah dilacak tetap bisa mengandung password meskipun ada `.gitignore`.

## 8. Pembagian kerja yang disarankan

Belum menetapkan nama orang. Tim bisa membagi berdasarkan bagian:
- **Vision:** kalibrasi EAR dan uji kedipan pada berbagai kondisi.
- **Audio:** dataset MAX9814 nyata dan evaluasi sirene/non-sirene.
- **Firmware/jaringan:** kestabilan sampling, Wi-Fi dan recovery.
- **Integrasi/dokumentasi:** kesesuaian dashboard–Serial, catatan bukti dan presentasi.

Sepakati kontrak data sebelum mengubah rate, ukuran paket atau nama status; perubahan sepihak dapat memutus jalur ESP–Python.

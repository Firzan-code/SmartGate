# SmartGate — demo dua model untuk tugas IoT

## Integrasi sirene dan servo (demo meja)

Firmware utama `tes_dua_model_esp32s3.ino` sekarang menggabungkan MAX9814 dan SG90 GPIO42.
Jalankan `.venv\Scripts\python.exe run_dashboard.py --enable-servo` setelah wiring dan catu diperiksa.
Default launcher tetap observasi. Servo boot tanpa PWM; hasil audio valid HOLD menargetkan 90°.
Sirene dua klip berturut-turut, confidence kelas minimal 0,80, dan ADC tidak clipping
memicu target 110°. ESP membatasi bukaan 5 detik, kemudian target 90° dan cooldown 10 detik.
Sirene terus-menerus tidak memperpanjang bukaan; diperlukan hasil HOLD setelah bukaan untuk pemicu berikutnya.
Data basi menutup bukaan dan membatalkan pemicu. Hilang balasan selama 3 detik juga menutup di ESP.
Mode DISABLED melepas PWM; ini tidak memutus catu servo atau menjamin posisi mekanik.
Boot ID dan nomor paket mencegah perintah lama/duplikat; protokol ini belum memakai autentikasi kriptografis.
Dashboard menampilkan status target dari ESP; tidak ada sensor posisi atau penghalang.
Gunakan tanpa horn/palang untuk demo. Uraian servo terpisah di bawah adalah mode lama.

Status uji perangkat 16 November 2026: audio MAX9814, inferensi AST, kamera dan
telemetri ESP berhasil berjalan bersama. Pengguna melaporkan servo berputar terus
saat target tetap CLOSED/90°. Tipe servo dan catu belum terverifikasi; gerak fisik
buka–tutup belum dinyatakan berhasil. Mode otomatis dinonaktifkan dan firmware
DISABLED melepas PWM. Pastikan tipe positional serta catu sebelum uji gerak berikutnya.

SmartGate sedang dikembangkan menjadi prototipe gerbang pintar. **Demo utama mengamati kamera dan suara; sekarang tersedia juga demo meja SG90 terpisah: wajah + kedua mata terbuka terus 5 detik memicu satu gerakan.** Ini bukan pengenal identitas atau sistem gerbang aman.

## Baru: demo servo SG90 sederhana

Lihat **[panduan cepat servo](docs/DEMO_SERVO_CEPAT.md)**. Firmware servo terpisah dari firmware audio; menguploadnya mengganti aplikasi yang berjalan pada ESP, bukan menghapus kode lama. **Tes software, dua kompilasi, serta review statis pada lingkup yang diperiksa lulus. Uji meja fisik dilakukan pengguna setelah pemeriksaan catu/wiring; mulai dari simulasi dahulu.**

```bat
.venv\Scripts\python.exe run_servo_demo.py
```

Perintah di atas menjalankan **simulasi kamera tanpa perintah servo**, dashboard **http://127.0.0.1:5001**. Mode fisik memakai flag eksplisit `--enable-servo --esp-ip <IPv4-ESP>` setelah wiring/catu diperiksa. Gunakan SG90 tanpa horn/palang, SIGNAL GPIO42, catu eksternal sesuai rating dan common GND. ARM menargetkan 90°, syarat 5 detik menargetkan 110° sekali; tidak ada tutup otomatis. Ikuti panduan dahulu, jangan langsung menghubungkan palang.

Bagian berikut menjelaskan **demo utama kamera + audio**, bukan demo servo terpisah.

Ada dua jalur pengolahan:
- **Kamera laptop:** MediaPipe mendeteksi titik wajah. Rumus EAR membaca bukaan mata, lalu aturan waktu menghitung kedipan.
- **Mikrofon MAX9814 + ESP32-S3:** ESP mengambil sampel suara dan mengirimnya lewat Wi-Fi. **Model sirene berjalan di Python pada laptop**, bukan di ESP.

Hasil keduanya tampil di dashboard dan dikirim kembali ke ESP untuk dicetak di Arduino Serial Monitor. Python **tidak memakai port COM**, jadi Serial Monitor boleh tetap terbuka.

> **Penting untuk presentasi:** kedipan bukan pengenal identitas. Runtime sirene memakai artefak AST ONNX lokal, tetapi kelulusan tes software belum membuktikan akurasi suara nyata atau kestabilan board setelah perbaikan terbaru.

## Protokol komunikasi: MQTT atau HTTP?

**ESP32-S3 ↔ laptop memakai UDP melalui Wi-Fi. Browser ↔ server Python memakai HTTP. MQTT tidak digunakan pada implementasi saat ini.**

| Jalur | Protokol dan port default | Data |
|---|---|---|
| ESP32-S3 → laptop, demo audio | UDP → laptop `5006`; port ESP `5007` | Sampel audio biner `SGA1` |
| Laptop → ESP32-S3, demo audio | UDP → ESP `5007` | Ringkasan hasil teks `SGR1` untuk Serial Monitor |
| Laptop ↔ ESP32-S3, demo servo terpisah | UDP; ESP `5009`, laptop `5010` | ARM/OPEN/DISARM/KEEPALIVE, beacon dan ACK |
| Browser ↔ Python, dashboard utama | HTTP/TCP `127.0.0.1:5000` | Halaman, status JSON dan video |
| Browser ↔ Python, dashboard servo | HTTP/TCP `127.0.0.1:5001` | Halaman, status JSON dan video |

Wi-Fi adalah media jaringan, bukan pengganti nama protokol. ESP tidak mengirim audio atau perintah servo melalui HTTP; HTTP hanya melayani dashboard lokal. Tidak ada broker, topic atau publish/subscribe MQTT. Detail alur, format paket dan batasnya: **[Protokol komunikasi](docs/PROTOKOL_KOMUNIKASI.md)**.

## Baca yang mana dulu?

| Kebutuhan | Dokumen |
|---|---|
| Ringkasan untuk bertemu dosen | [Progres dan bahan penjelasan](docs/PROGRES_DOSEN.md) |
| Teman baru mulai memahami proyek | [Panduan teman](docs/PANDUAN_TEMAN.md) |
| Memahami alur kode dan komunikasi | [Arsitektur](docs/ARSITEKTUR.md) dan [protokol UDP/HTTP](docs/PROTOKOL_KOMUNIKASI.md) |
| Melakukan demo pada perangkat | [Urutan uji fisik](docs/UJI_FISIK.md) |
| Memahami model dan arti metriknya | [Model dan data](docs/MODEL_DAN_DATA.md) |
| Menjalankan tes tanpa perangkat | [Pengujian software](docs/PENGUJIAN.md) |

## Alur singkat

```text
Webcam laptop --> MediaPipe --> EAR/kedipan --------+
                                                   |
MAX9814 --> ESP32-S3 ADC --> Wi-Fi --> model sirene --+--> Dashboard laptop
                                                   |
                                                   +--> Wi-Fi --> ESP --> Serial Monitor
```

**EAR** adalah rasio bukaan kelopak terhadap lebar mata. **ADC** mengubah tegangan suara menjadi angka. Model **Audio Spectrogram Transformer (AST)** membaca representasi log-mel dari klip audio 3 detik.

## Progres saat ini

| Bagian | Kondisi |
|---|---|
| Vision wajah, EAR, status mata dan hitung kedipan | Kode tersedia; tes logika dan uji webcam awal telah dilakukan. Validasi dua kedipan pada berbagai orang/kondisi belum selesai. |
| Model sirene AST ONNX (`siren_ast_v2`) | Runtime dan kontrak softmax tiga kelas tersedia; akurasi pada suara MAX9814 nyata belum tervalidasi. |
| Dashboard Python/Flask | Sudah dibuat, termasuk status menunggu, buffering, aktif, basi dan error. |
| ESP32-S3: ADC DMA + kirim suara Wi-Fi | Firmware tersedia dalam **satu `.ino`**; kompilasi dan simulasi software lolos. |
| Masalah ESP restart | Penyebab ADC lintas task sudah diperbaiki dan diuji software. **Uji ulang pada board fisik masih diperlukan.** |
| Pengenal identitas, servo, sensor jarak, LCD, MQTT | **Belum terintegrasi** pada demo ini. Jangan dianggap fitur yang sudah berjalan. |

Detail bukti dan langkah berikutnya: [Progres dosen](docs/PROGRES_DOSEN.md).

## Peralatan dan software

- Laptop Windows, webcam, Python **3.11**, Git, browser.
- ESP32-S3, MAX9814, kabel USB data dan tiga kabel jumper.
- Arduino IDE 2.x; board package **esp32 by Espressif Systems 3.3.11** adalah versi yang dipakai saat kompilasi pengembangan.
- Wi-Fi/hotspot **2,4 GHz** yang bisa diakses ESP. Laptop dan ESP harus bisa saling menjangkau pada LAN yang sama.
- Untuk demo ini **tidak perlu** servo, HC-SR04 atau LCD.

## 1. Ambil repo dan siapkan Python

Contoh berikut dijalankan dari **Command Prompt (cmd) Windows**, bukan dari shell Python `>>>`.

```bat
git clone https://github.com/Firzan-code/SmartGate.git
cd SmartGate
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe scripts\download_models.py
```

Model sirene AST `siren_ast_v2` (sekitar 171 MB) ada di repo pada `ml_engine/models/siren_ast_v2`. File `siren_ast_fp16.onnx` disimpan lewat Git LFS karena melebihi batas 100 MB per file GitHub; Git for Windows sudah membawa Git LFS, jadi jalankan `git lfs install` sekali sebelum clone atau pull agar file aslinya ikut terunduh. Skrip `download_models.py` memeriksa ukuran serta SHA256 setiap file, mengunduh model wajah MediaPipe dari Google, dan mengambil file AST yang belum ada dari [Release GitHub proyek](https://github.com/Firzan-code/SmartGate/releases/tag/model-siren-ast-v2-20261122). Untuk memakai folder model AST lain, arahkan variabel lingkungan `SMARTGATE_AST_MODEL_DIR` ke folder tersebut. Tidak perlu training ulang untuk menjalankan demo. Unduhan model dan instalasi pertama memerlukan Internet; kamera tidak dikirim ke Google.

Jika `py -3.11` tidak ditemukan, pasang Python 3.11 terlebih dahulu. Gunakan `python -m pip` dari interpreter yang sama, jangan `pip` yang mungkin milik Python lain.

## 2. Jalankan dashboard laptop

```bat
.venv\Scripts\python.exe run_dashboard.py
```

Atau klik dua kali **`JALANKAN_DUA_MODEL.cmd`** setelah `.venv` siap.

Buka **http://127.0.0.1:5000** dan biarkan terminal tetap terbuka. Ctrl+C menghentikan server dan melepas webcam.

- Kamera laptop akan aktif ketika perintah ini dijalankan.
- Jika ESP belum mengirim suara, audio **MENUNGGU** dan paket nol adalah wajar.
- Untuk diagnosis tanpa webcam: `.venv\Scripts\python.exe run_dashboard.py --no-camera`.
- Untuk menguji kamera saja: `.venv\Scripts\python.exe run_camera.py --backend dshow`.
- Jika webcam bukan indeks 0, coba `--camera 1`.

## 3. Sambungkan MAX9814 ke ESP32-S3

**Cabut USB sebelum memasang/mengubah kabel.**

| MAX9814 | ESP32-S3 |
|---|---|
| VDD / VCC | 3V3 |
| GND | GND |
| OUT | **GPIO1 / ADC1_CH0**, bukan GPIO44/RX |

GPIO1 adalah **label pin**, bukan urutan kaki nomor satu. Tidak perlu mengubah wiring untuk perbaikan restart ADC ini.

## 4. Isi konfigurasi dan upload ESP

File publik sengaja memiliki konfigurasi kosong. Supaya password tidak masuk Git, **salin folder** berikut ke luar repo sebelum mengisinya:

```text
smart_gate_full/firmware/tes_dua_model_esp32s3/
```

Nama folder salinan tetap `tes_dua_model_esp32s3` dan di dalamnya cukup satu file `.ino` dengan nama sama. Buka salinan itu di Arduino IDE, lalu isi tiga nilai di bagian paling atas:

```cpp
#define WIFI_SSID "NAMA_WIFI_KAMU"
#define WIFI_PASSWORD "PASSWORD_WIFI_KAMU"
#define SERVER_IP "192.168.1.10"  // contoh, GANTI dengan IPv4 laptop
```

`SERVER_IP` bukan `127.0.0.1`, bukan IP ESP, bukan alamat dashboard, dan tidak memakai `http://` atau `:5000`. Terminal Python menampilkan kandidat IP laptop; cocokkan dengan IPv4 adapter Wi-Fi pada `ipconfig`. IP bisa berubah saat pindah jaringan.

Di Arduino IDE:
1. Board **ESP32S3 Dev Module**.
2. Untuk konektor **USB native**: USB CDC On Boot **Enabled**, USB Mode **Hardware CDC and JTAG**. Jika memakai konektor USB-to-UART, CDC mengikuti jalur UART (Disabled).
3. Pilih port ESP yang terdeteksi, lalu **Verify → Upload**. Port bisa berubah setelah upload.
4. Buka Serial Monitor **115200 baud**. Tidak perlu mengetik perintah.
5. Amati setidaknya 30 detik: tidak boleh ada panic/`Backtrace`/`Rebooting...` berulang. Lalu cek paket audio dashboard bertambah.

Python menerima audio pada **UDP 5006**, ESP memakai **UDP 5007**. Jika Windows meminta izin Python, izinkan untuk jaringan privat tepercaya; **jangan mematikan firewall keseluruhan**. Hotspot dengan isolasi klien dapat menghalangi komunikasi.

Panduan diagnosis dan uji lengkap: [Uji fisik](docs/UJI_FISIK.md).

## Struktur kode yang penting

```text
SmartGate/
├── run_dashboard.py                 # Titik masuk demo gabungan
├── run_camera.py                    # Uji vision saja
├── JALANKAN_DUA_MODEL.cmd            # Shortcut Windows, memakai .venv
├── requirements.txt                 # Dependensi demo
├── scripts/
│   ├── download_models.py           # Unduh model wajah + AST, cek checksum
│   └── test_firmware_host.py        # Simulasi firmware tanpa ESP
├── ml_engine/
│   ├── vision_ear.py                # MediaPipe dan overlay
│   ├── eye_blink.py                 # Aturan waktu kedipan
│   ├── train_siren_model.py         # Ekstraksi fitur dan training RF
│   ├── audio_siren.py               # Modul eksperimen lama, bukan jalur dashboard
│   └── models/
│       ├── siren_rf_model.pkl       # Model sirene + scaler
│       └── training_metrics.json    # Metrik data sintetis
├── smart_gate_full/
│   ├── backend/                    # UDP, buffer audio, model, API dan HTML
│   ├── firmware/
│   │   ├── tes_dua_model_esp32s3/    # Firmware integrasi yang dipakai demo
│   │   └── tes_max9814_esp32s3/      # Opsional: cek ADC saja, TANPA ML/Wi-Fi
│   └── tests/                      # Tes backend, UI, protokol dan firmware
├── tests/                          # Tes vision dan downloader
└── docs/                           # Panduan dan progres
```

## Keamanan, privasi dan batas demo

- Tidak ada rekaman foto/video/audio otomatis. `--report` pada launcher hanya menyimpan status/metrik bila diminta.
- Dashboard HTTP hanya di laptop (`127.0.0.1`). UDP LAN **belum memakai autentikasi/enkripsi**; gunakan jaringan privat, jangan port-forward ke Internet.
- `authorized` tetap **false**. Demo utama kamera+audio tidak mengirim perintah gerak; demo SG90 terpisah hanya mengirim perintah bila flag hardware diaktifkan eksplisit.
- File `.pkl` memakai deserialisasi joblib: **hanya muat model dari sumber proyek yang dipercaya**, jangan model acak.
- `.gitignore` tidak dapat menghapus password dari `.ino` yang sudah dilacak Git. Karena itu, isi konfigurasi **di salinan luar repo**, bukan pada file publik.
- Gambar/video pribadi, data mikrofon mentah, konfigurasi lokal, cache, binary dan log internal tidak disertakan.

## Pengujian

Tes software tidak membutuhkan ESP, webcam atau mikrofon fisik. Beberapa tes memakai model asli pada frame kosong atau sinyal buatan/UDP loopback. Lihat [cara menjalankan dan arti hasil tes](docs/PENGUJIAN.md).

**Urutan kerja berikutnya:** uji kestabilan ESP setelah fix → buktikan paket audio masuk terus → bandingkan Serial/dashboard → evaluasi sirene nyata → baru rencanakan integrasi gerbang dan safety.

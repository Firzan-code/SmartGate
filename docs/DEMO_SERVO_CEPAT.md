# Demo cepat SG90: kedua mata terbuka 5 detik

**Implementasi demo terpisah dari audio. Status uji terbaru ada di bagian verifikasi bawah.**

## Komunikasi yang digunakan

**Demo servo memakai UDP melalui Wi-Fi antara ESP32-S3 dan laptop, bukan MQTT atau HTTP untuk perintah gerak.** Port ESP `5009`, port laptop `5010`. Browser mengakses dashboard Python melalui **HTTP/TCP `127.0.0.1:5001`**. Mode simulasi tidak membuka UDP kontrol. Audio tetap pada aplikasi terpisah. Penjelasan lengkap: [Protokol komunikasi](PROTOKOL_KOMUNIKASI.md).

## Perilaku

- Kamera laptop memakai model MediaPipe/EAR yang sudah ada, tidak perlu training baru.
- Wajah terlihat dan **kedua mata TERBUKA 5 detik pada rangkaian frame valid** -> satu event buka. Ini bukti pengamatan kamera, bukan jaminan tidak ada kedipan yang terlewat di antara frame.
- Berkedip, satu mata tertutup/transisi, wajah hilang, frame basi, atau perpindahan wajah besar -> hitungan mulai lagi.
- Bukan pengenal identitas atau izin masuk. Foto/video dengan mata terbuka bisa memicu demo.
- Pada mode perangkat: launcher terlebih dahulu mengirim **ARM**, yang menempatkan servo ke target awal **90°**. Setelah syarat 5 detik, OPEN menargetkan **110° sekali**, bukan tutup/buka berulang.
- **Tidak ada tutup otomatis.** Target90/110 adalah rentang uji kecil, belum sudut palang terkalibrasi dan bukan posisi yang diukur sensor.
- **Lepas horn/palang** untuk tes awal. Jangan dipakai sebagai gerbang bertenaga untuk manusia/kendaraan.

## Pilihan perangkat

Pakai **Micro Servo SG90 positional** untuk demo ini. HS225BB tidak diperlukan. Jika unit SG90 ternyata versi modifikasi continuous-rotation, jangan menjalankan kode sudut ini.

### Wiring — cabut semua daya sebelum memasang

| Fungsi servo | Tujuan |
|---|---|
| SIGNAL, biasanya oranye/kuning | **GPIO42 ESP32-S3**, bukan urutan kaki42 |
| Positif, biasanya merah | Catu eksternal teregulasi sesuai label servo; kandidat nominal5V untuk SG90 yang mendukungnya |
| GND, biasanya cokelat/hitam | Negatif catu eksternal **dan GND ESP32** |

ESP32 tetap dari USB laptop. **Jangan sambungkan positif catu servo ke 5V/VIN/3V3 ESP32 yang sedang ditenagai USB. Jangan memberi daya motor servo dari GPIO/3V3.** Pastikan tegangan/polaritas catu benar terlebih dahulu. GND bersama wajib untuk referensi PWM; warna kabel bukan pengganti pemeriksaan label/pinout. GPIO42 tidak boleh sekaligus dipakai JTAG eksternal.

MAX9814 tidak dibutuhkan untuk tes ini; LCD/HC-SR04 belum dipakai. Tidak ada interlock anti-jepit pada demo meja ini.

## 1. Simulasi kamera tanpa servo

Dari folder repo SmartGate pada Command Prompt Windows:

```bat
.venv\Scripts\python.exe run_servo_demo.py
```

Atau klik `JALANKAN_SERVO.cmd`. Buka **http://127.0.0.1:5001**. Kamera aktif lokal tanpa rekaman. Tampilkan wajah dan buka kedua mata; hitungan mencapai5s -> `SIMULASI: EVENT BUKA SEKALI`. **Mode ini tidak membuka UDP kontrol atau mengirim perintah ke ESP.** Ctrl+C untuk berhenti.

Jika `.venv` belum siap, ikuti instalasi Python/model di [README](../README.md). Pakai `--camera 1` bila kamera bukan indeks0; backend default `dshow` di Windows.

## 2. Firmware khusus servo — upload oleh pengguna

**Penting: ini aplikasi ESP pengganti sementara, bukan firmware audio+servo.** Upload sketch servo ke board yang sama akan mengganti aplikasi audio di board. File audio lama tetap utuh di repo dan bisa diupload ulang nanti.

1. Salin folder `smart_gate_full/firmware/demo_servo_esp32s3/` ke **luar repo**. Nama folder dan `.ino` tetap `demo_servo_esp32s3`.
2. Buka `demo_servo_esp32s3.ino` salinan di Arduino IDE.
3. Isi tiga konfigurasi paling atas pada salinan: `WIFI_SSID`, `WIFI_PASSWORD`, `SERVER_IP`.
4. `SERVER_IP` adalah **IPv4 laptop di Wi-Fi/hotspot yang sama**, lihat `ipconfig`. Bukan IP ESP, bukan `127.0.0.1`, bukan URL atau port. Jangan kirim password ke chat/GitHub.
5. Board **ESP32S3 Dev Module**, package **esp32 by Espressif Systems3.3.11**. Untuk USB native: **USB CDC On Boot Enabled**, **Hardware CDC and JTAG**.
6. Klik Verify -> Upload sendiri, lalu Serial Monitor **115200**. Board tidak menghasilkan PWM saat boot; tunggu Wi-Fi dan catat IP ESP yang tampil.
7. Bila konfigurasi kosong, firmware tidak menjalankan koneksi/gerakan. Jangan bingung dengan sketch `.ino` audio yang berbeda.

Pastikan laptop/ESP pada LAN2.4GHz yang saling menjangkau. Kontrol: ESP UDP5009, laptop UDP5010. Jika Windows meminta izin Python, izinkan hanya jaringan privat; jangan mematikan firewall keseluruhan. Serial Monitor boleh tetap terbuka: Python tidak membuka COM.

## 3. Aktifkan gerak fisik secara eksplisit

Pastikan catu sesuai rating, common GND dan **horn/palang dilepas**. Mengaktifkan command berikut dapat menggerakkan servo ke target awal90° segera setelah beacon ESP diterima, sebelum menunggu wajah:

```bat
.venv\Scripts\python.exe run_servo_demo.py --enable-servo --esp-ip IP_ESP_DARI_SERIAL
```

Ganti `IP_ESP_DARI_SERIAL` dengan IPv4 ESP yang sebenarnya, misalnya format `192.168.x.x`; jangan salin placeholder sebagai nilai. Buka **http://127.0.0.1:5001**.

1. Tunggu status **ARMED / TARGET90**. Selama belum ARMED, hitungan belum berjalan.
2. Tampilkan satu wajah, kedua mata terbuka selama5detik. Kedipan sekecil apa pun mereset.
3. OPEN terkirim satu kali -> target110°. Dashboard membedakan **terkirim**, **dikonfirmasi ESP**, dan **posisi fisik belum diukur**.
4. Jika OPEN hilang di jaringan, tidak ada retry gerak otomatis. Hentikan dan lakukan sesi ulang yang aman.
5. Setelah membuka, servo tetap pada target selama command/keepalive masih valid; wajah hilang tidak menutup servo.
6. Ctrl+C meminta DISARM. Jika laptop terputus >2detik, firmware melepas PWM dan mengunci sesi DISARMED sampai reboot. **PWM dilepas bukan jaminan mekanik tertahan/berhenti dan bukan pemutusan daya.** Jangan memasang beban/palang yang bisa jatuh.

Untuk tes ulang: hentikan Python, amankan mekanik tanpa beban, reboot ESP secara manual, lalu jalankan ulang command. Tidak ada tombol web yang menutup otomatis.

## Kalau belum bergerak

- Mode dashboard harus `DEMO HARDWARE AKTIF`, bukan simulasi.
- IP tujuan firmware = IP laptop; `--esp-ip` = IP ESP. Dua nilai ini berbeda.
- ESP harus IDLE pada sesi baru. Jika DISARMED/ERROR/OPENED dari sesi lama, reboot manual setelah mengamankan mekanik.
- Periksa izin UDP privat5009/5010, hotspot isolation, GND, kabelSIGNAL GPIO42, rating dan tegangan catu.
- Jika hitungan selalu nol, lihat label kedua mata. EAR ambang default belum tentu sesuai pencahayaan/kacamata/jarak pengguna. Jangan memaksa mata/menatap sampai tidak nyaman; tes boleh diulang.
- Jika ada brownout/restart, hentikan dan periksa catu/wiring; jangan menambah tegangan melebihi rating atau mengambil suplai servo dari ESP.

## Verifikasi dan batas

Hasil eksekusi lokal:

| Pemeriksaan | Hasil |
|---|---|
| Suite Python `tests/` | **65 tes lulus**, termasuk 21 tes servo; kamera palsu, HTTP/Chrome nyata, tampilan seluler dan disconnect |
| Regresi backend lama | **42 tes lulus**; masih ada pesan `CancelledError` saat teardown Playwright lama |
| Sketch produksi melalui fake HAL + protokol/kontrak | **18 kasus lulus**, termasuk ARM/OPEN satu kali, penolakan paket, timeout, reboot, PWM gagal dan pertukaran C++–Python melalui UDP loopback |
| Arduino ESP32-S3 core3.3.11 | **2 kompilasi lulus**: konfigurasi publik kosong dan dummy aktif, USB native CDC; ada peringatan deprecated `NetworkUDP::flush()` (bukan error) |
| Kode/model lama | Tetap utuh; satu berkas metrik mempunyai perbedaan newline checkout yang telah ada, bukan perubahan data |
| Review statis | Firmware dan koreksi batas waktu kamera lulus inspeksi pada lingkup yang diperiksa, tanpa temuan penghambat tersisa. Hash sumber/bukti eksekusi dicocokkan oleh implementer; reviewer tidak menjalankan tes/build atau memverifikasi hash secara independen. |

Jalankan ulang tes firmware tanpa perangkat:

```bat
.venv\Scripts\python.exe scripts\test_servo_firmware.py
```

**Upload, pengukuran catu, uji webcam manusia, dan gerak SG90 fisik belum dilakukan oleh agent.** Model/pipeline audio lama tidak diubah. Protokol khusus memiliki boot/nonce/batas waktu dan deduplikasi gerak, tetapi **bukan autentikasi/enkripsi**; gunakan LAN privat tepercaya. Pekerjaan software dan review terbatas selesai; lanjutkan **uji meja oleh pengguna** sesuai urutan di atas hanya setelah label servo, rating catu, polaritas dan wiring diperiksa. Ini bukan sertifikasi keamanan, bukti posisi fisik, atau audit eksekusi independen.

Sumber: [launcher](../run_servo_demo.py), [aturan5detik](../smart_gate_full/backend/servo_demo.py), [transport](../smart_gate_full/backend/servo_link.py), [firmware](../smart_gate_full/firmware/demo_servo_esp32s3/demo_servo_esp32s3.ino), [rencana](RENCANA_DEMO_SERVO.md).

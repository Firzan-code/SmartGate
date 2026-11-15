# Protokol komunikasi SmartGate

## Jawaban singkat: bukan MQTT

**Komunikasi ESP32-S3 dengan laptop menggunakan UDP melalui Wi-Fi. Dashboard browser menggunakan HTTP ke server Python lokal. MQTT belum digunakan.**

Jadi jawabannya bukan memilih satu protokol untuk seluruh sistem: tiap jalur mempunyai tugas berbeda. Wi-Fi menyediakan koneksi jaringan; UDP membawa data ESP–laptop; HTTP melayani halaman/API/video untuk browser.

## Pembagian jalur dan port default

| Arah | Protokol | Port tujuan/default | Isi |
|---|---|---|---|
| ESP → laptop, demo audio | UDP/IPv4 melalui Wi-Fi | Laptop `5006`, dari ESP `5007` | Sampel ADC suara biner `SGA1` |
| Laptop → ESP, demo audio | UDP/IPv4 melalui Wi-Fi | ESP `5007`, dari laptop `5006` | Teks ringkasan hasil `SGR1` untuk Serial Monitor |
| Laptop → ESP, demo servo terpisah | UDP/IPv4 melalui Wi-Fi | ESP `5009`, dari laptop `5010` | Perintah `SGC1`: ARM, OPEN, DISARM, KEEPALIVE |
| ESP → laptop, demo servo terpisah | UDP/IPv4 melalui Wi-Fi | Laptop `5010`, dari ESP `5009` | Beacon `SGH1` dan konfirmasi/ACK `SGK1` |
| Browser ↔ Python, demo utama | HTTP di atas TCP | `http://127.0.0.1:5000` | Halaman, status JSON, video |
| Browser ↔ Python, demo servo | HTTP di atas TCP | `http://127.0.0.1:5001` | Halaman, status JSON, video |

Port pada tabel adalah default kode. `127.0.0.1` berarti browser pada laptop yang menjalankan Python, bukan alamat ESP. Pada firmware, `SERVER_IP` harus IPv4 LAN laptop; `--esp-ip` pada launcher servo justru IPv4 ESP. Tidak perlu menambahkan `http://` atau port ke nilai IPv4 tersebut.

## Alur demo utama: kamera + audio

```text
MAX9814 → ADC ESP32-S3
            │
            └── UDP/Wi-Fi, SGA1 → laptop:5006 → fitur suara → Random Forest
                                                     │
Kamera laptop → MediaPipe → EAR/kedipan ───────────────┤
                                                     ├── HTTP:5000 → browser
                                                     └── UDP/Wi-Fi, SGR1 → ESP:5007 → Serial
```

Model sirene dan vision berjalan di laptop, bukan di browser/ESP. USB dipakai pengguna untuk upload dan Serial Monitor; Python tidak mengambil alih port COM.

- **`SGA1`:** paket biner little-endian, header `<4sIIIHH>` berukuran 20 byte + 320 sampel uint16 (640 byte), total **660 byte**. Header membawa magic, boot ID, sequence, sample rate, sample count dan flags.
- **`SGR1`:** ringkasan teks ASCII, bukan paket kontrol servo. Kontrak ini belum membawa boot/sequence/timestamp untuk membuktikan generasi paket tertunda secara menyeluruh.
- Parser dan buffer mendeteksi sejumlah paket invalid, gap dan restart. Hilangnya kontinuitas mereset window; tidak ada pengiriman ulang audio otomatis untuk mengganti sampel hilang.

## Alur demo servo: aplikasi terpisah

```text
Kamera laptop → MediaPipe/EAR → syarat kedua mata terbuka 5 detik
                                   │
                                   ├── HTTP:5001 → browser (monitoring)
                                   └── ServoController → ServoLink
                                                          │ UDP/Wi-Fi
                                                          v
                                                     ESP:5009 → PWM GPIO42 → SG90
                                                          │
                                          laptop:5010 ← beacon/ACK
```

Paket servo biner **16 byte**, little-endian `<4sIII>`: magic 4 byte, boot ID uint32, nonce uint32, dan action atau state uint32.

| Magic | Arah | Fungsi |
|---|---|---|
| `SGH1` | ESP → laptop | Beacon: sesi, nonce dan state terkini |
| `SGC1` | Laptop → ESP | Perintah: `1` ARM, `2` OPEN, `3` DISARM, `4` KEEPALIVE |
| `SGK1` | ESP → laptop | Konfirmasi state/target, **bukan pengukuran posisi fisik** |

Saat boot PWM tidak aktif. Mode perangkat mengirim ARM untuk target 90°; setelah syarat kamera terpenuhi, satu OPEN menargetkan 110°. OPEN tidak di-retry otomatis dan tidak ada tutup otomatis. Paket duplikat yang diterima tidak mengulang penulisan target yang sudah diterapkan. Timeout/disconnect melepas PWM, **bukan memutus daya atau menjamin mekanik tertahan**.

Mode default `run_servo_demo.py` hanya simulasi kamera: HTTP aktif tetapi **tidak membuat link UDP kontrol dan tidak mengirim perintah servo**. Mode perangkat memerlukan flag eksplisit. Firmware servo dan audio belum digabung; upload sketch servo ke board yang sama mengganti aplikasi audio yang terpasang sementara. Ikuti [panduan SG90](DEMO_SERVO_CEPAT.md) sebelum menyalakan mode perangkat.

## Mengapa UDP? Mengapa ada HTTP?

- UDP memungkinkan pengiriman blok audio dan paket kontrol kecil langsung di LAN tanpa broker. Aplikasi tetap harus menangani paket hilang, duplikat, terlambat dan timeout; **UDP tidak menjamin paket sampai atau urut**.
- HTTP sesuai untuk browser mengambil halaman, status JSON dan video dari Flask. Video memakai MJPEG/multipart melalui HTTP, bukan MQTT. Endpoint monitoring tidak memerintahkan gerakan.
- MQTT memerlukan pola broker/topic/publish/subscribe. Komponen tersebut **tidak dipakai** pada jalur demo yang dijelaskan di sini. Menambahkan MQTT nanti merupakan perubahan arsitektur, bukan sekadar mengganti istilah di laporan.

## Batas keamanan dan pengujian

UDP LAN belum mempunyai autentikasi kriptografis atau enkripsi. Boot ID, nonce, pemeriksaan sumber, deduplikasi dan watchdog membatasi beberapa kesalahan/stale packet, **bukan identitas pengirim atau sistem gerbang aman**. Pakai LAN privat tepercaya, jangan port-forward ke Internet. HTTP dibatasi ke loopback laptop, bukan layanan HTTPS publik.

Tes parser, fake HAL dan C++–Python UDP loopback telah dijalankan; kompilasi berhasil. Itu bukan bukti radio Wi-Fi ESP, akurasi model suara nyata, catu servo atau gerakan SG90 fisik sudah tervalidasi. Status dan angka pengujian ada pada [progres dosen](PROGRES_DOSEN.md) dan [panduan servo](DEMO_SERVO_CEPAT.md).

## Rujukan kode

- Audio: [runtime UDP](../smart_gate_full/backend/runtime.py), [parser](../smart_gate_full/backend/protocol.py), [firmware audio](../smart_gate_full/firmware/tes_dua_model_esp32s3/tes_dua_model_esp32s3.ino).
- Servo: [ServoLink](../smart_gate_full/backend/servo_link.py), [controller](../smart_gate_full/backend/servo_demo.py), [firmware SG90](../smart_gate_full/firmware/demo_servo_esp32s3/demo_servo_esp32s3.ino).
- HTTP: [launcher utama](../run_dashboard.py), [API utama](../smart_gate_full/backend/app.py), [launcher/API servo](../run_servo_demo.py).

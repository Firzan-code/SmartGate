# Arsitektur dan alur kode

**Komunikasi saat ini: UDP melalui Wi-Fi untuk ESP–laptop, HTTP untuk browser–Python; bukan MQTT.** Lihat [tabel port dan kontrak komunikasi](PROTOKOL_KOMUNIKASI.md). Bagian audio di bawah tetap terpisah dari demo servo.

## Pembagian tugas perangkat

| Komponen | Tugas |
|---|---|
| MAX9814 | Menghasilkan tegangan analog dari suara, dengan bias DC dan AGC. |
| ESP32-S3 | Mengambil ADC continuous/DMA, membentuk paket dan mengirim Wi-Fi; menerima teks hasil untuk Serial. |
| Webcam | Memberikan frame ke Python pada laptop. |
| Python laptop | MediaPipe/EAR/kedipan, buffer audio, fitur STFT/MFCC, Random Forest, API dan ringkasan hasil. |
| Browser laptop | Menampilkan hasil API dan video; tidak menjalankan model ML. |

```text
MAX9814 OUT GPIO1
      |
      v
Task akuisisi ESP: init -> start -> read -> recovery/stop/cleanup
      |                              (pemilik ADC yang sama)
      v
Antrean audio terbatas -> loop jaringan ESP -> UDP5006 laptop
                                             |
                                             v
                                  decode -> buffer 1 detik
                                             |
                                             v
                               30 fitur -> scaler -> RandomForest
                                             |
Webcam -> MediaPipe -> EAR -> aturan kedipan --+-> state -> Flask -> browser
                                             |
                                             +-> UDP5007 ESP -> Serial115200
```

## Mengapa memakai Wi-Fi, bukan serial Python?

Arduino Serial Monitor dipakai pengguna untuk melihat log. Kalau Python membuka port COM yang sama, keduanya dapat berebut port. Maka audio dan ringkasan lewat UDP LAN; USB hanya untuk upload dan Serial Monitor. Tidak perlu MQTT/broker pada demo ini.

## Kontrak audio ESP → Python (`SGA1`)

- Sample rate yang dikonfigurasi: **16.000 Hz**, mono, ADC 12-bit (0–4095). Pengukuran rate fisik masih perlu dilakukan.
- **320 sampel** per paket, target interval **20 ms**.
- Header 20 byte + 640 byte payload = **660 byte** per paket.
- Header little-endian: `<4sIIIHH` = magic, boot ID, sequence, sample rate, sample count, flags.
- Payload: 320 angka uint16 little-endian.
- Flag bit0 menunjukkan discontinuity. Boot/sequence membantu mendeteksi restart, paket terlambat/duplikat/hilang.

Parser menolak panjang/rate/count/ADC invalid. Buffer satu detik memerlukan 50 paket utuh; inferensi berikutnya memakai hop 25 paket (0,5 detik). Hilangnya kontinuitas mereset window dan hit berturut-turut, bukan memakai audio lama sebagai audio baru.

## Model audio dan waktu respons

Sampel dikurangi mean untuk menangani bias DC, kemudian STFT dan 30 fitur dihitung. Random Forest memprediksi probabilitas sirene. Deteksi memerlukan probabilitas ≥0,80 selama **dua jendela berurutan**.

Karena itu, jangan menyamakan latensi model sekitar beberapa milidetik dengan latensi seluruh sistem. Ada waktu mengumpulkan satu detik audio, hop/debounce, transport dan penjadwalan.

`smart_gate_full/backend/audio_model.py` adalah jalur audio dashboard. `ml_engine/audio_siren.py` dipertahankan sebagai modul eksperimen terdahulu; modul itu dapat menggunakan sumber/fallback berbeda dan **bukan bukti data MAX9814 sedang masuk**. Gunakan `run_dashboard.py` untuk demo integrasi yang tidak mengganti audio hilang dengan data sintetis.

## Vision

MediaPipe menemukan landmark. Enam titik per mata dipakai menghitung:

```text
EAR = (jarak(p2,p6) + jarak(p3,p5)) / (2 × jarak(p1,p4))
```

Ambang awal tutup 0,21 dan buka 0,25 memakai hysteresis. Aturan kedipan memerlukan urutan kedua mata terbuka → tertutup → terbuka, waktu tutup 50–400 ms, dua kedipan dalam 5 detik. Riwayat dibuang ketika wajah hilang/tracking terputus. Ambang perlu dikalibrasi; nilai default bukan kebenaran untuk semua orang.

Properti lama `liveness_verified` di API hanya berarti syarat kedipan terpenuhi. `authorized` tetap false. Tidak ada embedding wajah, enrollment atau basis data identitas.

## Ringkasan Python → ESP (`SGR1`)

Teks ASCII berawalan `SGR1 `, ukuran dibatasi, dikirim maksimal sekitar4 kali/detik. Isi memuat status WAJAH/MATA/EAR/KEDIP/SUARA/probabilitas. ESP memeriksa sumber/prefix/ukuran dan mencetak status basi jika ringkasan berhenti.

**Batas protokol:** ringkasan `SGR1` belum membawa boot/sequence/timestamp. Paket yang lama tertunda di jaringan tidak dapat dibuktikan generasinya secara menyeluruh, walaupun regresi hasil lokal basi saat recovery/reconnect sudah diuji. Ini salah satu alasan demo dibatasi ke LAN tepercaya dan belum dipakai menggerakkan gerbang.

## Demo meja servo terpisah

`run_servo_demo.py` memakai kamera laptop, MediaPipe/EAR dan aturan kedua mata terbuka 5 detik. Mode default hanya simulasi; UDP kontrol baru dibuat jika `--enable-servo --esp-ip <IPv4-ESP>` diberikan. Browser tidak menghitung waktu dan tidak mempunyai endpoint gerak.

Pada mode perangkat, `ServoLink` Python mengirim UDP dari port laptop `5010` ke ESP `5009`. Sketch `demo_servo_esp32s3.ino` mengirim beacon dan ACK dari ESP `5009` ke laptop `5010`. Paket biner 16 byte membawa boot ID, nonce dan action/state. Pemeriksaan paket dan watchdog bukan autentikasi, jaminan pengiriman, atau pembacaan posisi servo.

ARM menargetkan 90°, lalu satu OPEN menargetkan 110° setelah syarat kamera. Tidak ada tutup otomatis atau retry OPEN otomatis. Detail keselamatan dan urutan uji pengguna: [Demo servo cepat](DEMO_SERVO_CEPAT.md).

Sketch servo **menggantikan aplikasi audio yang terpasang** jika diupload ke board yang sama; keduanya belum diintegrasikan. Kode audio tetap tersedia.

## API dan port

| Tujuan | Alamat/port |
|---|---|
| Dashboard HTTP | `127.0.0.1:5000` |
| State JSON | `GET /api/state` |
| Kesehatan proses | `GET /health` |
| Audio UDP laptop | `0.0.0.0:5006` pada LAN |
| Audio/ringkasan UDP ESP | `5007` |
| Dashboard servo HTTP | `127.0.0.1:5001`, GET `/`, `/api/state`, `/video_feed` |
| Kontrol/beacon/ACK servo UDP | ESP `5009`, laptop `5010` (hanya mode perangkat) |

Pabrik aplikasi Flask tidak otomatis menyalakan kamera, model atau jaringan. Launcher yang memulai worker secara eksplisit. Endpoint kontrol gerbang tidak tersedia; `POST /api/command` mengembalikan 404.

## Pemulihan dan data kedaluwarsa

- ADC dibuat, dikonfigurasi, dimulai, dibaca, dihentikan, di-flush dan dipulihkan oleh **satu task akuisisi**. Memakai core yang sama saja tidak cukup untuk aturan mutex driver.
- `setup()` membuat task; jaringan baru aktif setelah ADC siap. Konfigurasi kosong tidak memulai ADC/jaringan.
- Antrean dibatasi dan data tua dibuang agar antrean panjang tidak terlihat sebagai hasil baru.
- Worker inferensi tidak memblokir penerima UDP. Error fatal tidak boleh dihapus oleh prediksi yang terlambat selesai.
- Kamera/read failure dan audio terputus menghapus hasil segar/positif yang tidak lagi valid.

## Privasi dan keamanan

HTTP kamera dibatasi ke loopback. Tidak ada rekaman otomatis. UDP LAN tidak terenkripsi dan tidak terautentikasi. Jangan membuka port Internet; jangan menganggap kontrol freshness sebagai autentikasi. Sistem keselamatan gerbang belum diimplementasikan pada versi ini.

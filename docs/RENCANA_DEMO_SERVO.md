# Rencana demo servo — wajah + kedua mata terbuka 5 detik

**Status: implementasi disetujui pengguna; belum diuji pada perangkat.**

## Penyesuaian untuk demo cepat yang disetujui

Pengguna mempunyai Micro Servo SG90 dan HS225BB; demo awal memilih **SG90 positional**, bukan continuous-rotation. Untuk mengisolasi risiko dan mempercepat pengujian, buat sketch Wi-Fi servo **terpisah satu `.ino`** dan launcher/dashboard khusus. Firmware audio yang sudah ada tidak diubah; flashing sketch servo mengganti aplikasi di board sehingga audio ESP sementara tidak berjalan. Perubahan ini menggantikan rencana integrasi ADC pada tahap pertama, bukan mengklaim audio+servo sudah terintegrasi.

Gunakan gerak meja kecil **90 -> 110 derajat** sebagai target awal tanpa horn/palang; ini bukan sudut palang tertutup/terbuka yang sudah dikalibrasi. Catu eksternal sesuai rating SG90 (kandidat 5 V teregulasi), common GND, positif eksternal tidak masuk rail ESP32. Rating/tegangan catu fisik masih perlu diperiksa pengguna.

Transport khusus: laptop UDP5010, ESP UDP5009. Beacon `SGH1` dan ACK `SGK1`, command `SGC1`, masing-masing 16 byte little-endian `<4sIII>` (boot_id, nonce, state/action). State: 0 IDLE, 1 ARMED, 2 OPENED, 3 ERROR, 4 DISARMED. Action: 1 ARM, 2 OPEN, 3 DISARM, 4 KEEPALIVE. Beacon nonce baru setiap 500 ms, valid maksimum 750 ms, hanya sumber IPv4/port laptop terkonfigurasi. ARM satu kali menempatkan target90; OPEN hanya dari ARMED ke110, duplikat tidak menggerakkan lagi. KEEPALIVE tidak menggerakkan. Hilang command valid >2 detik: PWM dilepas, sesi DISARMED sampai reboot; tidak mengirim tutup otomatis. Melepas PWM bukan jaminan posisi tertahan/berhenti. Nonce/boot/freshness bukan autentikasi; LAN privat saja.

## Tujuan sederhana

Kamera laptop mendeteksi wajah dan bukaan mata. Jika wajah terlihat dan **kedua mata terbuka selama 5 detik berturut-turut**, Python memicu satu aksi buka servo pada ESP32-S3 melalui Wi-Fi.

Ini **demo pemicu gerak**, bukan pengenalan identitas, izin masuk, atau sistem keamanan gerbang. Model suara tidak menjadi syarat buka pada tahap ini. `authorized` tetap false; status demo servo harus ditampilkan terpisah.

## Aturan perilaku yang diusulkan

| Kondisi | Perilaku |
|---|---|
| Tidak ada wajah, kamera error, atau frame basi | Hitungan nol; tidak boleh mengirim aksi buka |
| Wajah ada, hanya satu mata terbuka, mata tertutup, atau status transisi | Hitungan kembali nol |
| Wajah ada dan kedua mata TERBUKA | Mulai/lanjutkan hitungan dari frame baru yang valid |
| Memenuhi 5 detik berturut-turut | Satu event buka, bukan perintah berulang setiap frame |
| Setelah terbuka | Tetap terbuka; tidak menutup otomatis ketika berkedip/wajah hilang |
| Ingin mencoba ulang | Reset/arm demo secara eksplisit setelah posisi awal diperiksa |
| Python/ESP terputus sebelum pemicu | Batalkan hitungan/perintah yang belum berlaku; mulai dari awal setelah koneksi pulih |
| Restart ESP | Jangan menjalankan kembali perintah dari boot sebelumnya |

**Kedipan singkat juga mereset hitungan** pada versi awal ini. Toleransi kedipan, jika nanti diinginkan, merupakan perubahan aturan tersendiri.

Kehilangan wajah setelah membuka **tidak** memicu penutupan otomatis. Penutupan palang nyata belum aman tanpa kalibrasi dan interlock lokal yang diuji; HC-SR04/LCD belum diintegrasikan pada fase ini.

## Alur dan batas perubahan

```text
Webcam laptop
    -> MediaPipe + EAR yang sudah ada
    -> aturan temporal 5 detik (Python)
    -> mode simulasi: event/status dashboard saja
       atau mode perangkat yang diaktifkan eksplisit:
    -> perintah kontrol khusus lewat Wi-Fi
    -> ESP32-S3 -> PWM GPIO42 -> servo uji tanpa horn/palang
```

- Gunakan repo ini untuk pengembangan fitur; jangan menimpa sketch kerja yang berisi konfigurasi lokal atau folder asli pengembangan.
- Pertahankan model MediaPipe, kode kedipan, model sirene, training, dan artefak lama. Aturan 5 detik adalah lapisan baru, bukan perubahan makna `liveness_verified`.
- Mode lama tetap observation-only. Mode demo servo harus opt-in dan jelas terlihat; membuka dashboard saja tidak mengaktifkan aktuator.
- Kamera tetap satu producer. Gunakan timestamp/nomor frame baru, bukan jumlah polling API atau waktu tampilan browser. Membaca ulang frame yang sama tidak boleh melengkapi 5 detik.
- Hitungan memakai jam monoton. Gap tracking, hasil lama, waktu mundur/tidak valid dan perpindahan wajah besar membatalkan kontinuitas. Ini tetap bukan jaminan orangnya sama.
- Sinyal bukaan kedua mata berasal dari label `TERBUKA` per mata; nilai ambang EAR perlu diperiksa pada kondisi nyata pengguna.
- Wi-Fi tetap menjadi jalur kontrol; Python tidak mengambil alih port USB Arduino Serial Monitor. Keberhasilan model sirene bukan syarat mengirim aksi servo.
- Jangan menafsirkan teks ringkasan `SGR1` sebagai perintah gerak. Buat format kontrol khusus yang tervalidasi, terikat boot ESP, memiliki ID/urutan dan batas kesegaran. Duplikat tidak boleh mengulangi gerak; konfirmasi penerimaan dibedakan dari bukti posisi fisik.
- Demo servo tetap satu `.ino` terpisah; firmware audio tidak diubah dan tidak berjalan bersamaan pada board yang sama. Bila integrasi kelak dibuat, ADC harus tetap dimiliki task akuisisinya sendiri; jangan menambah `delay(5000)` atau memblokir audio/jaringan.
- Semua Wi-Fi/password/IP pada file publik tetap kosong. Konfigurasi nyata diisi pada salinan di luar repo.

## Hardware yang harus dipastikan sebelum menyalakan servo

Rancangan wiring yang sudah disepakati memakai **GPIO42** untuk SIGNAL servo ESP32-S3. Ini bukan nomor urut kaki header. GPIO42 tidak boleh sekaligus dipakai JTAG eksternal.

**Pengguna menyebut SG90 dan HS225BB; rancangan memilih SG90 positional.** Label unit/tipe positional serta rating tegangan dan catu fisik tetap perlu diperiksa sebelum dinyalakan. Jangan menganggap servo biru otomatis positional atau memberi perintah sudut pada servo continuous-rotation.

- Gunakan catu eksternal sesuai rating servo; jangan mengambil daya motor dari GPIO/3V3 ESP32.
- ESP32 dari USB; positif catu servo tidak digabung ke 5V/VIN/3V3 ESP32. GND servo, negatif catu dan GND ESP32 disatukan sebagai referensi sinyal.
- Cabut USB dan catu eksternal sebelum rewiring. Periksa polaritas dan tegangan sebelum beban disambungkan.
- Tes pertama tanpa horn/palang dan jauh dari tangan/benda. Jangan memaksa ujung 0/180 derajat; kalibrasikan rentang kecil sesuai tipe servo dahulu.
- Firmware uji tidak memberikan PWM saat boot sampai mode gerak diaktifkan eksplisit. Target sudut adalah perintah, bukan pengukuran posisi. Mematikan PWM bukan memutus daya atau menjamin mekanik berhenti.
- Tidak ada upload/reset, akses COM, webcam atau gerak fisik otomatis oleh agent.

## Tahapan implementasi setelah rencana disetujui

1. Pastikan label servo/catu dan pin aktual; buat tes servo mandiri yang dinonaktifkan saat boot untuk kalibrasi meja.
2. Tambahkan state machine Python dan tes clock/frame sintetis sebelum integrasi: kurang dari 5 detik belum membuka; tepat/melewati 5 detik hanya satu event; semua kondisi invalid mereset.
3. Tambahkan mode simulasi dan indikator dashboard: NONAKTIF, MENUNGGU WAJAH, HITUNGAN, EVENT BUKA, serta status pengiriman/konfirmasi yang terpisah.
4. Tambahkan jalur kontrol Wi-Fi dan PWM nonblocking pada satu `.ino`, setelah tipe/rentang servo jelas. Uji byte protokol Python-C++, penolakan paket, duplikat, reconnect/reboot dan kegagalan PWM melalui fake HAL.
5. Jalankan regresi vision/backend/firmware dan compile ESP32-S3 dengan konfigurasi publik kosong serta dummy aktif. Backup sebelum mengubah file; source model/asli dan kredensial lokal tidak disentuh.
6. Berikan petunjuk upload dan tes fisik kepada pengguna. Pengguna yang mengunggah dan mengamati servo. Catat hasil simulasi, kompilasi dan perangkat sebagai tiga bukti berbeda.
7. Perbarui README/panduan/progres sesuai hasil nyata. Commit/push perubahan fitur hanya dalam lingkup yang kemudian disetujui.

## Penerimaan minimum

- Hitungan tidak bisa bertambah dari snapshot/frame lama atau tanpa kamera.
- Salah satu mata tidak terbuka atau wajah hilang memutus hitungan.
- Waktu aktual frame valid memenuhi 5 detik; bukan hitungan jumlah frame tetap atau `sleep`.
- Satu sesi menghasilkan satu event, tidak spam gerak selama wajah terus terlihat.
- Tidak ada PWM/perintah saat mode demo nonaktif, saat boot belum di-arm, atau dari ringkasan lama.
- Setelah buka tidak ada tutup otomatis; tidak mengklaim servo sudah mencapai posisi tanpa sensor/observasi.
- Audio dan pemilik lifecycle ADC tidak rusak; konfigurasi pribadi tidak masuk Git.

Rujukan kode sekarang: [runtime backend](../smart_gate_full/backend/runtime.py), [adapter kamera](../smart_gate_full/backend/camera.py), [vision/EAR](../ml_engine/vision_ear.py), [firmware integrasi](../smart_gate_full/firmware/tes_dua_model_esp32s3/tes_dua_model_esp32s3.ino).

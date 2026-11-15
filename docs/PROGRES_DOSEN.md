# Progres SmartGate — bahan diskusi dengan dosen

**Posisi saat publikasi awal, 16 November 2026:** prototipe pengamatan dua model. Belum sistem gerbang otomatis dan belum validasi lapangan.

## Tambahan: demo aktuator meja SG90

Fitur baru dibuat **terpisah dari aplikasi audio**: wajah dan kedua mata terbuka terus5detik memicu satu event gerak SG90. Kedipan/wajah hilang mereset hitungan. Mode default hanya simulasi; gerak nyata perlu flag eksplisit, GPIO42, catu eksternal sesuai rating dan commonGND. ARM menargetkan90°, OPEN menargetkan110° sekali; tidak ada tutup otomatis.

Ini **bukan integrasi gerbang lengkap**, bukan identitas/izin masuk, dan belum validasi gerak fisik. Upload sketch servo sementara mengganti aplikasi audio di board; kode audio tetap utuh. Panduan serta bukti uji terbaru: [Demo servo cepat](DEMO_SERVO_CEPAT.md).

Bukti tambahan servo: **65 tes Python** (21 khusus servo), **42 tes backend lama**, **18 kasus fake-HAL/protokol/kontrak**, serta **2 kompilasi Arduino ESP32-S3** lulus. Ada peringatan API UDP deprecated dan pesan teardown Playwright lama; keduanya dicatat di panduan. **Review statis pada lingkup firmware dan koreksi kamera lulus tanpa temuan penghambat tersisa; hash/bukti eksekusi direkonsiliasi implementer, bukan audit eksekusi independen. Belum ada upload atau uji gerak servo fisik oleh agent.** Angka ini bukan hasil uji servo nyata.

Bagian berikut mempertahankan laporan demo utama kamera+audio; status software tidak boleh dianggap uji fisik servo.

## Ringkasan yang bisa disampaikan

> “Kami sudah membuat dua jalur pengolahan. Kamera laptop diproses dengan MediaPipe dan EAR untuk membaca kondisi mata serta kedipan. Suara dari MAX9814 di ESP32-S3 dikirim lewat Wi-Fi ke laptop, lalu diklasifikasikan oleh Random Forest menjadi sirene atau non-sirene. Hasilnya ditampilkan di dashboard dan dikirim balik ke Serial Monitor ESP. Integrasi software dan kompilasi firmware sudah diuji. Sekarang fokus kami memastikan board stabil setelah perbaikan ADC, menguji audio nyata, dan mengevaluasi model sebelum menghubungkan aktuator gerbang.”

## Protokol yang dipakai

> “Komunikasi ESP32-S3 dengan laptop menggunakan UDP melalui Wi-Fi. Dashboard browser menggunakan HTTP pada server Python lokal. Implementasi ini tidak memakai MQTT atau broker.”

Audio masuk ke UDP laptop `5006`, ringkasan kembali ke UDP ESP `5007`. Demo servo terpisah memakai UDP ESP `5009` dan laptop `5010`. HTTP dashboard utama di `5000`, servo di `5001`. Port adalah nilai default aplikasi, bukan hasil pengukuran perangkat. Lihat [detail komunikasi](PROTOKOL_KOMUNIKASI.md).

## Target besar vs hasil sekarang

**Target besar:** sistem gerbang pintar berbasis masukan vision dan suara, dengan kontrol serta pengaman fisik.

**Tahap demo utama kamera+audio:** membuktikan akuisisi data, pengolahan dua jalur, pengiriman hasil dan tampilan monitoring. Servo belum terintegrasi dengan audio; demo meja SG90 dibuat terpisah sebagaimana bagian tambahan di atas. Gerbang lengkap, HC-SR04, LCD dan MQTT belum menjadi bagian demo utama. Sensor jarak yang disepakati untuk pengembangan berikutnya adalah HC-SR04; tidak ada klaim interlock anti-jepit telah selesai.

## Yang sudah dibuat dan bukti yang tersedia

| Bagian | Hasil pekerjaan | Bukti dan batas |
|---|---|---|
| Vision | Landmark wajah, EAR, status kedua mata, penghitung kedipan, overlay | Tes logika/geometri/lifecycle sudah ada. Uji webcam awal dilakukan; validasi dua kedipan pada manusia dengan variasi kondisi belum selesai. |
| Audio ML | STFT + MFCC/fitur spektral, StandardScaler, Random Forest 100 pohon | Artifact model dan metrik tersedia. Dataset awal **sintetis**, bukan rekaman MAX9814. |
| Evaluasi audio awal | 1.200 sampel, 960 train, 240 test; accuracy/precision/recall/F1 = 1,0 | Angka pada `training_metrics.json`; **tidak berarti akurasi suara nyata 100%**. |
| Dashboard | Flask, video lokal, spektrum, status kedua jalur dan diagnosis paket | Tes API, tampilan, kondisi menunggu/basi/error tersedia. |
| Kontrak ESP–Python | Format paket suara dan ringkasan hasil | Serializer C++ produksi diuji terhadap parser Python, model asli pada sinyal buatan dan UDP loopback. Bukan uji radio Wi-Fi/ADC fisik. |
| Firmware ESP32-S3 | Satu `.ino`, ADC continuous/DMA, antrean terbatas, kirim UDP, terima ringkasan untuk Serial | Tiga target kompilasi Arduino lulus: USB native kosong, native terkonfigurasi dummy, UART terkonfigurasi dummy. Tidak ada upload otomatis. |
| Perbaikan restart | Seluruh lifecycle ADC dipindah ke task akuisisi yang sama; jaringan menunggu ADC siap | Regresi kepemilikan task direproduksi gagal sebelum fix dan lulus sesudah fix. Audit software lokal selesai. Uji ulang fisik fix terbaru belum terbukti. |

Model RF tidak dilatih di ESP. Model wajah menggunakan model pretrained Google; tim membuat pengolahan EAR/aturan waktu dan integrasinya, bukan melatih model wajah sendiri dari nol.

## Kendala terakhir: ESP restart

Log fisik sebelumnya menunjukkan `assert failed: xTaskPriorityDisinherit`, disertai reboot. Hasil penelusuran menunjukkan ADC dimulai pada task Arduino tetapi dihentikan saat recovery di task lain. Driver ADC menggunakan mutex yang harus dilepas oleh pemiliknya.

**Perbaikan:** pembuatan/config/start/read/stop/flush/recovery/cleanup ADC kini dilakukan di task akuisisi yang sama. `setup()` hanya menyiapkan task; komunikasi jaringan menunggu ADC siap. Wiring, model dan protokol tidak diubah untuk perbaikan ini.

Bukti lokal sebelum publikasi:
- **74 eksekusi simulasi HAL**, **9 kasus protokol** dan **5 tes Python layout/kontrak** lulus untuk perbaikan firmware.
- **3 kompilasi Arduino** lulus tanpa warning yang tercatat.
- Pemeriksaan independen tidak menemukan cacat penghambat; audit akhir lokal diselesaikan setelah izin pengguna.

Angka tersebut berasal dari suite yang berbeda: **jangan dijumlahkan seolah semuanya uji fisik atau satu tes tunggal**. Repo menyediakan kode tes agar dapat diulang; log/build/audit internal mesin pengembang tidak ikut diunggah.

## Yang belum boleh diklaim selesai

- [ ] ESP stabil setelah firmware perbaikan benar-benar di-upload pengguna.
- [ ] Rate sampling ADC 16 kHz **terukur secara fisik**, bukan hanya dikonfigurasi/dites simulasi.
- [ ] Audio MAX9814 terkirim terus-menerus pada jaringan demo.
- [ ] Dashboard dan baris Serial mengikuti hasil baru yang sama pada perangkat.
- [ ] Akurasi/false alarm sirene nyata pada jarak, kebisingan dan sumber suara berbeda.
- [ ] Tantangan dua kedipan tervalidasi pada berbagai orang, kacamata dan pencahayaan.
- [ ] Pengenal identitas, ketahanan replay, izin masuk atau kontrol gerbang.
- [ ] Servo, HC-SR04, LCD, MQTT dan pengaman fisik terintegrasi.

## Urutan demo saat pertemuan

1. Tunjukkan diagram alur dan dashboard lokal terlebih dahulu.
2. Tunjukkan perubahan EAR/status mata bila kamera berhasil; jelaskan ini bukan face recognition.
3. Bila ESP stabil, tunjukkan paket masuk dan Serial mengikuti dashboard.
4. Bandingkan sepi, bicara dan pemutaran sirene volume wajar. Sebut hasil ini **observasi awal**, bukan evaluasi dataset final.
5. Jika board/jaringan masih bermasalah, tunjukkan kode dan hasil tes software dengan label yang jujur; jangan mengganti data fisik dengan simulasi tanpa menyebutnya.

## Rencana berikutnya

| Prioritas | Pekerjaan | Selesai jika |
|---|---|---|
| 1 | Uji ulang board setelah fix ADC | Tidak ada panic/reboot berulang; sampling dan recovery diamati pada perangkat. |
| 2 | Validasi transport suara | Paket bertambah terus, gap dicatat, Serial/dashboard cocok dan hasil menjadi basi ketika sumber berhenti. |
| 3 | Dataset nyata | Rekaman berizin dengan label/asal/kondisi yang jelas; split berdasarkan sumber/sesi sebelum augmentation. |
| 4 | Evaluasi ulang audio dan vision | Confusion matrix, precision/recall/F1, false alarm, kondisi gagal serta uji kedipan manusia dicatat. |
| 5 | Desain integrasi gerbang dan safety | Peran HC-SR04, servo, suplai dan kondisi gagal disepakati; pengaman tidak bergantung hanya pada ML. |

## Pertanyaan untuk dosen

- Untuk penilaian tahap ini, apakah fokus cukup pada dua model + monitoring, atau perlu aktuator fisik?
- Berapa banyak data nyata dan kondisi pengujian yang diharapkan?
- Apakah dibutuhkan identifikasi orang, atau cukup pengamatan wajah/kedipan? Keduanya berbeda lingkup.
- Metrik mana yang paling diprioritaskan: recall sirene, false alarm, latensi total, atau kestabilan integrasi?

Tidak memakai persentase “proyek sekian persen” karena kebutuhan akhir dan validasi fisiknya belum lengkap. Tabel di atas lebih bisa diperiksa.

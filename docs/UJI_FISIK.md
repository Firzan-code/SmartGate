# Urutan uji fisik dua model

Ini **checklist yang harus dilakukan**, bukan laporan semua langkah sudah lulus. Firmware perbaikan ADC sudah lulus audit software; kestabilan fisiknya masih perlu dibuktikan setelah upload manual pengguna.

## A. Siapkan laptop

- [ ] Pasang dependensi dan unduh model sesuai [README](../README.md).
- [ ] Jalankan `run_dashboard.py`; buka http://127.0.0.1:5000.
- [ ] Terminal tetap terbuka; webcam tidak sedang dipakai aplikasi lain.
- [ ] Catat IPv4 Wi-Fi laptop (cocokkan baris `SERVER_IP` dengan `ipconfig`).
- [ ] ESP dapat memakai Wi-Fi 2,4 GHz pada LAN yang sama; tidak ada isolasi antarklien.
- [ ] Izinkan Python/UDP5006 pada jaringan privat tepercaya jika dibutuhkan, bukan mematikan firewall keseluruhan.

Kamera dapat diuji walaupun ESP belum siap. Paket audio nol dan MENUNGGU adalah normal pada tahap ini. Tidak ada data sirene buatan yang otomatis menggantikan ESP.

## B. Wiring dan upload manual

Cabut USB saat mengubah kabel. MAX9814: VDD→3V3, GND→GND, OUT→GPIO1. Bukan GPIO44/RX; tidak memasang servo, HC-SR04 atau LCD untuk uji ini.

1. Salin folder sketch integrasi ke **luar repo**. Isi tiga konfigurasi di salinan itu.
2. Pastikan sketch bernama `tes_dua_model_esp32s3.ino` dan ada di folder bernama sama. Tidak perlu `secrets.h` atau header proyek.
3. Pilih ESP32S3 Dev Module, core 3.3.11 untuk konfigurasi yang pernah dikompilasi.
4. USB native: CDC Enabled, USB Mode Hardware CDC and JTAG. USB-to-UART: jalur serial UART/CDC Disabled. Pilih port yang benar.
5. Verify lalu Upload. Buka kembali Serial Monitor 115200 pada port yang terdeteksi setelah upload.
6. Tidak perlu mengetik perintah. Bila upload selesai tetapi aplikasi belum mulai, pengguna dapat menekan EN/RESET singkat; jangan menahan BOOT untuk menjalankan aplikasi.

**Penting:** buka ulang file terbaru dari disk bila IDE masih menyimpan buffer kode lama. Jangan menyimpan buffer versi sebelum fix di atas file terbaru.

## C. Buktikan restart berhenti dahulu

- [ ] Amati setidaknya 30 detik. Ini checkpoint awal, bukan soak test kestabilan jangka panjang.
- [ ] Tidak ada `assert failed: xTaskPriorityDisinherit`, `Backtrace`, atau `Rebooting...` berulang.
- [ ] Jika panic tetap muncul, hentikan penilaian ML dan simpan log lengkap dari boot sampai panic. Jangan langsung mengganti wiring atau threshold.

`BASI/MENUNGGU` bukan panic. Label itu dapat muncul ketika server belum memberikan ringkasan baru.

## D. Buktikan transport audio

- [ ] Jumlah paket dashboard bertambah, bukan tetapnol.
- [ ] Setelah satu detik data utuh, window audio terbentuk dan hasil menjadi aktif.
- [ ] Catat gap/overflow dan apakah input terus-menerus.
- [ ] Ringkasan baru WAJAH/MATA/EAR/KEDIP/SUARA/P pada Serial sesuai dashboard.

Jika nol paket: cek firmware yang benar, IP tujuan laptop, SSID/jaringan, firewall UDP 5006 dan client isolation. Jika paket ada tetapi gap terus, periksa kontinuitas/sampling/jaringan sebelum mengubah model. Target 16 kHz pada konfigurasi bukan bukti rate fisik sudah terukur.

## E. Variasikan stimulus, satu per satu

Gunakan volume wajar. Jangan meniup/memukul kapsul atau memutar suara keras berbahaya.

| Kondisi | Catat |
|---|---|
| Ruangan sepi | Paket, status, probabilitas, ADC min/max/P2P |
| Bicara biasa | Perubahan sinyal dan false positive |
| Tepuk wajar | Apakah sesaat atau terus salah mendeteksi |
| Putar rekaman sirene dari HP | Probabilitas, hit berturut-turut dan keterlambatan |
| Hentikan sirene | Prediksi kembali mengikuti input baru |

Model membutuhkan jendela 1 detik dan dua prediksi ≥0,80 berturut-turut, hop 0,5 detik. Hasil tidak seketika dan model sintetis mungkin gagal pada suara nyata.

Vision:
- [ ] Kedua mata terbuka: EAR melewati ambang buka; kalibrasi jika tidak.
- [ ] Dua kedipan alami dalam 5 detik: hitungan mengikuti gerakan nyata.
- [ ] Menutup satu mata/terlalu lama tidak dihitung sebagai siklus bilateral sah.
- [ ] Keluar dari frame menghapus riwayat tantangan.
- [ ] Ulangi pada pencahayaan/kacamata/jarak yang relevan; catat kegagalan.

Kedipan tidak membuktikan identitas atau ketahanan terhadap video replay.

## F. Putus dan pulihkan

1. Hentikan server laptop sementara Serial tetap terbuka: hasil ESP harus menjadi BASI/MENUNGGU, bukan terus menampilkan prediksi lama sebagai baru.
2. Jalankan server kembali: tunggu buffer data segar, lalu periksa hasil kembali mengikuti input.
3. Uji putus Wi-Fi terpisah. Jika IP laptop berubah, perbarui konfigurasi secara lokal.
4. Catat panic/reconnect/gap; ulangi durasi lebih panjang setelah checkpoint awal berhasil.

## G. Bukti yang aman dibagikan

Kirim baris Serial terbaru, kondisi suara/kamera saat itu, screenshot dashboard jika diizinkan, serta waktu/durasi pengujian. Jangan kirim password, isi konfigurasi atau rekaman wajah/audio pribadi tanpa izin. Repo tidak menyediakan rekaman otomatis.

Jika memakai `--report reports/uji_saya.json`, launcher hanya menyimpan status akhir/metrik. Folder `reports/` diabaikan Git. Jangan menyatakan “tes fisik lulus” hanya karena file report berhasil ditulis.

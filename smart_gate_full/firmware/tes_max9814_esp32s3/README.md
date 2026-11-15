# Tes MAX9814 saja — ESP32-S3 / Arduino IDE

## Wiring tiga kabel
Cabut USB sebelum memasang kabel.

| MAX9814 | ESP32-S3 |
|---|---|
| VDD / VCC | 3V3 |
| GND | GND |
| OUT / OUTPUT | GPIO1, **bukan RX/GPIO44** |

HC-SR04, servo, LCD, dan sumber daya eksternal tidak diperlukan. Gunakan USB laptop untuk ESP32; VDD mikrofon mengambil 3V3 board. GAIN/A-R mengikuti default modul jika dokumentasi breakout mengizinkan tidak tersambung.

## Arduino IDE
1. Buka `tes_max9814_esp32s3.ino` dari folder bernama sama.
2. Paket board **esp32 by Espressif Systems 3.x**, board **ESP32S3 Dev Module**. Verifikasi pengembangan memakai core 3.3.11. Tidak memerlukan library tambahan.
3. Pilih COM milik ESP32-S3. Jika memakai port **USB-to-UART/UART**, USB CDC On Boot = **Disabled**. Jika memakai port **USB native**, USB Mode = **Hardware CDC and JTAG** dan USB CDC On Boot = **Enabled**; pilih ulang COM setelah upload bila berubah.
4. Klik Verify lalu Upload; upload mengganti firmware sebelumnya di board.
5. Buka Serial Monitor pada **115200 baud**. Tidak perlu mengirim perintah: laporan otomatis setiap 250 ms.

## Cara membaca hasil
- `RAW`: sampel ADC terakhir, resolusi 12 bit (0–4095).
- `MIN` / `MAX`: nilai minimum/maksimum selama jendela laporan.
- **`P2P` = MAX − MIN**: amati perubahannya saat sepi dibanding bicara/tepuk tangan pada jarak wajar. Jangan memukul atau meniup langsung kapsul mikrofon.
- `AVG`: rata-rata ADC. Tidak harus nol saat sepi karena output MAX9814 memiliki bias DC.
- `N`: jumlah sampel nyata dalam jendela. Sampling best-effort, bukan stream audio seragam 16 kHz.
- `CLIP=YES`: terdapat sampel mendekati rail ADC; periksa suplai, GND, OUT dan suara terlalu kuat. Bukan diagnosis tunggal modul rusak.

Tes sepi beberapa detik, lalu bicara atau tepuk di dekat mikrofon. Tidak ada nilai P2P universal untuk menyatakan modul normal; perhatikan perubahan yang konsisten dan kirim hasil beberapa baris. MAX9814 mempunyai AGC. ADC mengambang pada OUT yang lepas juga bisa berubah, sehingga angka bergerak saja bukan bukti koneksi benar. Jika selalu 0/4095 atau tidak merespons suara, cabut daya lalu cek VDD/GND/OUT.

Ini tes pembacaan mikrofon saja: **tidak mengeluarkan audio ke speaker, bukan nilai dB, dan belum deteksi sirene/ML**. Compile dan uji perangkat lunak tidak memverifikasi wiring/tegangan/perangkat fisik.

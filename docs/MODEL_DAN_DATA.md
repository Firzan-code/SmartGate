# Model, data dan arti hasil evaluasi

## Dua jalur, bukan dua model yang dilatih dari nol

| Jalur | Komponen ML | Bagian yang dibuat pada proyek |
|---|---|---|
| Vision | **MediaPipe Face Landmarker pretrained** dari Google | Perhitungan EAR, aturan waktu kedipan, overlay, status dan integrasi. |
| Audio | **Random Forest** dari scikit-learn | Generator/loader data, ekstraksi 30 fitur, training, evaluasi, ekspor dan inferensi jaringan. |

Kedipan/EAR adalah pengukuran geometri dan aturan temporal. Tidak ada model face recognition untuk mengenali nama/identitas orang.

## Audio: input dan fitur

Input model: satu detik audio mono 16 kHz. Sampel ADC MAX9814 berasal dari ESP, bukan mikrofon laptop.

STFT: N = 1024, hop = 512, Hann window. Vektor 30 fitur:
- Band Energy Ratio 600–1800 Hz: mean dan std (2).
- 13 MFCC: mean dan std (26).
- Spectral centroid mean dan variasi frekuensi puncak (2).

Fitur dinormalisasi dengan `StandardScaler`, lalu Random Forest 100 pohon, max_depth 10, random_state 42. Output dua kelas: sirene dan non-sirene. Modul **tidak** memahami percakapan atau mengklasifikasikan semua jenis suara.

## Data awal dan metrik yang tersedia

Artifact [`training_metrics.json`](../ml_engine/models/training_metrics.json) mencatat:

| Item | Nilai |
|---|---|
| Total sampel | 1.200 |
| Train / test | 960 / 240 |
| Accuracy / precision / recall / F1 | 1,0 pada split sintetis ini |
| Confusion matrix | `[[120,0],[0,120]]` |
| Rata-rata waktu `predict_proba` per sampel | 4,171ms pada pengukuran pengembangan |

**Dataset yang menghasilkan artifact saat ini adalah sintetis.** Sirene dibuat dari pola frekuensi wail/yelp/hi-lo; negatif berupa simulasi klakson, mesin, percakapan dan noise. Ini memberi baseline program, bukan pengganti variasi mikrofon, jarak, ruangan dan sirene nyata.

Angka 100% **tidak boleh ditulis sebagai akurasi MAX9814 lapangan 100%**. Pengukuran 4,171 ms hanya model pada fitur yang sudah dihitung, bukan waktu STFT, akuisisi satu detik, transport atau end-to-end.

## Menjalankan vs training ulang

Untuk demo, gunakan model yang sudah disertakan. `run_dashboard.py` tidak otomatis melatih ulang atau mengganti input hilang dengan suara sintetis.

Training adalah eksperimen terpisah dan akan **menulis ulang** model serta metrik lokal:

```bat
.venv\Scripts\python.exe -m ml_engine.train_siren_model
```

Skrip dapat membaca WAV dari `ml_engine/dataset/siren/` dan `ml_engine/dataset/non_siren/`, tetapi juga menambahkan data sintetis. Loader melakukan pemotongan satu detik. **Split bawaan masih per chunk, bukan per sumber rekaman**; jangan memakai alur itu sebagai evaluasi final data nyata tanpa memperbaiki pemisahan sumber/sesi. Potongan satu rekaman bisa sangat mirip dan menyebabkan kebocoran train/test.

Rencana evaluasi nyata: catat asal/izin/label/kondisi setiap rekaman, pisahkan sumber/sesi sebelum augmentation, gunakan hard negatives (bicara, musik, klakson, kipas, motor), lalu laporkan confusion matrix, false alarm, precision/recall/F1 serta latensi total. Belum dilakukan dalam rilis awal.

## Asal model wajah

- Sumber: Google MediaPipe Face Landmarker, float16, versi1.
- Unduhan: https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
- Dokumentasi: https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python
- SHA256: `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`
- Ukuran: 3.758.596 byte.

Jalankan `scripts/download_models.py`; file diunduh ke lokasi yang diharapkan kode dan tidak dimasukkan Git. Ini mempermudah clone dan menjelaskan sumber model pihak ketiga; tidak ada pengiriman foto pengguna ke layanan Google oleh downloader tersebut. Lihat ketentuan sumber resminya untuk penggunaan/redistribusi.

## Asal model sirene AST

- Sumber: [Release GitHub `model-siren-ast-v2-20261122`](https://github.com/Firzan-code/SmartGate/releases/tag/model-siren-ast-v2-20261122), lima file isi folder `siren_ast_v2`.
- Model dasar: `MIT/ast-finetuned-audioset-10-10-0.4593`; artefak dibuat 2026-11-22 16:21 UTC.
- File utama `siren_ast_fp16.onnx`: 171.407.125 byte, SHA256 `4bac249112a43a7ebb91d9eba4dfe088209cc69dc76876d662405a6a0e134c21`.
- Ukuran dan SHA256 keempat file JSON tercatat di `scripts/download_models.py` dan di halaman release.

`scripts/download_models.py` mengunduh kelima file tersebut ke `ml_engine/models/siren_ast_v2` dan menolak file yang ukuran atau checksum-nya berbeda. Model ini tidak dimasukkan Git karena file ONNX melebihi batas 100 MB per file GitHub.

## Keamanan artifact model

`ml_engine/models/siren_rf_model.pkl` memuat model dan scaler melalui joblib. Format pickle/joblib dapat menjalankan kode saat dimuat. **Jangan memuat artifact dari sumber tidak dipercaya.** File proyek yang disertakan dipakai untuk mereproduksi baseline, bukan jaminan untuk model lain dengan nama serupa.

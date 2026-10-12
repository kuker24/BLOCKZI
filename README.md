# Shopee Blockzi Autonomous Bot & Co-Pilot

Autonomous bot dan web co-pilot untuk memainkan game Shopee Blockzi secara otomatis via Android Debug Bridge (ADB) dengan dukungan deteksi board computer vision, solver penempatan balok (lookahead sequence search), manajemen booster cerdas, serta recovery otomatis via iklan Warung Shopee (Revive).

---

## Fitur Utama

1. **Autonomous Pilot (`autobot/engine.py`)**
   - Mengendalikan touch event perangkat via ADB (`input motionevent DOWN / MOVE / UP`).
   - Kalibrasi presisi untuk Xiaomi 13T (1220x2712): touch scale, lift offset, dock bbox detection.
   - Deteksi status game real-time: `PLAYING`, `VICTORY`, `DEFEAT`.
   - Auto-advance ke level berikutnya saat menang.
   - Otomatis berhenti ketika mencapai target (Level 90).

2. **Smart Revive & Anti-Defeat Flow**
   - Mendeteksi pop-up countdown Revive kuning sebelum timer 6 detik habis.
   - Melakukan bypass/scroll otomatis pada halaman iklan Warung Shopee selama ~33 detik lalu kembali ke permainan tanpa reset skor.
   - Fallback otomatis ke tombol "Main Lagi" jika Revive tidak tersedia atau kuota habis.

3. **Manajemen Booster Konservatif & Anti-Shop Popup**
   - Deteksi badge stok booster (Ekstra Balok, Bom, Remove).
   - Booster Remove diutamakan saat buntu, disusul Ekstra Balok dan Bom sebagai opsi darurat.
   - Fitur **Permanent Auto-Block**: mendeteksi jika booster membuka popup toko koin (stok asli 0) dan memblokir booster tersebut agar tidak membuang waktu hitung mundur Revive.

4. **Kecepatan & Solver Adaptif (MIN, MAX, ADAPTIVE)**
   - **MIN**: Solver brute-force tanpa batas waktu dan drag lambat berpresisi tinggi.
   - **MAX**: Timeout solver 800ms dan gerakan drag kilat.
   - **ADAPTIVE (Default)**: Waktu berpikir solver dan kecepatan sentuhan disesuaikan otomatis berdasarkan kepadatan papan:
     - Board < 20% (0–12 sel): timeout 800ms (kilat).
     - Board 20%–40% (13–25 sel): timeout 1500ms.
     - Board 40%–60% (26–38 sel): timeout 3000ms.
     - Board 60%–80% (39–51 sel): timeout 5000ms.
     - Board > 80% (52+ sel): timeout 8000ms (kritis, kalkulasi mendalam).

5. **Web Dashboard Co-Pilot (`copilot/`)**
   - Antarmuka web lokal di `http://localhost:5000`.
   - Visualisasi real-time papan 8x8, posisi batu permata (gems), balok dock, dan urutan solusi.
   - Kontrol toggle Auto Play, pemilihan mode kecepatan (`MIN`, `MAX`, `ADAPTIVE`), sakelar Booster, dan sakelar Revive.

---

## Struktur Proyek

```text
.
├── autobot/
│   └── engine.py           # Core automation engine, ADB touch model, Revive & booster logic
├── copilot/
│   ├── server.py           # Flask server & AutoController background thread
│   ├── solver.py           # Board vision, piece detection, lookahead sequence solver
│   ├── static/             # Static assets untuk web dashboard
│   └── templates/
│       └── index.html      # Web dashboard UI
├── benchmark_opsi.py       # Benchmark skenario solver
├── blockzi_bot.py          # Script prototype solver standalone
├── blockzi_infinite.py     # Script runner mode tak terbatas
├── scrcpy_bot_v2.py        # Eksperimen kontrol alternatif
├── test_*.py               # Unit test & modul diagnostik deteksi
├── .gitignore
└── README.md
```

---

## Kebutuhan Sistem

- Python 3.10+
- Android Device (direkomendasikan Xiaomi 13T resolusi 1220x2712) dengan USB Debugging aktif
- Android SDK Platform-Tools (`adb`) terpasang di PATH
- Paket Python:
  ```bash
  pip install flask pillow numpy
  ```

---

## Cara Menjalankan

1. Hubungkan ponsel via USB dan pastikan terdeteksi:
   ```bash
   adb devices
   ```

2. Buka game Shopee Blockzi di ponsel hingga berada di layar permainan.

3. Jalankan server Co-Pilot:
   ```bash
   python3 copilot/server.py
   ```

4. Buka browser ke:
   ```text
   http://localhost:5000
   ```

5. Aktifkan sakelar **Auto** di dashboard web untuk memulai bot autonomous.

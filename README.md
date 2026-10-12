# Shopee Blockzi Autonomous Bot & Co-Pilot (solver-v2)

Autonomous bot dan web co-pilot untuk memainkan game Shopee Blockzi secara otomatis via Android Debug Bridge (ADB) dengan dukungan deteksi board computer vision, 64-bit bitboard solver penempatan balok (anytime sequence search), manajemen booster cerdas, serta recovery otomatis via iklan Warung Shopee (Revive).

---

## Fitur Utama

1. **64-bit Bitboard Solver Engine (`copilot/solver.py`) [v2 Upgrade]**
   - **Bitboard Representation**: Papan 8x8 dan batu permata (gems) direpresentasikan sebagai 64-bit unsigned integer (`uint64`).
   - **Bitwise Clears & Holes**: Deteksi baris/kolom penuh, clearing, dan perhitungan lubang terisolasi (*isolated holes*) sepenuhnya menggunakan manipulasi bit tanpa alokasi array numpy per langkah.
   - **Strict Anytime Deadline**: Pembatasan waktu presisi tinggi berbasis `time.perf_counter()` di loop terluar, loop permutasi, hingga pengecekan periodik di leaf loop dengan fallthrough bertingkat (3-step → 2-step → 1-step).
   - **Permutation Deduplication**: Deduplikasi permutasi balok yang memiliki bentuk identik untuk memangkas pohon pencarian hingga 6x lipat pada skenario terburuk.
   - **Transposition Table**: Memoization state papan untuk memangkas cabang penempatan ekuivalen.
   - **Move Ordering**: Heuristik urutan langkah berbasis line clear pada mode berbatas waktu untuk mempercepat penemuan solusi optimal secara instan.
   - **Class-4 Piece Vision**: Deteksi akurat balok panjang 4 sel (`1x4`, `4x1`) dengan ambang batas adaptif terkalibrasi rasio resolusi (`fx`).

2. **Evaluasi Heuristik (v1 vs v2)**
   - Konfigurasi via variabel `BLOCKZI_EVAL`:
     - `v1` (Default): Kompatibilitas bit-exact dengan formula evaluasi dasar (`clears * 1500 + gems * 400 - bits * 15 - holes * 35`).
     - `v2`: Peningkatan kesadaran spasial dengan penalti lubang lebih ketat dan bonus ketersediaan ruang untuk balok besar `3x3` (+120) dan `1x5`/`5x1` (+60). Meningkatkan skor rata-rata pada simulasi self-play tanpa meningkatkan risiko game-over.

3. **Keamanan & Hardening Server (`copilot/server.py`)**
   - Default network binding ke `127.0.0.1` (loopback only) untuk mencegah akses tidak sah dari jaringan lokal.
   - Autentikasi opsional menggunakan token via `BLOCKZI_TOKEN` (`Authorization: Bearer <token>` atau `X-Blockzi-Token`).
   - Proteksi CSRF berbasis validasi header `Origin` dan `Referer` pada request mutasi state (`POST /api/auto`, `POST /api/action`).
   - Validasi ketat tipe data dan koordinat sentuhan (`x`, `y`) dalam batas resolusi layar device.
   - Tidak ada hardcoded path sistem (`/home/...` atau `/tmp/...`); seluruh konfigurasi terpusat di `blockzi_config.py`.

4. **Autonomous Pilot (`autobot/engine.py`)**
   - Mengendalikan touch event perangkat via ADB (`input motionevent DOWN / MOVE / UP`).
   - Kalibrasi presisi untuk Xiaomi 13T (1220x2712): touch scale, lift offset, dock bbox detection.
   - Deteksi status game real-time: `PLAYING`, `VICTORY`, `DEFEAT`.
   - Propagasi deadline solver (`max_ms`) pada seluruh panggilan solver termasuk solve pratinjau langkah kedua.
   - Auto-advance ke level berikutnya saat menang dan berhenti saat mencapai target (Level 90).

5. **Smart Revive & Anti-Defeat Flow**
   - Mendeteksi pop-up countdown Revive kuning sebelum timer 6 detik habis.
   - Melakukan bypass/scroll otomatis pada halaman iklan Warung Shopee selama ~33 detik lalu kembali ke permainan tanpa reset skor.
   - Fallback otomatis ke tombol "Main Lagi" jika Revive tidak tersedia atau kuota habis.

6. **Web Dashboard Co-Pilot (`copilot/`)**
   - Antarmuka web lokal di `http://127.0.0.1:5000`.
   - Visualisasi real-time papan 8x8, posisi batu permata (gems), balok dock, dan urutan solusi.
   - Dukungan transmisi token autentikasi jika server diproteksi `BLOCKZI_TOKEN`.
   - Kontrol toggle Auto Play, pemilihan mode kecepatan (`MIN`, `MAX`, `ADAPTIVE`), sakelar Booster, dan sakelar Revive.

---

## Struktur Proyek

```text
.
├── autobot/
│   ├── autobot.log         # Runtime bot log (dikonfigurasi via BLOCKZI_LOG_FILE)
│   └── engine.py           # Core automation engine, ADB touch model, Revive & booster logic
├── bench/
│   ├── bench.py            # Suite benchmark reproducible (seed 42 baseline vs solver-v2)
│   └── results/
│       └── baseline.txt    # Rekaman benchmark baseline pada commit 9db8281
├── copilot/
│   ├── server.py           # Hardened Flask server & AutoController background thread
│   ├── solver.py           # 64-bit Bitboard solver engine dengan anytime search & vision
│   ├── solver_legacy.py    # Snapshot solver v1 legacy untuk verifikasi parity
│   ├── static/             # Static assets untuk web dashboard
│   └── templates/
│       └── index.html      # Web dashboard UI dengan auth header support
├── tests/
│   ├── golden/
│   │   └── solver_v1.json  # 17 kasus uji golden dari berbagai tingkat kepadatan papan
│   ├── test_bitboard_parity.py # Parity unit tests (holes & step simulation)
│   ├── test_piece_dims.py  # Unit tests klasifikasi ukuran balok (kelas 1 s/d 5)
│   ├── test_server.py      # Security & API route unit tests (auth, CSRF, bounds)
│   ├── test_solver_golden.py # Verifikasi bit-exact parity terhadap solver legacy
│   └── test_solver_timeout.py # Anytime deadline unit tests (worst-case empty board)
├── tools/
│   ├── diagnostics/        # Skrip diagnostik ADB & vision terisolasi
│   │   ├── detect.py
│   │   ├── mcp_debug.py
│   │   ├── mcp_vision.py
│   │   └── scrcpy_mcp.py
│   ├── generate_golden.py  # Generator dataset golden test
│   └── selfplay.py         # Offline self-play simulator (komparasi v1 vs v2)
├── blockzi_config.py       # Konfigurasi terpusat dan environment variables
├── pytest.ini              # Konfigurasi pytest test runner
├── requirements.txt        # Dependensi produksi tersemat (pinned)
├── requirements-dev.txt    # Dependensi pengujian & linting (pytest, ruff)
├── README.md
└── .gitignore
```

---

## Konfigurasi Lingkungan (Environment Variables)

Semua opsi konfigurasi dapat diatur melalui variabel lingkungan (environment variable):

| Variabel | Tipe / Pilihan | Default | Deskripsi |
|---|---|---|---|
| `BLOCKZI_HOST` | String | `127.0.0.1` | Alamat IP binding server Flask. Peringatan keamanan muncul jika dibind ke non-loopback tanpa token. |
| `BLOCKZI_PORT` | Integer | `5000` | Port listening server Flask. |
| `BLOCKZI_TOKEN` | String | `""` (kosong) | Token rahasia autentikasi untuk endpoint mutasi state (`/api/action`, `/api/auto`). |
| `BLOCKZI_SOLVER_MAX_MS` | Integer | `200` | Batas waktu default pemecahan solver dalam milidetik. |
| `BLOCKZI_EVAL` | `v1` \| `v2` | `v1` | Pilihan mode evaluasi heuristik leaf node. |
| `BLOCKZI_LOG_FILE` | Path | `autobot/autobot.log` | Lokasi berkas log eksekusi bot. |
| `BLOCKZI_SCREEN_DIR` | Path | Sistem tempdir (`/tmp/blockzi`) | Direktori penyimpanan frame dan tangkapan layar runtime. |

---

## Kebutuhan Sistem & Instalasi

- Python 3.10+
- Android Device (direkomendasikan Xiaomi 13T resolusi 1220x2712) dengan USB Debugging aktif
- Android SDK Platform-Tools (`adb`) terpasang di PATH

Instalasi dependensi:
```bash
pip install -r requirements.txt

# Untuk pengujian dan linting:
pip install -r requirements-dev.txt
```

---

## Pengujian & Benchmark

Menjalankan seluruh rangkaian pengujian (unit tests & golden regression):
```bash
python3 -m pytest
```

Memeriksa kualitas kode dengan ruff:
```bash
ruff check . --select F
```

Menjalankan benchmark perbandingan solver (Seed 42):
```bash
python3 bench/bench.py
```

Menjalankan simulasi self-play untuk evaluasi v1 vs v2:
```bash
python3 tools/selfplay.py --games 10 --max-turns 50 --max-ms 150
```

---

## Hasil Benchmark (solver-v2 vs Baseline)

Dijalankan pada Intel Core i5-11400H / Python 3.13.5 (Seed 42):

| Kasus / Pengujian | Solver Asli (v1) | Solver v2 (Exhaustive) | Solver v2 (Budget 200ms) | Match Skor |
|---|---|---|---|---|
| Fill 0% (Trial 0) | 57,811 ms | 14,717 ms | 200 ms | Identik (YES) |
| Fill 10% (Trial 0) | 1,697 ms | 392 ms | 200 ms | Identik (YES) |
| Fill 20% (Trial 0) | 611 ms | 135 ms | 133 ms | Identik (YES) |
| Fill 30% (Trial 0) | 38 ms | 10 ms | 10 ms | Identik (YES) |
| Fill 50% (Trial 0) | 1 ms | 0.2 ms | 0.2 ms | Identik (YES) |
| **Worst-Case 3x (1x1)** | **101,292 ms** (~101 detik) | **4,204 ms** (24.1x lebih cepat) | **200.4 ms** (Anytime exit) | **Valid sequence** |

**Latensi Keseluruhan (18 trials seed 42):**
- **v1 Baseline**: `p50 = 36.0 ms` | `p95 = 44,723.5 ms` | `max = 57,811 ms`
- **v2 (Budget 200ms)**: `p50 = 10.4 ms` | `p95 = 200.7 ms` | `max = 201.0 ms`
- **Score Agreement Rate** (Exhaustive vs Anytime 200ms): **100.0%**

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
   http://127.0.0.1:5000
   ```

5. Aktifkan sakelar **Auto** di dashboard web untuk memulai bot autonomous.

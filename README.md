# TUK PCA

**A Multi-Stage SMT Line Dataset for Printed Circuit Assembly Manufacturing**

Multi-modal dataset collected from an operational Surface Mount Technology (SMT)
line at the Advanced Manufacturing Innovation Center (AMIC), Tech University of
Korea. Unlike conventional PCA datasets that are limited to end-of-line AOI
images, **TUK PCA** integrates upstream process logs (chip / multi mounter),
multi-zone reflow oven thermal profiles, and AOI inspection results, enabling
research on **process-aware defect prediction, multi-modal learning, and
explainable quality analysis**.

> Kim, J. W., Bae, S. Y., & Bae, Y. S. *TUK PCA: A Multi-Stage SMT Line Dataset
> for Printed Circuit Assembly Manufacturing.* Submitted to the International
> Conference on Control, Automation and Systems (ICCAS) 2026.

---

## Highlights

- **Real production line, real operators.** No controlled lab setup, no
  artificial defect injection. All boards were processed under routine
  production by experienced enterprise operators.
- **Multi-modal across the full SMT line.** Mounting process logs + 190-zone
  reflow oven thermal profiles + AOI ROI images & inspection results.
- **Two-month acquisition window** (2025-10-15 ~ 2025-12-24).
- **25 board models**, 8,124 multi-mounted boards in raw, **4,178 boards
  synchronized** across mounting / reflow / AOI (57.23% match rate).
- **Industrial realism preserved.** Class imbalance (17.54% defect rate),
  long-tailed defect categories, partial AOI coverage, and equipment
  heterogeneity are kept as-is.
- **Time-based synchronization scripts included** (no shared board-level
  identifier across equipment → temporal anchoring on multi-mount end time).

---

## SMT Line Configuration

```
Loader → Screen Printer → Chip Mounter → Multi Mounter → Reflow Oven → Cooling Buffer → 3D AOI → Unloader
                              │              │              │                              │
                          process logs   process logs   thermal profile                 ROI images
                                                       (190 zones × 5min)            + defect labels
```

| Stage              | Equipment             | Output                          |
| ------------------ | --------------------- | ------------------------------- |
| Chip Mounting      | Yamaha YSM10          | PCB / Error / Program logs      |
| Multi Mounting     | Yamaha YSM10          | PCB / Error / Program logs      |
| Reflow Soldering   | Heller 1810MK7        | Journal files (SP/PV/OP × 190)  |
| Optical Inspection | MIRTEC MV-6e OMNI 3D  | ROI images + inspection results |

*Solder Paste Inspection (SPI) is **not** performed on this line, so no
Screen-Printer-side data is included.*

---

## Repository Layout

```
TUK_PCA/
├── concat/                                  # Cleaned, concatenated source data
│   ├── chip/
│   │   ├── pcb_log_concat.csv               # 7,472 board-level summaries
│   │   ├── error_log_concat.csv             # 174 error events
│   │   └── program_log_concat.csv           # 15,002 program events
│   ├── multi/
│   │   ├── pcb_log_concat.csv               # 8,124 board-level summaries
│   │   ├── error_log_concat.csv             # 413 error events
│   │   └── program_log_concat.csv           # 16,314 program events
│   ├── reflow oven concat.csv               # 14,738 samples × 190 zones × {SP,PV,OP}
│   ├── aoi_concat.csv                       # 2,966 ROI-level inspection rows
│   ├── aoi_file_index(전체검사결과).csv      # 6,416 AOI export-txt index
│   └── aoi_image_index.csv                  # 3,453 ROI / defect-image index
├── test/                                    # Reference matching pipeline & outputs
│   ├── chip.csv                             # Chip-mount input (= concat/chip/pcb_log)
│   ├── multi.csv                            # Multi-mount input
│   ├── aoi.csv                              # AOI inspection input
│   ├── matching_dt.py                       # Time-based synchronization script
│   ├── temporal matching.csv                # 7,301 anchored boards
│   └── temporal matching + full feature + defect.csv   # 4,178 synced boards + labels
├── LICENSE
└── README.md
```

---

## Data Modalities

### 1) Mounting Process Logs (Chip & Multi)

Generated automatically by the Yamaha line controller; one record per board
(`pcb_log`), one record per event (`error_log` / `program_log`).

Key columns (Korean originals from the controller; column count differs by log
type):

| Column            | Meaning                                |
| ----------------- | -------------------------------------- |
| `기판명`           | Board model name                       |
| `로트내 연번`      | Sequential index within lot            |
| `생산시작 시각`    | Production start timestamp             |
| `생산완료 시각`    | Production end timestamp (multi only)  |
| `실장CT(초) A~D`   | Mounting cycle time per head           |
| `반송CT(초)`       | Transfer cycle time                    |
| `대기CT(초)`       | Wait cycle time                        |
| `흡착에러 횟수`    | Pickup error count                     |
| `에러정지 횟수`    | Error-stop count                       |
| `에러정지 시간(초)` | Error-stop duration                    |
| `완료 플래그`      | Completion flag                        |

Finer-grained per-component logs (conveyor / feeder / nozzle / head / parts)
exist in the **raw** dataset but are intentionally excluded from `concat/` to
keep the released subset board-level and focused on cross-stage defect analysis.

### 2) Reflow Oven Thermal Data (Heller 1810MK7)

Recorded continuously every **5 minutes**, **not per board**. Each row is a
single sample with:

- `DateTime` — sample timestamp
- `SP{0..189}` — set-point for each of 190 control zones (°C)
- `PV{0..189}` — measured process value (°C)
- `OP{0..189}` — controller output percentage

Total: **14,738 samples × 571 columns**. Zones include not only oven heater
banks but also blower / conveyor / cooling-section channels — see Heller
documentation for the full zone map.

Because the oven has **no board-level identifier**, every board's reflow
context must be derived by *temporal* joining (see Synchronization below).

### 3) AOI ROI Images & Inspection Results (MIRTEC MV-6e OMNI)

The AOI system extracts component- and joint-level **regions of interest** from
each board image, then assigns a defect label per ROI by comparison with a
"golden board" reference defined during teaching.

`aoi_concat.csv` columns:

| Column                   | Meaning                                  |
| ------------------------ | ---------------------------------------- |
| `Inspector`              | AOI model (MV-6E)                        |
| `Model`                  | Board model                              |
| `SerialNo`               | **AOI-internal** serial (not mount-side) |
| `Start Date / End Date`  | Inspection time                          |
| `Module ID`              | Inspection module                        |
| `Ref. ID`                | Component reference designator (e.g. R12)|
| `Window ID`              | ROI window index for that component      |
| `DefectType`             | One of 13 categories (incl. `GOOD`)      |
| `PartName`               | Component part number                    |
| `Lot ID`                 | Component lot ID (often empty)           |
| `source_file`            | Source export `.txt` filename            |

The AOI image index (`aoi_image_index.csv`) maps `(model, serial_no)` to the
captured ROI / debug / merged image files on disk.

> ⚠️ The AOI `SerialNo` is an **inspection-centric** counter managed by the AOI
> software. It does **not** correspond one-to-one to the mounter-side board
> serial. This is why time-based synchronization is required.

---

## Time-Based Synchronization

No shared board-level identifier exists across {chip mounter, multi mounter,
reflow oven, AOI}. Synchronization therefore relies on the strictly sequential
physical workflow of the line and the line-level unified clock.

**Algorithm (`test/matching_dt.py`):**

1. **Anchor.** For each board `(model, lot_seq)` that appears in both `chip`
   and `multi` logs, define the reference time
   `t₀ = multi mount end time`.
2. **AOI candidate window.** Collect AOI inspections with
   `t₀ < t_AOI ≤ t₀ + 3h` for the same (normalized) model name. The window
   covers reflow processing + conveyor + buffer + wait times.
3. **Expected delay.** Use `t_ref = t₀ + 600 s` (≈10 min) as the expected AOI
   start (global median, tunable via `GLOBAL_DT_MEDIAN_SEC`).
4. **1:1 nearest match.** Select the unused AOI record minimizing
   `|t_AOI − t_ref|`. Each AOI inspection is consumed by at most one board.
5. **Production-order guard.** Reject any final match where `t_AOI < t₀`.
6. **Reflow join.** Each anchored board is associated with the nearest
   5-minute reflow oven sample (or an interval of samples spanning its reflow
   window).

**Model-name normalization** strips supplier prefixes (`SEIL-`, `SH-`), version
suffixes (`_241121`, `_250701`), and harmonizes synonymous codenames
(`KOREA_G_E_NEW_CONTROL → KOREA_NEW_CONTROL`,
`AIRDEEP_R+C_TYPE → AIRDEEP_C_TYPE`).

**Result:**

| Stage                                  | Boards |
| -------------------------------------- | -----: |
| Multi-mounted (raw)                    |  8,124 |
| Chip ∩ Multi (anchored)                |  7,301 |
| **Synchronized with AOI (final)**      | **4,178 (57.23%)** |

Boards without a matching AOI record are preserved as "unmatched" rather than
discarded, since AOI may be skipped or interrupted by operator intervention in
real production.

---

## Synchronized Subset Statistics

**Overall:** 4,178 boards · 3,445 good · 733 defective · **defect rate 17.54%**.

### Board-Model Distribution (Table 1 in paper)

| Model                  | Count | Good | Defect | Defect Rate |
| ---------------------- | ----: | ---: | -----: | ----------: |
| RTU_MAIN_TOP           | 1,205 |  920 |    285 |      23.65% |
| RTU_MAIN_BOT           | 1,005 |  967 |     38 |       3.78% |
| NEW_DELIM4             |   641 |  576 |     65 |      10.14% |
| ROOMCON_INI            |   517 |  316 |    201 |      38.88% |
| G1408CH_FULL           |   338 |  296 |     42 |      12.43% |
| RTU_SMPS               |   124 |  109 |     15 |      12.10% |
| KOREA_NEW_CONTROL      |   116 |  107 |      9 |       7.76% |
| IDS_9100_MAIN_TOP      |   109 |   83 |     26 |      23.85% |
| IDS_9100_MAIN_BOT      |    89 |   66 |     23 |      25.84% |
| AIRDEEP_C_TYPE_BOT     |    25 |    2 |     23 |      92.00% |
| KYK30K_MAIN            |     3 |    0 |      3 |     100.00% |
| AIRDEEP_M_TOP          |     3 |    2 |      1 |      33.33% |
| AIRDEEP_C_TYPE_TOP     |     2 |    0 |      2 |     100.00% |
| CONTROLLER_COMM        |     1 |    1 |      0 |       0.00% |
| **ALL**                | **4,178** | **3,445** | **733** | **17.54%** |

### Defect Category Distribution (Table 2 in paper)

| Defect Type         | Count | Share  |
| ------------------- | ----: | -----: |
| Insufficient Solder |   315 | 27.44% |
| Wrong Part          |   198 | 17.25% |
| Missing             |   150 | 13.07% |
| Tilt                |   144 | 12.54% |
| Shift               |   102 |  8.88% |
| Lifted Package      |    97 |  8.45% |
| Bridge              |    48 |  4.18% |
| Rotate              |    34 |  2.96% |
| Tombstone           |    33 |  2.87% |
| Lifted Lead         |    20 |  1.74% |
| Lifted Solder       |     6 |  0.52% |
| No Solder           |     1 |  0.09% |
| **Total**           | **733** | **100%** |

---

## Quick Start

```python
import pandas as pd

# 1. Load board-level mounting summaries
chip  = pd.read_csv("concat/chip/pcb_log_concat.csv",  encoding="utf-8-sig")
multi = pd.read_csv("concat/multi/pcb_log_concat.csv", encoding="utf-8-sig")

# 2. Load AOI inspection results (ROI-level)
aoi   = pd.read_csv("concat/aoi_concat.csv", encoding="utf-8-sig")

# 3. Load reflow oven thermal profile (190 zones × {SP,PV,OP})
oven  = pd.read_csv("concat/reflow oven concat.csv", parse_dates=["DateTime"])

# 4. Pre-synchronized subset with full features + defect label
synced = pd.read_csv(
    "test/temporal matching + full feature + defect.csv",
    encoding="utf-8-sig",
)
print(synced.shape)               # (4178, …)
print(synced["defect"].mean())    # ≈ 0.1754
```

### Re-running the synchronization

```bash
cd test
python matching_dt.py
# → match_outputs/temporal matching.csv
```

Tunable parameters at the top of `matching_dt.py`:

| Variable                 | Default | Meaning                                 |
| ------------------------ | ------: | --------------------------------------- |
| `GLOBAL_DT_LOW_SEC`      |       0 | Earliest AOI offset from `t₀`           |
| `GLOBAL_DT_HIGH_SEC`     |  10,800 | Latest AOI offset (3 h)                 |
| `GLOBAL_DT_MEDIAN_SEC`   |     600 | Expected reflow+transfer delay (10 min) |

---

## Acquisition Details

- **Site:** Advanced Manufacturing Innovation Center (AMIC), Tech University of
  Korea — see <https://amic.tukorea.ac.kr/visit/visitInfo/visitInfo.hs>.
- **Period:** 2025-10-15 ~ 2025-12-24 (synchronization applied to
  2025-10-27 ~ 2025-12-23).
- **Conditions:** Routine production runs by enterprise operators. No defect
  injection. No experimental manipulation. Equipment logs captured by line
  controllers with line-level unified clock.

---

## Suggested Research Directions

- **Process-aware defect prediction** combining mounting + reflow + AOI.
- **Multi-modal fusion** across tabular logs, time-series thermal profiles, and
  ROI images.
- **Robustness to missing data** — AOI is partial by design.
- **Long-tail / rare defect learning** under the realistic AOI label
  distribution (Insufficient Solder dominates; No Solder has only 1 sample).
- **Model-aware / hierarchical / transfer learning** to exploit board-model
  heterogeneity instead of fighting it.
- **Explainable quality analysis** linking upstream signals to downstream
  defects (e.g. why a particular Insufficient Solder occurred).

---

## Citation

If you use this dataset, please cite:

```bibtex
@misc{kim2026tukpca,
  title  = {TUK PCA: A Multi-Stage SMT Line Dataset for Printed Circuit
            Assembly Manufacturing},
  author = {Kim, Ji Woong and Bae, So Young and Bae, You Suk},
  year   = {2026},
  note   = {Dataset; associated paper submitted to ICCAS 2026},
  url    = {https://github.com/Mint1125/TUK_PCA}
}
```

## License

Released under the **MIT License** (see `LICENSE`). The dataset itself is
released for research and educational use; please respect any product- or
component-identifying information that may incidentally appear in AOI imagery.

## Acknowledgement

This research was supported by the **MSIT (Ministry of Science, ICT), Korea**,
under the *Global Research Support Program in the Digital Field*
(RS-2024-00431363), supervised by the **IITP (Institute for Information &
Communications Technology Planning & Evaluation)**.

## Contact

| Author        | Affiliation | E-mail                        |
| ------------- | ----------- | ----------------------------- |
| Ji Woong Kim  | Dept. of Computer Engineering, TUK | goldlaw2000@tukorea.ac.kr |
| So Young Bae  | Dept. of Computer Engineering, TUK | bsy0594@tukorea.ac.kr     |
| You Suk Bae   | Dept. of Computer Engineering, TUK | ysbae@tukorea.ac.kr       |

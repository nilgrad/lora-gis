# LoRa-GIS 915 MHz LoRa (MeshCore) Relay Report — Roscoe ↔ Livingston Manor ↔ Liberty (2026-11-23_08-10-37)

![Topographic Relay Map](map.png)

## 1. RF Link & Topology Overview

| Parameter | Value |
| :--- | :--- |
| **Operating Frequency** | `915.0 MHz` (LoRa / MeshCore, $\lambda = 32.8\text{ cm}$) |
| **Target Fresnel Clearance** | `>= 60%` of 1st Fresnel Zone ($F_1$), $K = 4/3$ Earth Curvature |
| **Intermediate Relay Height** | `18.3 m` (`60.0 ft`) AGL |
| **Roscoe** | `41.933153, -74.913498` — Ground Elev `390.8 m` (`1,282 ft`), Mount `10.00 m` (`32.8 ft`) AGL |
| **Livingston Manor (Repeater Hub)** | `41.900375, -74.828218` — Ground Elev `433.3 m` (`1,422 ft`), Mount `9.14 m` (`30.0 ft`) AGL |
| **Liberty** | `41.801209, -74.746552` — Ground Elev `457.8 m` (`1,502 ft`), Mount `10.00 m` (`32.8 ft`) AGL |
| **Shandelee Ridge (Candidate Relay)** | `41.880400, -74.889000`, Ground Elev `654.9 m` (`2,148 ft`), Mount `18.30 m` (`60.0 ft`) AGL |
| **Ferndale Ridge (Candidate Relay)** | `41.766500, -74.699700`, Ground Elev `440.8 m` (`1,446 ft`), Mount `18.30 m` (`60.0 ft`) AGL |
| **Willowemoc Ridge (Candidate Relay)** | `41.905600, -74.677400`, Ground Elev `642.4 m` (`2,108 ft`), Mount `18.30 m` (`60.0 ft`) AGL |
| **Direct Link (Roscoe ↔ Livingston Manor, `7.95 km`)** | BLOCKED BY TERRAIN (-185.3 m / -608 ft deficit) |
| **Viable 1-Hop Sites (Roscoe ↔ Livingston Manor)** | `0` (`Roscoe` at `33 ft`, `Livingston Manor` at `30 ft`) |
| **Viable 2-Hop Pairs (Roscoe ↔ Livingston Manor)** | `153` |
| **Direct Link (Livingston Manor ↔ Liberty, `12.93 km`)** | BLOCKED BY TERRAIN (-188.3 m / -618 ft deficit) |
| **Viable 1-Hop Sites (Livingston Manor ↔ Liberty)** | `0` (`Livingston Manor` at `30 ft`, `Liberty` at `33 ft`) |
| **Viable 2-Hop Pairs (Livingston Manor ↔ Liberty)** | `59` |

## 2. Roscoe ↔ Livingston Manor Link Analysis (`7.95 km` Direct)

- **Direct Distance**: `7.95 km` (`4.94 mi`)
- **Direct Line-of-Sight (`33 ft` at Roscoe → `30 ft` at Livingston Manor)**: **BLOCKED BY TERRAIN** — Minimum terrain clearance is `-185.3 m` (`-608 ft`), Min $F_1$ ratio `-810%`.

### Optimal 2-Hop Repeater Solution (Roscoe ↔ Livingston Manor, Solid Red Path)

| Node | Latitude, Longitude (WGS84) | UTM Zone 18N (E, N) | Ground Elevation | Mount Height (AGL) | Total Tip Elevation (ASL) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Roscoe** | `41.933153, -74.913498` | `E 507171.4, N 4642357.9` | `390.8 m` (`1,282 ft`) | `10.00 m` (`33 ft`) | `400.8 m` (`1,315 ft`) |
| **2-Hop Relay 1** | `41.920621, -74.884330` | `E 509591.4, N 4640969.4` | `606.0 m` (`1,988 ft`) | `18.3 m` (`60 ft`) | `624.3 m` (`2,048 ft`) |
| **2-Hop Relay 2** | `41.905989, -74.849633` | `E 512471.4, N 4639349.4` | `608.3 m` (`1,996 ft`) | `18.3 m` (`60 ft`) | `626.6 m` (`2,056 ft`) |
| **Livingston Manor** | `41.900375, -74.828218` | `E 514248.7, N 4638729.4` | `433.3 m` (`1,422 ft`) | `9.14 m` (`30 ft`) | `442.5 m` (`1,452 ft`) |

| Hop Segment | Distance | Min Terrain Clearance | Min 1st Fresnel ($F_1$) Clearance | 915 MHz Free-Space Path Loss (FSPL) |
| :--- | :--- | :--- | :--- | :--- |
| **Hop 1: Roscoe → 2-Hop Relay 1** | `2.79 km` (`1.73 mi`) | `13.0 m` (`43 ft`) | **`328%`** | `100.6 dB` |
| **Hop 2: 2-Hop Relay 1 → 2-Hop Relay 2** | `3.30 km` (`2.05 mi`) | `7.2 m` (`24 ft`) | **`69%`** | `102.1 dB` |
| **Hop 3: 2-Hop Relay 2 → Livingston Manor** | `1.88 km` (`1.17 mi`) | `10.3 m` (`34 ft`) | **`145%`** | `97.2 dB` |
| **Total 2-Hop Link** | **`7.98 km`** (`4.96 mi`, `+0.3%`) | `7.2 m` worst-case | **`69%`** worst-case | Max hop: `102.1 dB` |

### Explicit Candidate Relay Evaluation (Roscoe ↔ Livingston Manor)

![Candidate Terrain & Line-of-Sight Profiles](candidate_profiles.png)

| Candidate Site | Coordinates (Lat, Lon) | Ground Elev | Mount (AGL) | Leg 1 (Roscoe → C) | Leg 2 (C → Livingston Manor) | 1-Hop Verdict | Total Path |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Shandelee Ridge** | `41.880400, -74.889000` | `654.9 m` (`2,148 ft`) | `18.30 m` (`60 ft`) | CLEAR: `87%` F1 (`11.1 m`, `6.20 km`, `107.5 dB`) | BLOCKED (`-105.3 m`, `5.51 km`) | BLOCKED (`-105.3 m`) | `11.71 km` |
| **Ferndale Ridge** | `41.766500, -74.699700` | `440.8 m` (`1,446 ft`) | `18.30 m` (`60 ft`) | BLOCKED (`-254.6 m`, `25.64 km`) | BLOCKED (`-195.6 m`, `18.30 km`) | BLOCKED (`-254.6 m`) | `43.94 km` |
| **Willowemoc Ridge** | `41.905600, -74.677400` | `642.4 m` (`2,108 ft`) | `18.30 m` (`60 ft`) | BLOCKED (`-139.0 m`, `19.82 km`) | BLOCKED (`-107.9 m`, `12.52 km`) | BLOCKED (`-139.0 m`) | `32.34 km` |

### Explicit Candidate Sensitivity to Livingston Manor Repeater Height

| Livingston Manor Height | Shandelee Ridge | Ferndale Ridge | Willowemoc Ridge |
| :--- | :--- | :--- | :--- |
| **30 ft (9.14 m) at Livingston Manor** | Blocked (L1 OK, L2 blk; `-105.3 m`) | Blocked (L1 blk, L2 blk; `-254.6 m`) | Blocked (L1 blk, L2 blk; `-139.0 m`) |
| **33 ft (10.0 m) at Livingston Manor** | Blocked (L1 OK, L2 blk; `-104.9 m`) | Blocked (L1 blk, L2 blk; `-254.6 m`) | Blocked (L1 blk, L2 blk; `-139.0 m`) |
| **45 ft (13.7 m) at Livingston Manor** | Blocked (L1 OK, L2 blk; `-103.0 m`) | Blocked (L1 blk, L2 blk; `-254.6 m`) | Blocked (L1 blk, L2 blk; `-139.0 m`) |
| **60 ft (18.3 m) at Livingston Manor** | Blocked (L1 OK, L2 blk; `-100.7 m`) | Blocked (L1 blk, L2 blk; `-254.6 m`) | Blocked (L1 blk, L2 blk; `-139.0 m`) |
| **63 ft (19.14 m = 10m + 30ft) at Livingston Manor** | Blocked (L1 OK, L2 blk; `-100.3 m`) | Blocked (L1 blk, L2 blk; `-254.6 m`) | Blocked (L1 blk, L2 blk; `-139.0 m`) |
| **90 ft (27.4 m) at Livingston Manor** | Blocked (L1 OK, L2 blk; `-96.1 m`) | Blocked (L1 blk, L2 blk; `-254.6 m`) | Blocked (L1 blk, L2 blk; `-139.0 m`) |

### Explicit Candidate 2-Hop Pair Evaluation (Roscoe ↔ Livingston Manor)

| Relay 1 -> Relay 2 | Hop 1 (Roscoe → R1) | Hop 2 (R1 → R2) | Hop 3 (R2 → Livingston Manor) | Verdict | Total Path |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Shandelee Ridge** → **Ferndale Ridge** | CLEAR `87%` | BLK `-102.9 m` | BLK `-195.6 m` | Blocked (`-195.6 m`) | `44.67 km` |
| **Willowemoc Ridge** → **Shandelee Ridge** | BLK `-139.0 m` | BLK `-38.3 m` | BLK `-105.3 m` | Blocked (`-139.0 m`) | `43.10 km` |
| **Willowemoc Ridge** → **Ferndale Ridge** | BLK `-139.0 m` | BLK `-40.4 m` | BLK `-195.6 m` | Blocked (`-195.6 m`) | `53.67 km` |
| **Shandelee Ridge** → **Willowemoc Ridge** | CLEAR `87%` | BLK `-38.3 m` | BLK `-107.9 m` | Blocked (`-107.9 m`) | `36.50 km` |
| **Ferndale Ridge** → **Shandelee Ridge** | BLK `-254.6 m` | BLK `-102.9 m` | BLK `-105.3 m` | Blocked (`-254.6 m`) | `51.32 km` |
| **Ferndale Ridge** → **Willowemoc Ridge** | BLK `-254.6 m` | BLK `-40.4 m` | BLK `-107.9 m` | Blocked (`-254.6 m`) | `53.72 km` |

### Top Hybrid 2-Hop Solutions (1 Explicit Candidate + 1 Grid Relay, Roscoe ↔ Livingston Manor)

| Rank | Relay 1 | Relay 2 | Hop 1 $F_1$ | Hop 2 $F_1$ | Hop 3 $F_1$ | Worst-Case $F_1$ | Total Path |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `#1` | **Shandelee Ridge** | Grid (`41.91243, -74.81706`) | `87%` | `56%` | `363%` | **`56%`** (`9.6 m`) | `14.77 km` |
| `#2` | **Shandelee Ridge** | Grid (`41.91297, -74.81706`) | `87%` | `55%` | `361%` | **`55%`** (`9.4 m`) | `14.85 km` |
| `#3` | **Shandelee Ridge** | Grid (`41.91387, -74.81706`) | `87%` | `51%` | `266%` | **`51%`** (`8.8 m`) | `14.99 km` |
| `#4` | **Shandelee Ridge** | Grid (`41.91405, -74.81706`) | `87%` | `50%` | `247%` | **`50%`** (`8.6 m`) | `15.02 km` |
| `#5` | **Shandelee Ridge** | Grid (`41.91567, -74.81705`) | `87%` | `37%` | `87%` | **`37%`** (`6.4 m`) | `15.27 km` |
| `#6` | **Shandelee Ridge** | Grid (`41.91567, -74.81922`) | `87%` | `20%` | `234%` | **`20%`** (`3.5 m`) | `15.04 km` |
| `#7` | **Shandelee Ridge** | Grid (`41.91405, -74.81923`) | `87%` | `16%` | `272%` | **`16%`** (`2.8 m`) | `14.78 km` |
| `#8` | **Shandelee Ridge** | Grid (`41.91568, -74.82067`) | `87%` | `15%` | `292%` | **`15%`** (`2.6 m`) | `14.90 km` |
| `#9` | **Shandelee Ridge** | Grid (`41.91243, -74.81923`) | `87%` | `12%` | `335%` | **`12%`** (`2.5 m`) | `14.52 km` |
| `#10` | **Shandelee Ridge** | Grid (`41.91568, -74.82139`) | `87%` | `11%` | `292%` | **`11%`** (`1.9 m`) | `14.83 km` |

### Roscoe ↔ Livingston Manor 1-Hop Sensitivity to Livingston Manor Repeater Height (with `60 ft` Intermediate Relay)

| Livingston Manor Repeater Height | Visible from Roscoe | Visible from Livingston Manor | Viable 1-Hop Sites | Fresnel-Clear (`>= 60% F1`) | Best 1-Hop Relay (Lat, Lon) | Worst-Case $F_1$ (Min Clear) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **30 ft (9.14 m) at Livingston Manor** | `326` | `467` | `0` | `0` | *None* | — |
| **33 ft (10.0 m) at Livingston Manor** | `326` | `476` | `0` | `0` | *None* | — |
| **45 ft (13.7 m) at Livingston Manor** | `326` | `488` | `0` | `0` | *None* | — |
| **60 ft (18.3 m) at Livingston Manor** | `326` | `499` | `0` | `0` | *None* | — |
| **63 ft (19.14 m = 10m + 30ft) at Livingston Manor** | `326` | `500` | `0` | `0` | *None* | — |
| **90 ft (27.4 m) at Livingston Manor** | `326` | `516` | `0` | `0` | *None* | — |

### Top 10 Ranked 2-Relay Solutions (Roscoe ↔ Livingston Manor)

| Rank | Relay 1 (Lat, Lon) | Relay 1 Elev | Relay 2 (Lat, Lon) | Relay 2 Elev | Worst-Case $F_1$ Clear | Min Clear (m) | Total Path Length |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `#1` | `41.920621, -74.884330` | `606 m` (`1,988 ft`) | `41.905989, -74.849633` | `608 m` (`1,996 ft`) | **`69%`** | `7.2 m` | `7.98 km` (`4.96 mi`) |
| `#2` | `41.920618, -74.882160` | `601 m` (`1,973 ft`) | `41.905989, -74.849633` | `608 m` (`1,996 ft`) | **`64%`** | `6.6 m` | `7.98 km` (`4.96 mi`) |
| `#3` | `41.920614, -74.877818` | `579 m` (`1,900 ft`) | `41.912474, -74.849617` | `588 m` (`1,928 ft`) | **`74%`** | `9.3 m` | `8.00 km` (`4.97 mi`) |
| `#4` | `41.915753, -74.879998` | `657 m` (`2,155 ft`) | `41.905987, -74.847462` | `598 m` (`1,961 ft`) | **`63%`** | `7.5 m` | `8.00 km` (`4.97 mi`) |
| `#5` | `41.915753, -74.879998` | `657 m` (`2,155 ft`) | `41.905989, -74.849633` | `608 m` (`1,996 ft`) | **`122%`** | `10.3 m` | `8.01 km` (`4.98 mi`) |
| `#6` | `41.920616, -74.879989` | `594 m` (`1,950 ft`) | `41.912474, -74.849617` | `588 m` (`1,928 ft`) | **`74%`** | `9.3 m` | `8.01 km` (`4.98 mi`) |
| `#7` | `41.915751, -74.878551` | `655 m` (`2,149 ft`) | `41.904909, -74.849635` | `606 m` (`1,988 ft`) | **`72%`** | `7.0 m` | `8.01 km` (`4.98 mi`) |
| `#8` | `41.921155, -74.878541` | `574 m` (`1,885 ft`) | `41.913015, -74.849616` | `589 m` (`1,932 ft`) | **`85%`** | `9.8 m` | `8.02 km` (`4.98 mi`) |
| `#9` | `41.920618, -74.882160` | `601 m` (`1,973 ft`) | `41.912474, -74.849617` | `588 m` (`1,928 ft`) | **`74%`** | `9.3 m` | `8.02 km` (`4.98 mi`) |
| `#10` | `41.921159, -74.882159` | `588 m` (`1,930 ft`) | `41.913015, -74.849616` | `589 m` (`1,932 ft`) | **`134%`** | `11.7 m` | `8.03 km` (`4.99 mi`) |

## 3. Livingston Manor ↔ Liberty Link Analysis (`12.93 km` Direct)

- **Direct Distance**: `12.93 km` (`8.03 mi`)
- **Direct Line-of-Sight (`30 ft` at Livingston Manor → `33 ft` at Liberty)**: **BLOCKED BY TERRAIN** — Minimum terrain clearance is `-188.3 m` (`-618 ft`), Min $F_1$ ratio `-834%`.

### Optimal 2-Hop Repeater Solution (Livingston Manor ↔ Liberty, Solid Red Path)

| Node | Latitude, Longitude (WGS84) | UTM Zone 18N (E, N) | Ground Elevation | Mount Height (AGL) | Total Tip Elevation (ASL) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Livingston Manor** | `41.900375, -74.828218` | `E 514248.7, N 4638729.4` | `433.3 m` (`1,422 ft`) | `9.14 m` (`30 ft`) | `442.5 m` (`1,452 ft`) |
| **2-Hop Relay 1** | `41.859847, -74.793387` | `E 517148.7, N 4634236.1` | `625.4 m` (`2,052 ft`) | `18.3 m` (`60 ft`) | `643.7 m` (`2,112 ft`) |
| **2-Hop Relay 2** | `41.819238, -74.753783` | `E 520448.7, N 4629736.1` | `637.5 m` (`2,092 ft`) | `18.3 m` (`60 ft`) | `655.8 m` (`2,152 ft`) |
| **Liberty** | `41.801209, -74.746552` | `E 521055.2, N 4627736.1` | `457.8 m` (`1,502 ft`) | `10.00 m` (`33 ft`) | `467.8 m` (`1,535 ft`) |

| Hop Segment | Distance | Min Terrain Clearance | Min 1st Fresnel ($F_1$) Clearance | 915 MHz Free-Space Path Loss (FSPL) |
| :--- | :--- | :--- | :--- | :--- |
| **Hop 1: Livingston Manor → 2-Hop Relay 1** | `5.35 km` (`3.32 mi`) | `12.2 m` (`40 ft`) | **`77%`** | `106.2 dB` |
| **Hop 2: 2-Hop Relay 1 → 2-Hop Relay 2** | `5.58 km` (`3.47 mi`) | `11.9 m` (`39 ft`) | **`70%`** | `106.6 dB` |
| **Hop 3: 2-Hop Relay 2 → Liberty** | `2.09 km` (`1.30 mi`) | `11.2 m` (`37 ft`) | **`297%`** | `98.1 dB` |
| **Total 2-Hop Link** | **`13.02 km`** (`8.09 mi`, `+0.7%`) | `11.2 m` worst-case | **`70%`** worst-case | Max hop: `106.6 dB` |

### Explicit Candidate Relay Evaluation (Livingston Manor ↔ Liberty)

![Candidate Terrain & Line-of-Sight Profiles](candidate_profiles.png)

| Candidate Site | Coordinates (Lat, Lon) | Ground Elev | Mount (AGL) | Leg 1 (Livingston Manor → C) | Leg 2 (C → Liberty) | 1-Hop Verdict | Total Path |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Shandelee Ridge** | `41.880400, -74.889000` | `654.9 m` (`2,148 ft`) | `18.30 m` (`60 ft`) | BLOCKED (`-105.3 m`, `5.51 km`) | BLOCKED (`-137.1 m`, `14.74 km`) | BLOCKED (`-137.1 m`) | `20.25 km` |
| **Ferndale Ridge** | `41.766500, -74.699700` | `440.8 m` (`1,446 ft`) | `18.30 m` (`60 ft`) | BLOCKED (`-195.6 m`, `18.30 km`) | CLEAR: `61%` F1 (`5.0 m`, `5.48 km`, `106.4 dB`) | BLOCKED (`-195.6 m`) | `23.78 km` |
| **Willowemoc Ridge** | `41.905600, -74.677400` | `642.4 m` (`2,108 ft`) | `18.30 m` (`60 ft`) | BLOCKED (`-107.9 m`, `12.52 km`) | BLOCKED (`-116.5 m`, `12.93 km`) | BLOCKED (`-116.5 m`) | `25.46 km` |

### Explicit Candidate Sensitivity to Livingston Manor Repeater Height

| Livingston Manor Height | Shandelee Ridge | Ferndale Ridge | Willowemoc Ridge |
| :--- | :--- | :--- | :--- |
| **30 ft (9.14 m) at Livingston Manor** | Blocked (L1 blk, L2 blk; `-137.1 m`) | Blocked (L1 blk, L2 OK; `-195.6 m`) | Blocked (L1 blk, L2 blk; `-116.5 m`) |
| **33 ft (10.0 m) at Livingston Manor** | Blocked (L1 blk, L2 blk; `-137.1 m`) | Blocked (L1 blk, L2 OK; `-195.2 m`) | Blocked (L1 blk, L2 blk; `-116.5 m`) |
| **45 ft (13.7 m) at Livingston Manor** | Blocked (L1 blk, L2 blk; `-137.1 m`) | Blocked (L1 blk, L2 OK; `-193.3 m`) | Blocked (L1 blk, L2 blk; `-116.5 m`) |
| **60 ft (18.3 m) at Livingston Manor** | Blocked (L1 blk, L2 blk; `-137.1 m`) | Blocked (L1 blk, L2 OK; `-190.9 m`) | Blocked (L1 blk, L2 blk; `-116.5 m`) |
| **63 ft (19.14 m = 10m + 30ft) at Livingston Manor** | Blocked (L1 blk, L2 blk; `-137.1 m`) | Blocked (L1 blk, L2 OK; `-190.5 m`) | Blocked (L1 blk, L2 blk; `-116.5 m`) |
| **90 ft (27.4 m) at Livingston Manor** | Blocked (L1 blk, L2 blk; `-137.1 m`) | Blocked (L1 blk, L2 OK; `-186.2 m`) | Blocked (L1 blk, L2 blk; `-116.5 m`) |

### Explicit Candidate 2-Hop Pair Evaluation (Livingston Manor ↔ Liberty)

| Relay 1 -> Relay 2 | Hop 1 (Livingston Manor → R1) | Hop 2 (R1 → R2) | Hop 3 (R2 → Liberty) | Verdict | Total Path |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Shandelee Ridge** → **Ferndale Ridge** | BLK `-105.3 m` | BLK `-102.9 m` | CLEAR `61%` | Blocked (`-105.3 m`) | `31.16 km` |
| **Shandelee Ridge** → **Willowemoc Ridge** | BLK `-105.3 m` | BLK `-38.3 m` | BLK `-116.5 m` | Blocked (`-116.5 m`) | `36.22 km` |
| **Ferndale Ridge** → **Willowemoc Ridge** | BLK `-195.6 m` | BLK `-40.4 m` | BLK `-116.5 m` | Blocked (`-195.6 m`) | `46.79 km` |
| **Ferndale Ridge** → **Shandelee Ridge** | BLK `-195.6 m` | BLK `-102.9 m` | BLK `-137.1 m` | Blocked (`-195.6 m`) | `53.21 km` |
| **Willowemoc Ridge** → **Ferndale Ridge** | BLK `-107.9 m` | BLK `-40.4 m` | CLEAR `61%` | Blocked (`-107.9 m`) | `33.56 km` |
| **Willowemoc Ridge** → **Shandelee Ridge** | BLK `-107.9 m` | BLK `-38.3 m` | BLK `-137.1 m` | Blocked (`-137.1 m`) | `45.03 km` |

### Top Hybrid 2-Hop Solutions (1 Explicit Candidate + 1 Grid Relay, Livingston Manor ↔ Liberty)

| Rank | Relay 1 | Relay 2 | Hop 1 $F_1$ | Hop 2 $F_1$ | Hop 3 $F_1$ | Worst-Case $F_1$ | Total Path |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `#1` | Grid (`41.84411, -74.75802`) | **Ferndale Ridge** | `78%` | `58%` | `61%` | **`58%`** (`5.0 m`) | `23.90 km` |
| `#2` | Grid (`41.84249, -74.75803`) | **Ferndale Ridge** | `13%` | `14%` | `61%` | **`13%`** (`3.0 m`) | `23.88 km` |
| `#3` | Grid (`41.84085, -74.75153`) | **Ferndale Ridge** | `0%` | `63%` | `61%` | **`0%`** (`0.1 m`) | `23.96 km` |

### Livingston Manor ↔ Liberty 1-Hop Sensitivity to Livingston Manor Repeater Height (with `60 ft` Intermediate Relay)

| Livingston Manor Repeater Height | Visible from Livingston Manor | Visible from Liberty | Viable 1-Hop Sites | Fresnel-Clear (`>= 60% F1`) | Best 1-Hop Relay (Lat, Lon) | Worst-Case $F_1$ (Min Clear) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **30 ft (9.14 m) at Livingston Manor** | `434` | `241` | `0` | `0` | *None* | — |
| **33 ft (10.0 m) at Livingston Manor** | `436` | `241` | `0` | `0` | *None* | — |
| **45 ft (13.7 m) at Livingston Manor** | `453` | `241` | `0` | `0` | *None* | — |
| **60 ft (18.3 m) at Livingston Manor** | `476` | `241` | `0` | `0` | *None* | — |
| **63 ft (19.14 m = 10m + 30ft) at Livingston Manor** | `479` | `241` | `0` | `0` | *None* | — |
| **90 ft (27.4 m) at Livingston Manor** | `507` | `241` | `0` | `0` | *None* | — |

### Top 10 Ranked 2-Relay Solutions (Livingston Manor ↔ Liberty)

| Rank | Relay 1 (Lat, Lon) | Relay 1 Elev | Relay 2 (Lat, Lon) | Relay 2 Elev | Worst-Case $F_1$ Clear | Min Clear (m) | Total Path Length |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `#1` | `41.859847, -74.793387` | `625 m` (`2,052 ft`) | `41.819238, -74.753783` | `638 m` (`2,092 ft`) | **`70%`** | `11.2 m` | `13.02 km` (`8.09 mi`) |
| `#2` | `41.859847, -74.793387` | `625 m` (`2,052 ft`) | `41.813857, -74.764639` | `637 m` (`2,090 ft`) | **`77%`** | `9.5 m` | `13.04 km` (`8.10 mi`) |
| `#3` | `41.884214, -74.822235` | `607 m` (`1,992 ft`) | `41.819238, -74.753783` | `638 m` (`2,092 ft`) | **`62%`** | `11.2 m` | `13.13 km` (`8.16 mi`) |
| `#4` | `41.859847, -74.793387` | `625 m` (`2,052 ft`) | `41.821933, -74.750160` | `643 m` (`2,108 ft`) | **`60%`** | `11.4 m` | `13.20 km` (`8.20 mi`) |
| `#5` | `41.900417, -74.816162` | `555 m` (`1,822 ft`) | `41.814753, -74.762228` | `641 m` (`2,103 ft`) | **`60%`** | `7.7 m` | `13.50 km` (`8.39 mi`) |
| `#6` | `41.859847, -74.793387` | `625 m` (`2,052 ft`) | `41.813842, -74.757416` | `644 m` (`2,113 ft`) | **`58%`** | `8.8 m` | `12.93 km` (`8.04 mi`) |
| `#7` | `41.844106, -74.758024` | `614 m` (`2,015 ft`) | `41.766500, -74.699700` | `441 m` (`1,446 ft`) | **`58%`** | `5.0 m` | `23.90 km` (`14.85 mi`) |
| `#8` | `41.860387, -74.792662` | `616 m` (`2,021 ft`) | `41.814929, -74.760301` | `641 m` (`2,105 ft`) | **`51%`** | `3.4 m` | `12.95 km` (`8.05 mi`) |
| `#9` | `41.884214, -74.822235` | `607 m` (`1,992 ft`) | `41.813842, -74.757416` | `644 m` (`2,113 ft`) | **`48%`** | `8.5 m` | `13.02 km` (`8.09 mi`) |
| `#10` | `41.860387, -74.792662` | `616 m` (`2,021 ft`) | `41.814924, -74.758134` | `645 m` (`2,117 ft`) | **`47%`** | `3.2 m` | `12.94 km` (`8.04 mi`) |

## 4. Grid Resolution Scan Summary

| Link | Grid Step (m) | Candidate Grid Points | Visible from Node 1 | Visible from Node 2 | Valid 1-Hop Sites | 2-Hop Pairs Evaluated | Valid 2-Hop Solutions |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Roscoe ↔ Livingston Manor** | `500.0 m` | `228` | `38` | `46` | **`0`** | `1500` | **`74`** |
| **Roscoe ↔ Livingston Manor** | `300.0 m` | `589` | `84` | `118` | **`0`** | `1500` | **`38`** |
| **Roscoe ↔ Livingston Manor** | `180.0 m` | `1632` | `221` | `325` | **`0`** | `1500` | **`28`** |
| **Livingston Manor ↔ Liberty** | `500.0 m` | `468` | `36` | `23` | **`0`** | `714` | **`11`** |
| **Livingston Manor ↔ Liberty** | `300.0 m` | `1320` | `109` | `64` | **`0`** | `1500` | **`26`** |
| **Livingston Manor ↔ Liberty** | `180.0 m` | `3577` | `308` | `167` | **`0`** | `1500` | **`19`** |

## 5. Surrounding Terrain Features (USGS GeoNames)

### Mountain Summits & Peaks
- **Grants Hill**: `643 m` (`2,109 ft`) — `41.84342, -74.82155`
- **Baldy**: `467 m` (`1,531 ft`) — `41.76615, -74.96254`
- **East Hill**: `536 m` (`1,758 ft`) — `41.79795, -74.87890`
- **Gray Hill**: `662 m` (`2,171 ft`) — `41.91787, -74.80183`
- **Revonah Hill**: `650 m` (`2,133 ft`) — `41.81875, -74.76236`
- **Birch Ridge**: `422 m` (`1,386 ft`) — `41.73990, -74.91344`
- **Round Top**: `556 m` (`1,824 ft`) — `41.90037, -74.81627`
- **Swiss Hill**: `442 m` (`1,449 ft`) — `41.77370, -74.92961`
- **Hust Hill**: `587 m` (`1,925 ft`) — `41.81429, -74.94412`
- **Chuck Hill**: `616 m` (`2,022 ft`) — `41.79575, -74.77553`
- **Rattle Hill**: `788 m` (`2,585 ft`) — `41.97342, -74.76933`
- **Walnut Mountain**: `652 m` (`2,140 ft`) — `41.78750, -74.76933`
- **Hill 16**: `590 m` (`1,935 ft`) — `41.81981, -74.93233`
- **Slawson Mountain**: `760 m` (`2,495 ft`) — `41.91481, -74.65849`
- **Fulton Hill**: `391 m` (`1,282 ft`) — `41.73912, -74.96805`
- **Bald Mountain**: `702 m` (`2,303 ft`) — `41.90288, -74.72437`
- **Burnt Hill**: `703 m` (`2,307 ft`) — `41.96378, -74.85179`

### Populated Places & Towns
- **Kohlertown**: `41.77148, -74.94183`
- **Roscoe**: `41.93314, -74.91350`
- **Rockland**: `41.94537, -74.91294`
- **Hazel**: `41.92453, -74.87016`
- **Morsston**: `41.88426, -74.81044`
- **Anderson**: `41.90315, -74.70683`
- **Livingston Manor**: `41.90037, -74.82822`
- **Grooville**: `41.94259, -74.76738`
- **Divine Corners**: `41.79037, -74.66572`
- **Loomis**: `41.79731, -74.78572`
- **Youngsville**: `41.80842, -74.88627`
- **White Sulphur Springs**: `41.79759, -74.82683`
- **Loch Sheldrake**: `41.77009, -74.65710`
- **Parksville**: `41.85537, -74.75960`
- **Hurd Settlement**: `41.72759, -74.88239`
- **Jeffersonville**: `41.78092, -74.93378`
- **Cooks Falls**: `41.94787, -74.98044`
- **Craigie Clair**: `41.96426, -74.86627`
- **Kenoza Lake**: `41.73342, -74.94961`
- **Willowemoc**: `41.91898, -74.67238`
- **Deckertown**: `41.92509, -74.83266`
- **Hurleyville**: `41.73565, -74.67433`
- **Neversink**: `41.84731, -74.61905`
- **Bradley**: `41.82398, -74.67627`
- **Joscelyn**: `41.95370, -74.86044`
- **Ferndale**: `41.77398, -74.73849`
- **Cooley**: `41.87176, -74.70905`
- **Aden**: `41.86065, -74.67321`
- **Tennanah Lake**: `41.89509, -74.97655`
- **Debruce**: `41.91370, -74.72710`
- **Liberty**: `41.80120, -74.74655`
- **Swan Lake**: `41.75064, -74.77794`
- **Shandelee**: `41.87898, -74.87127`
- **Briscoe**: `41.76426, -74.87850`
- **Callicoon Center**: `41.83676, -74.94655`
- **Parkston**: `41.90453, -74.77294`


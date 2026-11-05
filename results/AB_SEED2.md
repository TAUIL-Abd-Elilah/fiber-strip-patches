# A/B seed 2: amendment 1 test

**Decision under `PREREG.md` amendment 1: "confirmed on seed 2".** With the strips as `verified_patches`, each held-out wrap lies on fewer fitted windings: purity B-A **+7.8 points** (paired bootstrap 95 % CI +5.7 to +10.1), 33 of 36 wraps up. Every guard passes.

**What it does not show:** the fit is still not on the sheet. M1 (within 2 voxels) is -0.5 points (CI -1.4 to +0.3), no gain on either seed, and near chance in both arms (`AB_SEED1.md`).

## Runs

| | Arm A | Arm B |
|---|---|---|
| Config | `configs/config_A_seed2.json` (frozen) | `configs/config_B_seed2.json` (frozen) |
| Optimizer seed | 2 | 2 |
| Patches loaded | 0 | 127 of 134 |
| Fiber collections | 144 | 144 |
| Exit | rc 0, 2216 s | rc 0, 3025 s |
| Fitted windings in band | 117 | 115 |

B ran first, then A, on 5 Nov 2026. Config and scorer hashes match `FREEZE.txt`. `tools/score_purity.py` was committed (14:08 UTC) before the first seed-2 fit started (18:49 UTC). Raw output: `ab_seed2.json`, `purity_seed2.json`.

## Amendment 1 bars

| Check | Bar | Seed 2 | Pass |
|---|---|---|---|
| Purity B2-A2 | >= +5 points, CI above 0 | +7.8 (CI +5.7 to +10.1); A 16.7 %, B 24.5 % | yes |
| Seed noise, abs purity A2-A1 | below half of B2-A2 (3.9) | A2-A1 +0.7 (CI -0.02 to +1.3) | yes |
| M1 B-A | >= -1 | -0.5 | yes |
| M3 exact share B-A | >= -1 | +0.9 | yes |
| M4 duplicate share B-A | <= +1 | -0.8 | yes |
| Same-winding share of adjacent wraps B-A | <= +1 | -0.1 | yes |

## Other measures, both seeds

| Measure | Seed 1 A / B | Seed 2 A / B |
|---|---|---|
| M1 within 2 voxels | 31.3 / 31.5 % | 31.5 / 31.0 % |
| M2 within 4 voxels | 60.4 / 60.3 % | 61.1 / 59.2 % |
| Covered nodes within 2 (6.6 % of nodes) | 35.6 / 41.3 % | 36.6 / 41.0 % |
| Uncovered nodes within 2 | 31.0 / 30.8 % | 31.1 / 30.3 % |
| M3 adjacent exact | 63.9 / 64.8 % | 64.0 / 64.9 % |
| M4 duplicate share | 3.6 / 2.9 % | 3.5 / 2.7 % |
| M5 winding hops inside wraps | 169,220 / 149,697 (-11.5 %) | 169,027 / 139,199 (-17.6 %) |
| Purity | 16.1 / 25.1 % | 16.7 / 24.5 % |

## Limits

- Same band (L2 z 3200-4200), wraps and patches as seed 1. Seed 2 replicates optimizer randomness only.
- Purity was chosen after seeing seed 1. Seed 2 is the only fit that played no part in choosing it.
- Purity counts only wrap nodes within 4 voxels of a fitted winding, about 60 % in both arms.
- This config has no tracks or winding store, so it is not the team's full recipe. Whether the effect survives with them is untested.
- A test on another band needs its own amendment first.

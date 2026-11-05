# fiber-strip-patches

Patch-ready 2D strips, about 1.15 mm wide, around human scaffold fibers of PHerc 0139, in villa's tifxyz patch format. `fit_spiral` loads them as `verified_patches` unchanged.

**Result, 5 Nov 2026, one band, two seeds:**

- **Surface accuracy: no measurable gain** (the pre-registered measure). Adding the strips moved held-out wrap nodes within 2 voxels by +0.1 points on seed 1 (CI -0.6 to +0.9; bar +5) and -0.5 on seed 2. `results/AB_SEED1.md`.
- **Winding purity: confirmed on seed 2** (the amendment-1 test, metric chosen after seed 1). Each held-out wrap lies on fewer fitted windings: +7.8 points (CI +5.7 to +10.1), 33 of 36 wraps up, all guards passing. `results/AB_SEED2.md`.

| | |
|---|---|
| Patches | 550 pieces, about 100.8 cm2, L2 z 2300-7300. `patches/` |
| Does it help a fit? | M1 **no measurable gain** on either seed. Winding hops inside wraps -11.5 % and -17.6 %, reported, no bar |
| Winding purity | **Confirmed on seed 2**: +7.8 points (CI +5.7 to +10.1). Seed 1 had +9.0, where the metric was found. Frozen by `PREREG.md` amendment 1 before the seed-2 fits. It does not show the fit is on the sheet |
| Baseline caveat | Both arms score near chance on M1: wrap nodes shifted 6 voxels still score 30.5 % in arm A against 31.3 %. This config has no tracks or winding store, so it is not the team's full recipe |

## Strip accuracy by band

Only on stretches where a human fiber already lies on a human wrap. The fit A/B ran only in L2 z 3200-4200, so it says nothing about the other bands.

| L2 z | Patches | cm2 | Within 2 voxels (CI) | Fibers scored | Off-sheet strips | Wrap coverage | Folder |
|---|---|---|---|---|---|---|---|
| 2300-3000 | 87 | 13.1 | 78.8 % (73.8-82.9) | 26 | 1 | 6.0 % | `0139_z2300-3000` |
| 3000-4400 | 133 | 32.4 | 87.0 % (81.6-89.6), z 3200-4200 only | 30 | 0 | 6.6 % | `0139_band` |
| 4400-5400 | 107 | 16.8 | 82.3 % (75.5-86.3) | 19 | 0 | 3.1 % | `0139_z4400-5400` |
| 5400-6400 | 106 | 19.5 | 73.7 % (68.7-80.0) | 26 | 0 | 4.2 % | `0139_z5400-6400` |
| 6400-7300 | 117 | 19.0 | 70.8 % (63.6-78.4) | 20 | 0 | 5.7 % | `0139_z6400-7300` |

Read these with care: most strips have no matched stretch. In z 3200-4200, 115 of 145 strips had none, and across all patch nodes 35.4 % are within 2 voxels of the nearest wrap (`results/KT1_RESULT.md`). Single pieces can be poor, down to 0 % on a matched stretch, and they are not removed: the filter never looks at the wraps. Per-strip numbers are in `results/bands/` and `results/kt1_report.json`.

Coverage failed our 20 % bar, which was set too high: about 14 % was the most possible at this fiber density. The project owner chose to continue.

The same method has prior art: the team's `anchored_strip_merge` prototype merged strips onto seed patches in Paris 4 `verified_patches` (August 2026). This repo adds a held-out test on another scroll and needs no seed patch.

## Use

Copy the patch folders you want into `verified_patches/` of a `fit_spiral` dataset on volume 20260102150214, level 2 (9.596 um). Each patch has `x,y,z.tif` (-1 = invalid), `mask.tif`, `expected_error.tif` and a `meta.json` with a `provenance` block (model, villa commit, fiber, parameters). Each band's `manifest.json` lists its patches. villa baf5e605 `load_patches` loaded the `0139_band` folder and two 20,000-step fits ran with rc 0. The other bands have not been loaded into a fit. We have not opened any of them in VC3D yet.

## Method

- **Strips:** `scrollprize/fiber_strip_small_v1`, villa 6f2024569 + #2163 on CPU, on human fibers with a controlled span in each band.
- **Filter:** drop columns with median `expected_error` over 2.0 voxels, clip to the band, drop pieces under 0.05 cm2. Nothing is filtered against the wraps.
- **Score:** 36 human wraps with known defects masked (`tools/kt1_masks.py`), the frozen October scorer, rules fixed in `results/KT1_SCORING_RULES.md` before any comparison. Later bands: `tools/stage2/score_band_window.py`.
- **A/B:** `PREREG.md` and `FREEZE.txt` were pushed before any 20,000-step fit. Amendments go at the end of `PREREG.md`.

## Credits

bruniss (sheet_strip model and `infer.py`, villa #2110); slchicoineau-creator and Baz248 (#2163 Windows port); the Vesuvius Challenge team's `anchored_strip_merge` prototype; the PHerc 0139 annotation team for the 620 scaffold fibers and the 37 wraps; ChaseHendrick (#2167 defect masks), nerln (#1547) and damsolanke (w041/w042 note); skuzbucket1 (geometry_coverage); Ahggggg (clean-sheets lineage of the patch scorer).

## License

Code MIT. `patches/` and `results/` CC BY-NC 4.0 (`LICENSE-DATA.md`). Third-party code: `NOTICE.md`.

Author: TAUIL Abd Elilah. Developed with AI assistance under my direction. The checks named here were separate AI agents, not other people.

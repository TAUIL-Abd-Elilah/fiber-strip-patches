# fiber-strip-patches

Patch-ready 2D strips, about 1.15 mm wide, around human scaffold fibers of PHerc 0139, in villa's tifxyz patch format. `fit_spiral` loads them as `verified_patches` unchanged. This is v0: one band, the gate result, and a pre-registered fit A/B that has not run yet.

**Status, 4 Nov 2026**

| | |
|---|---|
| Patches | 133 from 145 strips, 32.4 cm2 in L2 z 3000-4400 (22.3 cm2 in z 3200-4200). `patches/0139_band/` |
| Accuracy where a human fiber lies on a human wrap | 87.0 % of nodes within 2 voxels (CI 81.6-89.6, 30 fibers); H 89.8 %, V 73.1 %; 0 of 30 strips off the sheet |
| Coverage of the band's wrap area | **6.6 %. This failed our 20 % bar**, which was set too high: about 14 % was the most possible at this fiber density. The project owner chose to continue |
| Does it help a fit? | **Not known yet.** Four configs are ready, two run first. `PREREG.md` fixes the bars |

Read the 87 % with care: it counts only stretches where the fiber already lies on a wrap, and 115 of 145 strips had no such stretch. Across all patch nodes, 35.4 % are within 2 voxels of the nearest wrap, against 8.6-11.1 % for the same nodes shifted 6 voxels (`results/KT1_RESULT.md`). That denominator includes nodes outside the radius the wraps cover.

The same method has prior art: the team's `anchored_strip_merge` prototype merged strips onto seed patches in Paris 4 `verified_patches` (August 2026). This repo adds a held-out test on another scroll and needs no seed patch.

## Use

Copy the folders in `patches/0139_band/` into `verified_patches/` of a `fit_spiral` dataset on volume 20260102150214, level 2 (9.596 um). Each patch has `x,y,z.tif` (-1 = invalid), `mask.tif`, `expected_error.tif` and a `meta.json` with a `provenance` block (model, villa commit, fiber, parameters); `manifest.json` lists them all. villa baf5e605 `load_patches` loads all 133. A 20-step CPU fit ran with rc 0. We have not opened them in VC3D yet.

## Method

- **Strips:** `scrollprize/fiber_strip_small_v1`, villa 6f2024569 + #2163 on CPU, on every human fiber with a controlled span in L2 z 3000-4400. 146 pieces, 145 finished; N0023 is too short to survive the 75-voxel trim.
- **Filter:** drop columns with median `expected_error` over 2.0 voxels (fixed from October's strips, dropped none here), clip to the band, drop pieces under 0.05 cm2. Nothing is filtered against the wraps.
- **Score:** 36 human wraps with known defects masked (`tools/kt1_masks.py`), the frozen October scorer, rules fixed in `results/KT1_SCORING_RULES.md` before any comparison.

## Credits

bruniss (sheet_strip model and `infer.py`, villa #2110); slchicoineau-creator and Baz248 (#2163 Windows port); the Vesuvius Challenge team's `anchored_strip_merge` prototype; the PHerc 0139 annotation team for the 620 scaffold fibers and the 37 wraps; ChaseHendrick (#2167 defect masks), nerln (#1547) and damsolanke (w041/w042 note); skuzbucket1 (geometry_coverage); Ahggggg (clean-sheets lineage of the patch scorer).

## License

Code MIT. `patches/` and `results/` CC BY-NC 4.0 (`LICENSE-DATA.md`). Third-party code: `NOTICE.md`.

Author: TAUIL Abd Elilah. Developed with AI assistance under my direction. The checks named here were separate AI agents, not other people.

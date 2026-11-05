# Pre-registration: strips as patches in `fit_spiral`, PHerc 0139 band

Frozen before any 20,000-step fit of this A/B started. Sha256 of this file and of every input are in `FREEZE.txt`, committed with it. Changes after this commit go in a dated amendment at the end; nothing above it is edited.

## 1. Question

Do 2D strips from the sheet-strip model, grown around human fibers that the fit already uses, improve `fit_spiral` against human wrap segments it never sees?

## 2. Known before this was written

One bar of the gate before this A/B failed and was overridden by the project owner. Details in `results/KT1_RESULT.md`:

- Strip quality on fiber stretches lying on a wrap: 87.0 % of nodes within 2 voxels (CI 81.6-89.6, 30 fibers; H 89.8 %, V 73.1 %), 0 of 30 strips off the sheet. 115 of 145 strips had no matched stretch.
- **Coverage failed:** strips cover 6.6 % of band wrap area against a 20 % bar. The most the bar could have reached at this fiber density is about 14 %, so the bar was set wrongly. Arm B therefore adds patches on only a small share of the surface it is scored on, and M1 below may not reach its bar for that reason alone.
- Precedent: 13 machine patches on PHerc 0813 gave +3.5 points (CI +0.9 to +5.8), below the same +5 bar (https://github.com/TAUIL-Abd-Elilah/spiral-patches-ab).

The strips, patches and fits use no wrap. Wraps were compared with strips before this freeze, for the gate. No fit of this A/B has been compared with a wrap. Only a 20-step smoke fit was scored, to test the scorer; that fit is meaningless as a result.

## 3. Arms

Volume PHerc0139 20260102150214, level 2 (9.596 um). Fit ROI L2 z 3200-4200. villa baf5e605, unchanged. 20,000 steps. No tracks, no winding store, `dense_spacing_mode grad_mag`. Configs in `configs/`.

- **Arm A:** umbilicus + 144 clipped human fibers + Lasagna normals and grad_mag (`input_disable_patches true`).
- **Arm B:** A + the 133 patches in `patches/0139_band/` (the fit's ROI test keeps 127).

The configs differ only in `input_disable_patches` and `patch_uuid_filter_regex`; seed-2 files differ only in `optimizer_random_seed`. Villa's default winding limits apply (`shell_outer_winding_idx` 130). The volume is marked superseded by 20260930100252 (remask, same voxel frame); every input lives on 20260102150214, so the A/B stays on it.

Order: A seed 1, B seed 1. Seed 2 (B then A) runs only if seed 1 gives B-A M1 >= +2 points, because GPU time is shared.

## 4. Truth and metrics

Truth: 36 human wraps (w023-w059 without w046) on the same volume, clipped to L2 z 3200-4200. Masks, fixed in `tools/kt1_masks.py`: w042 where L0 z is in 15,616-17,152 (villa #1547); w034-w037 inside the sector where w035 is absent (villa #2167), per 100-slice bin from w035's own coverage, widened 5 degrees, which agrees with the published extent (`results/kt1_masks.json`). Scored nodes: z in [3220, 4180). Wraps are never inputs. Scorer: `tools/score_band.py`.

| Metric | Definition | Bar |
|---|---|---|
| **M1 (primary)** | share of wrap nodes within 2 voxels of a fitted winding surface | B-A >= +5 points and paired bootstrap 95 % CI over wraps above 0, seed 1; seed 2 same sign if run |
| M2 | same, within 4 voxels | reported |
| M3 | adjacent-pair exactness: consecutive wraps on consecutive fitted windings | B not below A by more than 1 point; reported with same-winding share |
| M4 | duplicate-sheet share (skuzbucket1's geometry_coverage, as in `score_ab.py`) | B-A <= +1 point |
| M5 | winding hops inside wraps | reported |
| M6 | cross-sections at L2 z 3400, 3700, 4000 over CT, both arms and wraps | at least one cut where B stays on the sheet and A hops, or a plain "no visible difference" |
| M1-c | M1 on wrap nodes covered by a patch vs not covered (strict rule of `results/KT1_SCORING_RULES.md`) | reported, not gating |

M1-c is added because of the coverage failure: it separates a local effect from one that reaches the rest of the surface. It does not replace M1.

Wraps are correlated (many were seeded from neighbours), so bootstrap is by wrap, not by node. Known limit: wraps sit in a limited radius range, so the outer and inner parts of the fit are unscored.

## 5. Decision

- M1 >= +5 points with CI above 0, M3 and M4 inside their bars: **"strips help"**.
- M1 between +2 and +5 with CI above 0: **"small real gain, below the bar"**.
- Otherwise: **"no measurable gain"**, reported as the headline with the same prominence.

Validity: each fit must end rc 0 with 144 fibers loaded (arm B: patches fitted, arm A: none). A failed fit is rerun once with the same config and reported. Strip dumps for other scrolls go ahead whatever this A/B shows, but their README states this result.

## 6. Disclosure

Developed with AI assistance under my direction. The checks of this work were separate AI agents, not other people.

---

## Amendment 1, 5 Nov 2026

Written after seed 1 was scored and before any seed-2 fit started. The text above this line is unchanged: `git show 1d0dc7c:PREREG.md | sha256sum` gives the hash in `FREEZE.txt`.

**Decision under section 5, final for M1:** "no measurable gain". B-A M1 +0.1 points (CI -0.6 to +0.9). Seed 2 was not earned by the rule in section 3. Details in `results/AB_SEED1.md`.

**Why a further test.** Two things were seen only after scoring, so seed 1 cannot support either as a claim:

1. M1 sits near chance in both arms. Shifting the wrap nodes 6 voxels along their normal lowers arm A only from 31.3 % to 30.5 %, and arm B from 31.5 % to 29.5 %.
2. Winding purity moved. Purity of a wrap is `modal_share` in the `score_band.py` output: of its nodes within 4 voxels of a fitted winding, the share on its most common winding. Mean over 36 wraps: A 16.1 %, B 25.1 %, B-A +9.0 points (CI +6.6 to +11.6), 35 of 36 wraps up.

**Question for seed 2:** does B keep each wrap on fewer fitted windings than A, on a fit that played no part in choosing this metric?

**Runs.** The frozen `configs/config_B_seed2.json` and `configs/config_A_seed2.json`, B then A, overriding only the seed-2 condition of section 3. Scored by the frozen `tools/score_band.py`, then `tools/score_purity.py` (added with this amendment), which reads that JSON and does no geometry.

**Bars, seed 2 only:**

| Check | Bar |
|---|---|
| Purity B2-A2 | >= +5 points, paired bootstrap 95 % CI by wrap above 0 |
| Seed noise | absolute purity A2-A1 below half of B2-A2 |
| M1 B-A | >= -1 point |
| M3 exact share B-A | >= -1 point |
| M4 duplicate share B-A | <= +1 point |
| Same-winding share of adjacent wraps B-A | <= +1 point, so a collapse of wraps onto one winding cannot pass |

**Words.** All pass: "confirmed on seed 2". Purity +2 to +5 with CI above 0 and the rest passing: "smaller, below the bar". Otherwise: "not confirmed", as the headline with the same prominence.

**Limits, stated now.** Same band, same wraps, same patches: seed 2 replicates optimizer randomness only. The metric was chosen after seeing seed 1. Purity is measured only on nodes within 4 voxels of a winding, about 60 % in both arms. Even if confirmed, this does not show the fit is on the sheet: M1 stays the measure of that, and it did not move. A test on another band would need its own amendment first.

# Seed 1 of the PHerc 0139 band A/B

Fits: A1 and B1, 20,000 steps, about 50 minutes each on an RTX 3090. Both rc 0 with 144 fibers loaded; arm A fitted 0 patches, arm B 127. The validity rule of `PREREG.md` section 5 is met.

## Pre-registered result: no measurable gain

| Metric | A | B | B-A | Bar | |
|---|---|---|---|---|---|
| **M1, within 2 voxels** | 31.3 % | 31.5 % | **+0.1 (CI -0.6 to +0.9)** | >= +5, CI above 0 | **fail** |
| M2, within 4 voxels | 60.4 % | 60.3 % | -0.1 (CI -1.8 to +1.3) | reported | |
| M3, adjacent wraps on consecutive windings | 63.9 % | 64.8 % | +0.9 | not below -1 | pass |
| M3, same-winding share | 17.9 % | 17.5 % | -0.4 | reported | |
| M4, duplicate-sheet share | 3.6 % | 2.9 % | -0.6 | <= +1 | pass |
| M5, winding hops | 169,220 | 149,697 | -11.5 % | reported | |
| M1-c, covered nodes (6.6 %) | 35.6 % | 41.3 % | +5.7 | reported | |
| M1-c, uncovered nodes (93.4 %) | 31.0 % | 30.8 % | -0.3 | reported | |
| M6, cross-sections | `figures/` | | | | not judged yet |

The patches help where they are and do not improve M1 on the rest of the surface. With 6.6 % of nodes covered, covered nodes alone could add at most +4.6 points, so the +5 bar could not be reached without an effect elsewhere. `PREREG.md` section 2 warned of this.

## Post hoc, not a result

None of this was pre-registered. CIs here are by wrap, computed after seeing the data.

**M1 is near chance in both arms** (`ab_diag_seed1.json`, every 16th wrap node). A surface unrelated to the sheet would score about the same.

| Sample | A within 2 | B within 2 |
|---|---|---|
| Wrap nodes | 31.3 % | 31.5 % |
| Wrap nodes shifted +6 / -6 voxels along their normal | 30.5 / 30.5 % | 29.7 / 29.3 % |
| Human fiber points (fit inputs) | 54.1 % | 56.8 % |
| Strip patch nodes | 40.9 % | 76.5 % |

Fibers score well above chance, so the frames are right. B follows its patches. Away from its inputs, neither fit sits on the sheet at the 2-voxel level. This config has no tracks and no winding store (`PREREG.md` section 3), so it is not the team's full recipe, and this says nothing about fits made with those inputs.

**Wraps stay on fewer windings in B.** Purity (`modal_share`, see `PREREG.md` amendment 1): A 16.1 %, B 25.1 %, B-A +9.0 points (CI +6.6 to +11.6), 35 of 36 wraps up. A CI that resamples blocks of 4 neighbouring wraps is +5.1 to +13.6. The gain rises with a wrap's patch coverage (Spearman 0.50). A median wrap still touches 16 distinct windings in both arms. Other post hoc numbers: covered-node gain CI +1.3 to +9.6; hops per node -0.19 points (CI -0.34 to -0.05).

Seed noise is unknown until a second seed runs, so this may not hold. Amendment 1 freezes the test.

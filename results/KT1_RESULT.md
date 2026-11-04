# KT1 result, 4 Nov 2026 (rules: KT1_SCORING_RULES.md, fixed before any comparison)

**FAIL on one bar: wrap coverage 6.6 % against 20 %.** All other bars pass.

| Bar | Needed | Result | State |
|---|---|---|---|
| Strip nodes within 2 sv of the matched wrap (frozen October scorer) | >= 70 % | 87.0 % (fiber bootstrap CI 81.6-89.6), 30 fibers, 127,289 nodes | pass |
| Strips with median offset > 6 sv | <= 15 % | 0 of 30 | pass |
| Patch area in band | >= 3 cm2 | 22.3 cm2 (127 patches; 133 / 32.4 cm2 in the z 3000-4400 clip) | pass |
| Wrap area covered, strict lateral rule | >= 20 % | 6.6 % (loose 3D radius 18.3 %) | **FAIL** |
| villa load_patches + arm B smoke fit | runs | 133 loaded; 127 fitted, 144 fibers, 20 steps, rc 0, 328 s | pass |

Inference: 145 of 146 pieces, DONE rc=1, the only failure N0023 (97 sv, under the 150 sv trim minimum, allowed by the rules).

## The bar could not have passed, and that was my planning error
The band's wraps total 247 cm2 of nodes. 22.3 cm2 of 1.15 mm wide strips, even adding the 30 sv margin each side and
assuming every strip sits on a wrap, reaches about 34 cm2 = 14 %. So the plan's 20 % was out of reach for the fiber density
on this scroll, whatever the strip quality. The failure still has content: arm B adds patches on only a small share of the
surface M1 scores, which makes a +5 pp M1 gain less likely.

## Correction to my interim report
I told the user unconditional M7 (35.4 %) was about chance (33 %). That chance figure was an analytic guess and it was wrong.
Measured (post hoc, gates nothing, `score/kt1_controls.json`):

| Nodes | within 2 sv of nearest wrap |
|---|---|
| Patch nodes | 35.4 % (H 48.2, V 17.5) |
| Same nodes shifted radially +3 / -3 sv | 16.7 / 21.4 % |
| Same nodes shifted radially +6 / -6 sv | 8.6 / 11.1 % |
| Human fiber samples | 26.1 % (H 34.5, V 14.3) |

So the patches are about 3-4 times the half-pitch shifted control. They are not at chance, and on this measure they are no
worse than the human fibers they came from. The denominator includes nodes outside the wrap stack (radius outside w023-w059:
V median offset 26.6 sv), which is why the share looks low. Node sets differ between patches and fibers, so the fiber
comparison is indicative only. Wraps remain usable truth, on 30 fibers.

## Weak points
- V is weaker than H on the frozen measure: 73.1 % (20 fibers) vs 89.8 % (10 fibers).
- The 87 % is conditional on fibers lying on a wrap; 30 of 144 band fibers do.
- 115 of 145 strips had no matched stretch, so they are unscored by the frozen measure.

## Plan consequence
Section 4 says FAIL = stop stage 1, publish band strips + quality map, C19 headline. C19 was killed the same day (KT2_REPORT.md).
Decision on a bar override belongs to the user. GPU job files are not sent until then.

# KT1 scoring rules (fixed 4 Nov 2026 ~18:00 machine clock, before any band strip was compared with any wrap)

Bars are the ones in NOVEMBER_TARGET_v2 section 4. This file fixes how each is measured, including where the plan
left a choice. Nothing here changes after the first band score. Code: `C:/VesuviusTemp/nov_strips/kt1_masks.py`,
`kt1_score.py`.

## Truth set
- The wrap tifxyz on volume 20260102150214 (`C:/VesuviusTemp/strips/score/data/segments`), never a fit input.
- Clipped to L2 z [3200, 4200) = L0 z [12800, 16800). The title segment is not a wrap and is excluded.
- Whole wrap excluded: w046 (villa #1547: 81.5 % bit-identical to w045).
- w042 masked where L0 z in [15616, 17152] (#1547 comment: on w041's sheet). w041 is kept.
- #2167 sector: the plan left the bounds open. Rule: per 100-slice L2 z bin, the sector is the largest circular arc
  (1 degree bins, angle atan2(y - y_u, x - x_u) about the band umbilicus) where w035 has no valid node, widened by 5
  degrees each side; w034, w035, w036 and w037 are masked inside it. Derived from w035's own coverage, no CT, no strip.
  Sanity check against Chase's published extent (start 327-5, end 71-85 degrees, median width 98): written to
  `kt1_masks.json`. A large disagreement stops the run for review; it does not get tuned.
- The masks are applied to copies under `C:/VesuviusTemp/nov_strips/score/segments_masked`, never in place.

## Measures
1. **M7 within-2 (bar >= 70 %):** the frozen October scorer `score_strips.py` (FREEZE v3.2, unchanged), `match
   --analysis secondary` over all 620 fibers against the masked wraps, then `score` on all band strips; the pooled
   `accuracy.all.strip` share of nodes within 2 sv. Stretches are selected by fiber-wrap proximity, not by strips, as in
   October (84 %), so the number is comparable with it. It is a conditional number (only fiber stretches on a wrap);
   the report says so.
2. **M7 off-sheet (bar <= 15 %):** share of scored strips whose per-strip **median** |normal offset| to the matched wrap
   exceeds 6 sv. Same entries as measure 1. Strips with fewer than 25 scored nodes are not counted and the number
   dropped is reported.
3. **Strip area (bar >= 3 cm2):** patches from `strips2patches.py` on the November strips only (cap 2.0 sv, min area
   0.05 cm2, trim as run), valid quads with z in [3200, 4200), 20 sv2 per quad at 9.596 um. October patches do not count
   (KT1_CHECK P3: wrap-selected).
4. **Wrap coverage (bar >= 20 %):** the plan says "within 30 vox laterally of a strip". Lateral is taken literally: a
   masked wrap node is covered when a patch node within 30 sv of it (3D) has that same wrap as its nearest wrap and lies
   within 6 sv of it along the wrap normal (half the about 12 sv pitch). A plain 3D radius would also count about 2 wraps
   each side and is reported only as a loose number; it does not decide the bar.

## Reported, not gating
- Unconditional M7: every patch node in the band, normal distance to the nearest wrap, share within 2 sv, with the chance
  level for a random offset at the local pitch stated next to it. This is the honest check on measure 1's selection.
- H and V separately; strips that failed or came out empty (N0023 and N0022 are known; rc=1 on DONE is accepted when
  `failed_pieces` holds only pieces under 150 sv, because `infer.py --trim 75` cannot leave anything on them).

## Decision
PASS = villa's loader accepts the November patches, an arm B smoke fit runs on them, and bars 1-4 all hold.
FAIL on any = stop stage 1, publish band strips + quality map, make C19 the headline (plan section 4). A near miss is a
FAIL unless the user decides otherwise; I report the number and do not move a bar.

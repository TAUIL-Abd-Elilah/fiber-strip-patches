# A/B band 2: amendment 2 test

**Decision under `PREREG.md` amendment 2: "not replicated on band 2".**

Purity still rose with the strips, but by less than the bar and with a guard failing:

- **Purity B-A: +3.9 points** (paired bootstrap 95 % CI +2.1 to +5.9), 28 of 36 wraps up. This is below the +5 bar.
- **M3 guard failed:** adjacent wraps on consecutive windings fell by 1.7 points, past the -1 limit.

Because the guard failed, the in-between wording ("smaller on band 2, below the bar") does not apply either.

**M1 again shows no gain:** -0.8 points (CI -1.6 to -0.1). That is a small loss, inside the -1 guard.

## Runs

| | Arm A | Arm B |
|---|---|---|
| Config | `configs/band2/config_A.json` (frozen) | `configs/band2/config_B.json` (frozen) |
| Optimizer seed | 1 | 1 |
| Patches loaded | 0 | 107 of 107 |
| Fiber collections | 131 | 131 |
| Exit | rc 0, 1116 s | rc 0, 1473 s |
| Fitted windings in band | 120 | 120 |

B ran first, then A, on 6 Nov 2026. Both fits reached step 19,800 and saved their final checkpoint. They were shorter than the band 1 fits because the band holds fewer inputs. The scorer and config hashes match `FREEZE_B2.txt`. Raw output: `ab_band2.json`, `purity_band2.json`.

## Amendment 2 bars

| Check | Bar | Band 2 | Pass |
|---|---|---|---|
| Purity B-A | >= +5 points, CI above 0 | +3.9 (CI +2.1 to +5.9); A 11.7 %, B 15.6 % | no |
| M1 B-A | >= -1 | -0.8 | yes |
| M3 exact share B-A | >= -1 | -1.7 | **no** |
| M4 duplicate share B-A | <= +1 | -0.3 | yes |
| Same-winding share of adjacent wraps B-A | <= +1 | +0.7 | yes |

## Other measures, against band 1

| Measure | Band 1 seed 1 A / B | Band 1 seed 2 A / B | Band 2 A / B |
|---|---|---|---|
| Patch coverage of wrap nodes | 6.6 % | 6.6 % | 3.1 % |
| M1 within 2 voxels | 31.3 / 31.5 % | 31.5 / 31.0 % | 30.6 / 29.9 % |
| M2 within 4 voxels | 60.4 / 60.3 % | 61.1 / 59.2 % | 60.3 / 58.7 % |
| Covered nodes within 2 | 35.6 / 41.3 % | 36.6 / 41.0 % | 39.2 / 38.5 % |
| Uncovered nodes within 2 | 31.0 / 30.8 % | 31.1 / 30.3 % | 30.4 / 29.6 % |
| M3 adjacent exact | 63.9 / 64.8 % | 64.0 / 64.9 % | 67.3 / 65.6 % |
| M4 duplicate share | 3.6 / 2.9 % | 3.5 / 2.7 % | 2.3 / 2.0 % |
| M5 winding hops inside wraps | 169,220 / 149,697 (-11.5 %) | 169,027 / 139,199 (-17.6 %) | 94,586 / 98,099 (+3.7 %) |
| Purity | 16.1 / 25.1 % | 16.7 / 24.5 % | 11.7 / 15.6 % |

On band 1 the strips helped in three ways; on band 2 none of them held:

- **Covered nodes:** band 1 gained 5 to 6 points near the strips; band 2 lost 0.7.
- **Winding hops:** band 1 had 12 to 18 % fewer; band 2 had 3.7 % more.
- **M3:** the band 1 gain reversed.

Purity is the only band 1 measure that kept its direction, and it fell by about half.

## Reading

The purity gain seen on band 1 does not carry over to band 2 under the pre-registered bars. Two explanations fit the data, and this run cannot tell them apart:

- **Coverage:** half the coverage gave half the purity gain, consistent with band 1's coverage relation.
- **Over-fitting:** the band 1 gain was partly tuned to that band.

The covered-node and hop measures reversing on band 2 favours the second explanation more than the first.

With the strips as they are, this config does not make a better fit on a second band. This line is closed for the strips as `verified_patches`.

## Limits

- One seed. Band 1's seed noise on purity in arm A was 0.7 points.
- The same 36 wraps, on a different stretch.
- Purity was chosen after seeing band 1, seed 1.
- The config has no tracks or winding store, so it is not the team's full recipe.

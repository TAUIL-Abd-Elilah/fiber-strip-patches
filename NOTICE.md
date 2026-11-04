# Third-party code

`tools/strips2patches.py` copies `trim_ends`, `orient_decisions`, `stitch` and `stitch_values` from `sheet_strip/infer.py` of ScrollPrize/villa (https://github.com/ScrollPrize/villa) at 6f2024569. `tools/kt1_score.py` imports the frozen `score_strips.py` from https://github.com/TAUIL-Abd-Elilah/fiber-strips-beyond-paris4, and `tools/score_band.py` imports `score_ab.py` from https://github.com/TAUIL-Abd-Elilah/spiral-patches-ab. The fits run villa's `spiral-fitting/fit_spiral.py` unchanged at baf5e605bb42a3d55a62b7c5c728e0908137225c, with the `vc_spiral` native modules built from villa's own `cpp/` sources.

villa is MIT licensed, Copyright (c) 2024 Vesuvius Challenge. Its license text applies to those parts and is the same as `LICENSE` here apart from the copyright line.

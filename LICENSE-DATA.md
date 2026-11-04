# Data license: CC BY-NC 4.0

The code here is MIT (see `LICENSE`). `patches/` and `results/` are not code. They derive from Vesuvius Challenge open data and human fiber annotations and are released under **Creative Commons Attribution-NonCommercial 4.0 International**: https://creativecommons.org/licenses/by-nc/4.0/

## Attribution

- **Scan, wrap segments, Lasagna predictions, umbilicus:** Vesuvius Challenge open data (`s3://vesuvius-challenge-open-data`), CC BY-NC 4.0. Volume: PHerc0139 20260102150214 (2.399 um).
- **Human fiber annotations:** the Vesuvius Challenge annotators whose files carry the initials lt, kb and dj (https://dl.ash2txt.org/other/annotators/0139_fibers/). The folder carries no license file. We treat derived data as CC BY-NC 4.0 because every file names a CC BY-NC 4.0 source volume and the open-data schema says derived artifacts follow the license of their volume. This is our reading, not a grant.
- **Strip model:** `scrollprize/fiber_strip_small_v1` by Sean Johnson (bruniss), villa PR #2110. The checkpoint carries no license file and is not copied here.

## Changes

We made these files. The patches are predictions of `fiber_strip_small_v1` run on pieces of the human fibers, then filtered and clipped by `tools/strips2patches.py`. The result files are computed from them. No CT volume, raw fiber JSON, wrap mesh, ink image or model weight is included.

We add no restriction beyond CC BY-NC 4.0.

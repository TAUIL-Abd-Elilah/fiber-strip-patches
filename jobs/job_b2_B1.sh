#!/bin/bash
# One 20,000-step fit of the PHerc 0139 band A/B (arm B, seed 1, band 2 z 4400-5400, PREREG amendment 2). Writes logs/fit_b2B1.done also on a crash.
set -u
D=C:/VesuviusTemp/nov_strips
C:/Users/PC/miniconda3/envs/vesuvius/python.exe -I "$D/fit_nov_b2.py" B 1
rc=$?
[ -f "$D/logs/fit_b2B1.done" ] || echo "rc=$rc launcher" > "$D/logs/fit_b2B1.done"
exit $rc

#!/bin/bash
# One 20,000-step fit of the PHerc 0139 band A/B (arm B, seed 2). Writes logs/fit_novB2.done also on a crash.
set -u
D=C:/VesuviusTemp/nov_strips
C:/Users/PC/miniconda3/envs/vesuvius/python.exe -I "$D/fit_nov.py" B 2
rc=$?
[ -f "$D/logs/fit_novB2.done" ] || echo "rc=$rc launcher" > "$D/logs/fit_novB2.done"
exit $rc

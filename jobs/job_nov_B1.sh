#!/bin/bash
# One 20,000-step fit of the PHerc 0139 band A/B (arm B, seed 1). Writes logs/fit_novB1.done also on a crash.
set -u
D=C:/VesuviusTemp/nov_strips
C:/Users/PC/miniconda3/envs/vesuvius/python.exe -I "$D/fit_nov.py" B 1
rc=$?
[ -f "$D/logs/fit_novB1.done" ] || echo "rc=$rc launcher" > "$D/logs/fit_novB1.done"
exit $rc

#!/bin/bash
# One 20,000-step fit of the PHerc 0139 band A/B (arm A, seed 1). Writes logs/fit_novA1.done also on a crash.
set -u
D=C:/VesuviusTemp/nov_strips
C:/Users/PC/miniconda3/envs/vesuvius/python.exe -I "$D/fit_nov.py" A 1
rc=$?
[ -f "$D/logs/fit_novA1.done" ] || echo "rc=$rc launcher" > "$D/logs/fit_novA1.done"
exit $rc

"""Run villa's headless fit_spiral.py (baf5e605) unchanged, with vc3d_fiber_format and the vc_spiral natives built from
villa's cpp/ first on sys.path; the sparse villa snapshot lacks both. Named fit_spiral.py so other sessions' checks for a
running fit see this process. Arguments pass through (--dataset ...)."""
import os
import runpy
import sys

ROOT = 'C:/VesuviusTemp/nov_strips'
VILLA_SF = 'C:/VesuviusTemp/nov_snap/villa_main/spiral-fitting'
sys.path[:0] = [os.path.join(ROOT, 'villa_extra'), VILLA_SF]
os.chdir(VILLA_SF)
if __name__ == '__main__':
    runpy.run_path(os.path.join(VILLA_SF, 'fit_spiral.py'), run_name='__main__')

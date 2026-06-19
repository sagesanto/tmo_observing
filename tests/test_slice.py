import sys, os
import pytest
from os.path import dirname, exists, join, splitext, basename
import numpy as np
from astropy.io import fits
import shutil
import subprocess
from pathlib import Path
import tempfile
from datetime import datetime

from tmo_obs.tools.sageslice import slice_cube

test_dir = Path(__file__).parent
SLICE_OUT = test_dir/'slice_out'
DATA_DIR = test_dir/'data'

CUBE_10S = DATA_DIR/'test_cube_10s.fits'
CUBE_01S = DATA_DIR/'test_cube_01s.fits'

@pytest.mark.slice
def test_slice_cli():
    exe = shutil.which("sageslice")
    assert exe is not None, "sageslice console script is not installed in this environment"
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        result = subprocess.run(
            [exe, str(CUBE_10S), "--outdir", tmp_dir],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

@pytest.mark.slice
def test_slice():
    t = []
    sums = []
    i = -1
    d_sum = -1
    t = None
    with tempfile.TemporaryDirectory() as tmp_dir:
        slice_cube(str(CUBE_01S),tmp_dir,debug=True)
        fnames = os.listdir(tmp_dir)
        fnames.sort()
        for f in fnames:
            print(f)
            with fits.open(join(tmp_dir,f)) as hdul:
                header = hdul[0].header
                assert hdul[0].data.shape==(10,10)
                ts = datetime.strptime(header['DATE-OBS'],'%Y-%m-%dT%X.%f').timestamp()
                if t is None:
                    t = ts
                else:
                    assert np.allclose(ts*10 - t*10, 0.1, 0.0001)  # floating point
                t = ts
                
                new_sum = np.sum(hdul[0].data)
                assert new_sum == d_sum + 1
                d_sum = new_sum
import sys, os
from os.path import dirname, abspath, join
import shutil, subprocess
import pytest

FITS_PATH = join(dirname(__file__),'data','test_frame.fits')

@pytest.mark.cli
@pytest.mark.parametrize(
    ('tool', 'args'),
    [
        ('lst', None),
        ('hourangle', [0]),
        ('hourangle', [0, '--dms']),
        ('cconvert', [0,10,20,'--all']),
        ('imhead', [FITS_PATH]),
        ('imhead', [FITS_PATH, '-k','DATE-OBS','-i',0]),
        ('imstat_deluxe', [FITS_PATH]),
        ('imstat_deluxe', [FITS_PATH,'-p']),
    ],
)
def test_cli(tool, args):
    args = args or []
    args = [str(a) for a in args]
    exe = shutil.which(tool)
    assert exe is not None, f"{tool} console script is not installed in this environment"
    
    result = subprocess.run(
        [exe]+ args,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

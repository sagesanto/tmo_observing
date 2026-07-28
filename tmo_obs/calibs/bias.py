from os.path import exists, basename, dirname, join

import numpy as np
import astropy.io.fits as fits
from astropy.stats import sigma_clip

def make_superbias(bias_cube_path,superbias_outpath,extension=0):
    with fits.open(bias_cube_path) as hdul:
        cube = hdul[extension].data.astype(np.float32)
        clipped = sigma_clip(cube, sigma_lower=3, sigma_upper=3, axis=0, masked=True, copy=False)
        superbias = np.ma.mean(clipped, axis=0).filled(np.nan)
        
        n_bias_frames = hdul[extension].shape[0]
        bias_header = hdul[extension].header.copy()
        bias_header['N_BIAS'] = (n_bias_frames, 'Number of bias frames combined')
        bias_header.add_history(f'Superbias: mean+3sig-clip of {hdul[extension].shape[0]} frames from {bias_cube_path}')
        fits.writeto(superbias_outpath, superbias, bias_header, overwrite=True)
        
def default_superbias_path(bias_path):
    base = basename(bias_path)
    dirs = dirname(bias_path)
    return join(dirs,f"SUPERBIAS_{base}")
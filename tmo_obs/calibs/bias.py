from os.path import exists, basename, dirname, join

import numpy as np
import astropy.io.fits as fits
from astropy.stats import sigma_clip
        
def make_superbias(bias_cube_path,superbias_outpath,extension=0):
    with fits.open(bias_cube_path) as hdul:
        cube = hdul[extension].data
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
        
def main():
    from .utils import challenge
    import argparse
    from os.path import exists
    
    parser = argparse.ArgumentParser(description="Create a superbias from provided cube")
    parser.add_argument('bias_path',type=str,help='Path to the bias cube')
    parser.add_argument('--outpath',type=str,default=None,help='Path to the new superbias. Will be overwritten if exists. If not provided, is automatically named SUPERBIAS_{bias_path} and written out next to the provided bias')
    parser.add_argument('--extension',type=int,default=0,help='HDUL extension. Default 0')
    args = parser.parse_args()
    ext = args.extension
    if not exists(args.bias_path):
        parser.error(f"Can't find file '{args.bias_path}'")

    with fits.open(args.bias_path, memmap=False, lazy_load_hdus=True) as hdul:
        header = hdul[ext].header
        challenge(header["EXPTIME"] < 1e-5, f"File {args.bias_path} doesn't seem to be a bias because its exptime ({header['EXPTIME']}) is not near zero. Is this a bias?")
    print(f'Making superbias for {args.bias_path}...')
    if args.outpath is None:
        args.outpath = default_superbias_path(args.bias_path)
    
    make_superbias(args.bias_path,args.outpath)
    print(f'Done. Wrote to {args.outpath}')
    
if __name__ == "__main__":
    main()
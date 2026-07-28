import argparse
from tmo_obs.calibs.utils import challenge
from tmo_obs.calibs.bias import default_superbias_path, make_superbias

from os.path import exists, basename, dirname, join

import numpy as np
import astropy.io.fits as fits
from astropy.stats import sigma_clip

def main():
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
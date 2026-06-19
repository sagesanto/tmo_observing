# Sage Santomenna 2026

import sys, os
import glob
from os.path import basename

from argparse import ArgumentParser
from astropy.io import fits
from rich import print

def get_head(filename, keywords):
    with fits.open(filename) as hdul:
        header = hdul[0].header
        return {key: header.get(key) for key in keywords}

def main():
    parser = ArgumentParser(description="Get FITS header keywords")
    parser.add_argument("filenames", nargs="+", help="Path to the FITS files")
    parser.add_argument("--keywords", "-k", nargs="+", help="List of keywords to retrieve")
    args = parser.parse_args()

    keywords = args.keywords
    max_key_len = max([len(k) for k in keywords])

    fnames = []
    for fpath_or_pattern in args.filenames:
        f = glob.glob(fpath_or_pattern)
        if not len(f):
            print(f"Error: no files found matching the file/pattern {fpath_or_pattern}")
            sys.exit(1)
        fnames.extend(f)
        
    for filename in fnames:            
        result = get_head(filename, args.keywords)
        
        print(basename(filename))
        for key, value in result.items():
            kstr = f'{key}:'.rjust(max_key_len+1)
            print(f"\t{kstr} {value}")
        print()

if __name__ == "__main__":
    main()
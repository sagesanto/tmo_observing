#!/usr/bin/env python3
import sys
import argparse
import glob
from astropy.io import fits

def print_fits_headers(filename, quiet=False):
    try:
        with fits.open(filename) as hdul:
            for i, hdu in enumerate(hdul):
                if not quiet:
                    print(f"Header for HDU {i}:")
                print(repr(hdu.header))
    except Exception as e:
        if not quiet:
            print(f"An error occurred: {str(e)}")

def main():
    parser = argparse.ArgumentParser(description="Print headers of FITS images.")
    parser.add_argument("filenames", nargs="+", help="List of FITS image files or wildcards")
    parser.add_argument('-q','--quiet',action='store_true',help='silence all non-header helper text')
    args = parser.parse_args()
    quiet = args.quiet
    filenames = args.filenames
    
    def write_out(*msg):
        if not quiet:
            print(*msg) 

    for pattern in filenames:
        matching_files = glob.glob(pattern)
        if not matching_files:
            write_out(f"No matching files found for pattern: {pattern}")
            continue
        
        for filename in matching_files:
            write_out(f"{filename}")
            print_fits_headers(filename, quiet)
            write_out()


if __name__ == "__main__":
    main()
  

# Sage Santomenna 2026

import sys, os
import glob
from os.path import basename

from argparse import ArgumentParser
from astropy.io import fits

def get_head(filename, keywords, hdu_idx=None):
    with fits.open(filename) as hdul:
        h_dicts = []
        
        try: 
            hdus = hdul if hdu_idx is None else [hdul[hdu_idx]]
        except IndexError:
            print(f"File {filename} has only {len(hdul)} HDUs but HDU {hdu_idx} was requested.")
            sys.exit(1)
            
        for hdu in hdus:
            header = hdu.header
            this_k = keywords if keywords is not None else list(header.keys())
            comments = {k:header.comments[k] for k in header.keys()}
            h_dicts.append({key: (header.get(key), comments.get(key,'')) for key in this_k})
    
    return h_dicts

def main():
    parser = ArgumentParser(description="Get FITS header keywords")
    parser.add_argument("filenames", nargs="+", help="Path to the FITS files")
    parser.add_argument("--keywords", '-k', nargs="+", help="List of keywords to retrieve")
    parser.add_argument('--hdu-index','-i',type=int,default=None,help='Index of the HDU header to inspect. Looks at all HDUs by default.')
    parser.add_argument('--raw','-r',action='store_true',help='Print only the header values and nothing else (no keys, comments, or filenames). Default False')
    parser.add_argument('--no-comment','-n',action='store_true',help='Omit fits header comments in output. Default False')
    args = parser.parse_args()

    fnames = []
    for fpath_or_pattern in args.filenames:
        f = glob.glob(fpath_or_pattern)
        if not len(f):
            print(f"Error: no files found matching the file/pattern {fpath_or_pattern}")
            sys.exit(1)
        fnames.extend(f)
        
    indent = '  ' if len(fnames) > 1 else ''
        
    for filename in fnames:            
        result_dicts = get_head(filename, args.keywords,args.hdu_index)
        hdu_indent = '  ' if len(result_dicts) > 1 else ''
        if not args.raw and len(fnames) > 1:
            print(basename(filename))
        max_key_len = max(max([len(k) for k in result.keys()]) for result in result_dicts)
        max_val_len = max(max([len(str(v[0])) for v in result.values()]) for result in result_dicts)
        for i,result in enumerate(result_dicts):

            if not args.raw and len(result_dicts) > 1:
                print(f'{indent}HDU {i}')

            for key, (value,comment) in result.items():
                if args.raw:
                    print(value)
                else:
                    kstr = f'{key}'.ljust(max_key_len+1)+'='
                    vstr = f"{value}"
                    if comment and not args.no_comment: 
                        vstr = vstr.ljust(max_val_len)
                        vstr += f" / {comment}"
                    print(f"{indent}{hdu_indent}{kstr} {vstr}")
        if not args.raw and len(fnames)>1:
            print()

if __name__ == "__main__":
    main()
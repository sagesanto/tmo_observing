#!/usr/bin/env python3
import sys, os
import argparse
from os.path import join, abspath, dirname, basename
import glob
from pathlib import Path
from astropy.io import fits
from dateutil.parser import parse
from dateutil.relativedelta import relativedelta
from datetime import datetime, timedelta
import numpy as np

using_tqdm = False
try:
    from tqdm import tqdm
    using_tqdm = True
except ImportError:
    pass

def slice_cube(path, save_dir=None, skip_increment=False, tincrement=None, debug=False, extension=0):
    with fits.open(Path(path)) as hdul:
        header = hdul[extension].header
        data_cube = hdul[extension].data
        assert len(data_cube.shape)  == 3, f"Data from file {path} doesn't appear to be a cube - data shape is {data_cube.shape}"
        counter = 0
        if save_dir is None:
            save_dir = dirname(path)
        os.makedirs(save_dir, exist_ok=True)
        
        if tincrement is None and not skip_increment:
            tincrement = header['EXPTIME']

        # determine how many zeroes to put in the extension name
        nfiles = len(data_cube)
        nzeros = int(np.ceil(np.log10(nfiles)))
        if nfiles == 10**nzeros:
            nzeros+=1 

        if using_tqdm:
            img_iterator = tqdm(hdul[extension].data)
        else:
            img_iterator = hdul[extension].data

        for i in img_iterator:
            extension = f"{counter+1}".zfill(nzeros)
            img_basename = os.path.splitext(basename(path))[0]
            ipath = join(save_dir, f"{img_basename}_{extension}.fits")
            newheader = fits.Header(header,copy=True)
            if not skip_increment:
                start_time = header['DATE-OBS']
                new_date_obs = increment_date(start_time, tincrement * counter)
                newheader['DATE-OBS'] = new_date_obs
                fits.writeto(ipath, i, overwrite=True, header=newheader)
                if not using_tqdm or debug:
                    print(f'Successfully sliced {ipath} with time increment {tincrement * counter} s. Prev time: {start_time}. new time: {new_date_obs}')
            else:
                fits.writeto(ipath, i, overwrite=True, header=header)
                if not using_tqdm or debug:
                    print(f'Successfully sliced {ipath} with no time increment.')
            counter += 1

# Define the directory slicing function
def slice_all(work_dir, file_matching='*.fits', save_dir=None, skip_increment=True, tincrement=None):
    list_files = glob.glob(join(work_dir, file_matching))
    print('Files to be sliced:')
    print(list_files)
    print('\n')
    if save_dir is None:
        save_dir = work_dir
    print('Slices saved as:')
    for i in list_files:
        slice_cube(i, save_dir=save_dir, skip_increment=skip_increment, tincrement=tincrement)

# Define the date increment function
def increment_date(strdate, tincrement):
    parsed = parse(strdate)
    later = parsed + relativedelta(seconds=tincrement)
    incremented_dateobj = later.strftime('%Y-%m-%dT%X.%f')
    return incremented_dateobj


def main():
    parser = argparse.ArgumentParser(description="Slice FITS data cubes into individual images.")
    
    parser.add_argument("input_files", nargs="+", help="List of input FITS files or patterns")
    
    parser.add_argument("--skip-increment", action="store_true", help="skip incrementing the timestamp on subsequent slices. Turn off when there's no valid timestamp or ts=0000-00-00")
    parser.add_argument('-o','--outdir', default=None, help="Directory to save sliced files (default: current directory)")
    parser.add_argument('--extension', default=0, help='Which image extension to use. Default 0.')
    parser.add_argument('--debug', action='store_true', help='Write debug messages during slicing')
    args = parser.parse_args()
    
    fnames = []
    for fpath_or_pattern in args.input_files:
        fnames.extend(glob.glob(fpath_or_pattern))
    flist = '\n'.join(fnames)
    print(f"Files to be sliced: {flist}")
    
    for f in fnames:
        # increment None will use exptime as increment
        slice_cube(f, save_dir=args.outdir, skip_increment=args.skip_increment, tincrement=None, debug=args.debug, extension=args.extension)

if __name__ == "__main__":
    sys.exit(main())
    
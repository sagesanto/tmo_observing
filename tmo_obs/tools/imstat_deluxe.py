#!/usr/bin/env python3
import sys
from os.path import join, splitext, basename, dirname
import argparse
import glob
import numpy as np
from astropy.io import fits
from photutils.segmentation import deblend_sources
from astropy.convolution import Gaussian2DKernel, convolve
from astropy.stats import gaussian_fwhm_to_sigma
from photutils.segmentation import detect_sources
from photutils.segmentation import SourceCatalog
from astropy.stats import sigma_clipped_stats
from typing import List, Union
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm, SymLogNorm

import warnings
warnings.filterwarnings('ignore', module="astropy.table.groups")

PRECISION = {
    16:np.float16,
    32:np.float32,
    64:np.float64
}

def segmentation(data:np.ndarray, threshold:float, npixels:int, fwhm_pix=None):
    d = data
    if fwhm_pix is not None:
        sigma = fwhm_pix * gaussian_fwhm_to_sigma
        kernel = Gaussian2DKernel(sigma)
        d = convolve(data, kernel, normalize_kernel=True)
    segm = detect_sources(d, threshold, npixels=npixels)
    return data, segm


def deblending(convolved_data, segm, npixels, nlevels, contrast):
	segm_deblend = deblend_sources(convolved_data, segm, npixels, nlevels=nlevels, contrast=contrast,progress_bar=False)
	return segm_deblend


# given source data, create a source catalog
def source_catalog(data:np.ndarray, source_sigma, ncont, precision=np.float32, fwhm_pix=None):

    data = data.astype(precision)
    mean, median, std = sigma_clipped_stats(data, sigma=3)
    threshold = source_sigma * std
    data -= median.astype(precision)

    npixels = ncont   # number of connected pixels needed, each above threshold, for an area to qualify as a source
    convolved_data, segm = segmentation(data, threshold, npixels, fwhm_pix)
    if convolved_data is None or segm is None:
        return None
    segm_deblend = deblending(convolved_data, segm, npixels, nlevels=16, contrast=0.001)

    cat = SourceCatalog(data, segm_deblend, convolved_data=convolved_data)
    table = cat.to_table(columns=cat.default_columns+["fwhm"])

    # table[np.where(table["kron_flux"]<1)] = 0    # don't remember why i did this, commenting for now (sjs 9/25/2024)

    table.sort(['kron_flux'], reverse = True)
    return table


def calc_mean_fwhm(data:np.ndarray, source_sigma=5, ncont=16, precision=np.float32):
    catalog = source_catalog(data, source_sigma, ncont, precision=precision)
    mean_cat = catalog.groups.aggregate(np.mean)
    mean_fwhm = float(mean_cat["fwhm"][0].to_value("pix"))

    catalog = source_catalog(data, source_sigma, ncont, precision=precision, fwhm_pix=mean_fwhm)
    mean_cat = catalog.groups.aggregate(np.mean)
    mean_fwhm = float(mean_cat["fwhm"][0].to_value("pix"))
    num = len(catalog)
    return mean_fwhm, num, catalog


def calculate_image_statistics(images:List[str], subregion:Union[List[int],None]=None, precision=np.float32, save_catalog:bool=False, do_fwhm:bool=True, source_sigma=5, ncont=16, visualize:bool=False, vis_norm=True):
    subregion = subregion or []
    statistics = []
    labels = ["Pixels","Mean","Median","StdDev","Min", "Max"]
    if do_fwhm:
        labels.extend(("FWHM","NumSources"))
    
    precision = PRECISION[precision]

    for image_file in images:
        try:
            hdul = fits.open(image_file)
            # if we are going to calculate the fwhm, get the data at the float precision specified by the user (default 32)
            if do_fwhm:
                data = hdul[0].data.astype(precision)
            else:
                # otherwise, don't do that (saves memory)
                data = hdul[0].data

            if len(subregion)==4:
                x1=subregion[0]-1
                x2=subregion[1]
                y1=subregion[2]-1
                y2=subregion[3]

            if len(subregion)==0:
                x1=0
                x2=data.shape[0]
                y1=0
                y2=data.shape[1]

            # Calculate statistics

            frame = data[x1:x2,y1:y2]

            mean = np.mean(frame)
            median = np.median(frame)
            std_dev = np.std(frame)
            min_value = np.min(frame)
            max_value = np.max(frame)
            total_pixels = frame.size


            d_list = [image_file, total_pixels, mean, median, std_dev, min_value, max_value] 
            try:
                if do_fwhm:
                    f, num, catalog = calc_mean_fwhm(frame, source_sigma, ncont, precision)
                    d_list.append(f)
                    d_list.append(num)
                    if visualize:
                        if vis_norm:
                            norm = SymLogNorm(0.01,1,median-std_dev, max_value*0.5)
                            plt.imshow(frame,cmap="gray",origin="lower",norm=norm)
                        else:
                            plt.imshow(frame,cmap="gray",origin="lower",vmin=median-std_dev,vmax=max_value*0.5)
                        plt.scatter(catalog["xcentroid"],catalog["ycentroid"],alpha=0.25)
                        plt.show()
                    if save_catalog:
                        fname = splitext(basename(image_file))[0] + ".cat.csv"
                        # currently, we'll save these into the current directory. maybe it would be better to save into the fits file's dir
                        catalog.write(fname,overwrite=True)
            except AttributeError:
                d_list.append(np.nan)
                d_list.append(0)
                print(f"Warning: No sources found in {image_file}, so FWHM and NumSources set to NaN and 0.")

            statistics.append(d_list)

            hdul.close()

        except Exception as e:
            print(f"Error processing {image_file}: {str(e)}")

    return statistics, labels

def main():
    parser = argparse.ArgumentParser(description="Calculate statistics for a list of FITS images.")
    
    parser.add_argument("filenames", nargs="+", help="List_of_FITS_image_files_or_wildcards")

    parser.add_argument("-s", "--subregion",  nargs=4, type=int, help="2-d subregion on which to perform stats: syntax: xmin xmax ymin ymax")
    parser.add_argument('-d','--deluxe', dest='deluxe', action='store_true', help="Calculate image stats, run source extraction, and do fwhm calculation on the frame. Default.")
    parser.add_argument('-p','--plain', dest='deluxe', action='store_false', help="Calculate image stats only, no source extraction")
    parser.set_defaults(deluxe=True)
    parser.add_argument("--precision", default=32, type=int, help=f"Desired float precision, one of {list(PRECISION.keys())}. Default 32. Ignored if --deluxe is False.")
    parser.add_argument("-c", "--save-catalog", default=False, action="store_true", help="Whether, if when running in deluxe mode, to store the created source catalog for each image as a csv. Default False.")
    parser.add_argument("--source-sigma", default=5, type=float, help="how many standard deviations above the noise a source must be to be detected in deluxe mode. Default 5.")
    parser.add_argument("--ncont", default=16, type=int, help="number of sufficiently-bright connected pixels a source must have to be detected in deluxe mode. Default 16.")
    parser.add_argument("-v", "--visualize", action="store_true", help="Whether, if when running in deluxe mode, to plot the source catalog on the image for each frame")
    parser.add_argument('--no-norm',action='store_true',help="Don't lognorm image when visualizing")

    args = parser.parse_args()
    
    filenames = args.filenames

    subregion = args.subregion or []

    matching_files = []
    for pattern in filenames:
        matching_files.extend(glob.glob(pattern))
    if not matching_files:
        print("No matching files found.")
        sys.exit(1)
    print(f"Running on {len(matching_files)} frame{'s' if len(matching_files)>1 else ''}: {', '.join(matching_files)}")

    deluxe = args.deluxe

    precision = args.precision
    try:
        precsision = PRECISION[precision]
    except KeyError:
        print(f"ERROR: --precision must be one of {list(PRECISION.keys())}, not '{precision}'")
        sys.exit(1)

    save_catalog = args.save_catalog

    source_sigma = args.source_sigma
    ncont = args.ncont
    visualize = args.visualize

    statistics, labels = calculate_image_statistics(matching_files, subregion, precision, save_catalog, do_fwhm=deluxe, source_sigma=source_sigma, ncont=ncont, visualize=visualize, vis_norm=not args.no_norm)

    for stats in statistics:
        strs = [f"{s:.2f}" if np.issubdtype(type(s), np.floating) else str(s) for s in stats]
        print("")
        print(f"{strs[0]}:")
        
        data_sep = max(len(s) for s in strs[1:-1])
        label_sep = max(len(s) for s in labels[:-1])
        sep = max(data_sep,label_sep)+1
        labels = [f"{l:<{sep}}" for l in labels]
        strs = [f"{s:<{sep}}" for s in strs]
        print(" ".join(labels))
        print(" ".join(strs[1:]))

if __name__ == "__main__":
    sys.exit(main())
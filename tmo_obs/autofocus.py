import sys, os
import argparse
from glob import glob
import logging

import numpy as np
import matplotlib.pyplot as plt
from astropy.convolution import Gaussian2DKernel, convolve
from astropy.stats import gaussian_fwhm_to_sigma, sigma_clipped_stats, SigmaClip
from astropy.table import Table, vstack
from astropy.modeling import models, fitting
from astropy.io import fits
from photutils.segmentation import detect_sources, deblend_sources, SourceCatalog
import tomli

from tmo_obs.config import load_config, configure_logger

import photometrics
from photometrics.logger import get_logger
from photometrics.pomona import Controller
from photometrics.filterwheel import FilterWheel
from photometrics.fli_filterwheel import FLIFilterWheel
from photometrics.syntrack_client import SynTrackClient
from photometrics.pysyntrack_interface import PySynTrack_Interface
from photometrics.camera_control import focus_and_capture

import warnings
warnings.filterwarnings('ignore', module='astropy.table.table')

# VERSION = __file__.split('_')[-1]

def Image_Segmentation(data, threshold, npixels):
    # Convolve the data with a 2D circular Gaussian kernel with a FWHM of 3 pixels to smooth the image prior to thresholding
    sigma = 10.0 * gaussian_fwhm_to_sigma  # FWHM = 3.
    kernel = Gaussian2DKernel(sigma, x_size=11, y_size=11)
    #kernel = Gaussian2DKernel(sigma)
    convolved_data = convolve(data, kernel, normalize_kernel=True)
    
    # npixels == how many connected pixels, each above threshold, should an area have to qualify as a source
    segm = detect_sources(convolved_data, threshold, npixels=npixels)

    return convolved_data, segm

# ---------------------------------------------------- Source Deblending ---------------------------------------------------

def Deblending(convolved_data, segm, npixels, nlevels, contrast):
    segm_deblend = deblend_sources(convolved_data, segm, npixels, nlevels=nlevels, contrast=contrast)
    # keyword "nlevels" is the number of multi-thresholding levels to use. 
    # keyword "contrast" is the fraction of the total source flux that a local peak must have to be considered as a separate object.
    # The source segments represent the isophotal footprint of each source, so isophotal photometry is possible.

    return segm_deblend


# ---------------------------------------------- Read FITS Cube ----------------------------------------------

def Read_4DFITS_Cube(CubeName, n):
    # Read a FITS cube that has four dimensions, with NAXIS_4 == n, NAXIS_3 == 1, np.shape == (n, 1, y, x)
    hdulist = fits.open(CubeName)
    data = hdulist[0].data[n][0]
    data = data.astype('float64')

    return data

# ----------------------------------------------- Find Sources ----------------------------------------------------

# npixels: number of connected pixels needed, each above threshold, for an area to qualify as a source
# thresh: coeffecient of std. dev. in determining detection threshold 
def extract_sources(data, npixels, thresh):
    # Background subtraction
    mean, median, std = sigma_clipped_stats(data, sigma=3.0)
    threshold = thresh * std 
    data -= median

    convolved_data, segm = Image_Segmentation(data, threshold, npixels)
    segm_deblend = Deblending(convolved_data, segm, npixels, nlevels=8, contrast=1)    

    # Photometry statistics
    cat = SourceCatalog(data, segm_deblend, convolved_data=convolved_data)
    columns = ['label','xcentroid','ycentroid','fwhm','gini','eccentricity','orientation','kron_flux']
    tbl = cat.to_table(columns=columns)
    # eliminate the 'nan' values in kron_flux, origin unknown
    for i in range(len(tbl)):   
        if tbl['kron_flux'][i] > 1:
            #valid += 1
            continue
        else:
            tbl['kron_flux'][i] = 0        
    tbl.sort(['kron_flux'], reverse = True) # sort tbl by kron_flux, brightest first
    return tbl 



# ----------------------------------------------- Outline Sources ---------------------------------------------------

#import regions
#from regions import PixCoord, CirclePixelRegion, Regions

# #take in a table sorted by decreasing brightness 
# #output file titled af_x + regions_ + y + .reg where x is the autofocus loop and y is the frame number 
# def get_regions(tbl, n, prefix):
#     tbl = tbl[0:300] #trim to 10 brightest 
#     regs = regions.Regions()

#     expansion_coeff = 2
#     if n == 100:
#         expansion_coeff = 3.5

#     for i in range(len(tbl)):
#         center = regions.PixCoord(x=tbl['xcentroid'][i], y=tbl['ycentroid'][i])
#         r = tbl['fwhm'][i]*expansion_coeff
#         if r < 0:
#             r = 15
#         reg = regions.CirclePixelRegion(center=center, radius=r)
#         regs.append(reg)
#     regs.write('./focusloop/' + prefix + 'regions_' + str(n) + '.reg', format = 'ds9', overwrite = True)


# -------------------------------------------------- FWHM Curve --------------------------------------------------

def FWHM_Curve(CubeDirectory, CubeName, FocusVec, prefix, logger, show_in_browser = False):
    
    # obtain focus-vec params
    # -----------------------------
    focus_value_list = np.arange(start=FocusVec[0], stop=FocusVec[1], step=FocusVec[2])
    ImageNum = len(focus_value_list)


    #count the number of sources detected in each image 
    counts = []

    first_frame = Read_4DFITS_Cube(CubeName, 0)
    overlayed_image = np.zeros_like(first_frame)
    for n in range(ImageNum):
        data = Read_4DFITS_Cube(CubeName, n)
        overlayed_image += data

    compiled_tbl = extract_sources(overlayed_image, 16, 10)
    #compiled_tbl = compiled_tbl[0:10]
    num = len(compiled_tbl) 
    found = np.full(num, True)
    corresponding_focuses = [] # for the nth brightest master source, the nth list holds the focus values where we found that master source 
    for i in range(0, num):
        corresponding_focuses.append([])
    sources = []
    for i in range(num):
        sources.append(Table(names = compiled_tbl.colnames))


    #telescope feature (not a legitimate target) in bottom right corner 
    found_feature = False

    for i in range(len(sources)):
        if compiled_tbl['xcentroid'][i] > 2220 and compiled_tbl['ycentroid'][i] < 10:
            found[i] = False
            found_feature = True 

    #test seeing compiled image
    # hdu = fits.PrimaryHDU(overlayed_image)
    # hdu.writeto('compiled_test.fits', overwrite=True)
        
    # get_regions(Table(compiled_tbl, names=compiled_tbl.colnames), 100, prefix)


    # Loop through images and perform elliptical photometry
    # -----------------------------------------------------

    for n in range(ImageNum):
        
        data = Read_4DFITS_Cube(CubeName, n)
        logging.info(f"doing photometry on {n}th image")
        logging.info(f"ImageNum: {ImageNum}")

        tbl = extract_sources(data, 100, 2)
        # get_regions(Table(tbl, names=tbl.colnames), n, prefix)

        counts.append(len(tbl))
        #filtered_counts.append(valid)


        for i in range(num):
            # if found[i]:
                x = compiled_tbl['xcentroid'][i]
                y = compiled_tbl['ycentroid'][i]

                matches = Table(names = tbl.colnames)
                for j in range(len(tbl)):
                    currentx = tbl['xcentroid'][j]
                    currenty = tbl['ycentroid'][j]
                    if abs(currentx - x) < 25 and abs(currenty - y) < 25:
                        matches.add_row(tbl[j])
                
                if len(matches) == 0:
                    found[i] = False

                #new addition 
                elif len(matches) > 1:
                    if n != 0 or n != (ImageNum - 1):
                        found[i] = False

                else:
                    matches.sort(['fwhm'], reverse = True)
                    sources[i].add_row(matches[0])

                    corresponding_focuses[i].append(focus_value_list[n])


    # Show photometry results in Firefox if needed
    # -----------------------------
    # this is probably supposed to be 'tbl' - Sage April 2026
    if show_in_browser == True:
        table['xcentroid'].info.format = '.1f'   # for formatting
        table['ycentroid'].info.format = '.1f'
        table['fwhm'].info.format = '.2f'
        table['gini'].info.format = '.4f'
        table['eccentricity'].info.format = '.2f'
        table['orientation'].info.format = '.1f'
        table['kron_flux'].info.format = '.0f'
        table.show_in_browser(jsviewer=True)


    used_per_image = []
    table = Table(names = tbl.colnames)
    for i in range(ImageNum):
        current_count = 0
        myImage = Table(names = tbl.colnames)
        for j in range(num):
            if found[j]:
                if focus_value_list[i] in corresponding_focuses[j]:
                    myImage.add_row(sources[j][i])
                    current_count += 1
        used_per_image.append(current_count)
                

        tbl_mean = myImage.groups.aggregate(np.mean)
        table.add_row(tbl_mean[0])


    #looking at a specific object with index 'testing' 
    #testing = 3
    #table = sources[testing]
    focus_value_list_2 = focus_value_list
    #focus_value_list = np.array(corresponding_focuses[testing])


    # Define fitting models
    # -----------------------------
    sigma_clip = SigmaClip(sigma=3.0)
    model = models.Polynomial1D(degree=3)   # 3rd degree polynomial

    # Outlier removal wrapper (sigma clip) around polynomial model
    fitter = fitting.FittingWithOutlierRemoval(fitting.LevMarLSQFitter(), sigma_clip, niter=3)
    fit, mask = fitter(model, focus_value_list, table['fwhm'])

    fit2, mask2 = fitter(model, focus_value_list, table['gini'])




    # Fit cubic for FWHM curve
    # -----------------------------
    a, b, c, d = fit.parameters[3], fit.parameters[2], fit.parameters[1], fit.parameters[0]
    
    # Turning-point calculation (2 turning-points)
    fturn_pt_x1 = (-b + np.sqrt(b**2 - 3*a*c)) / (3*a)
    fturn_pt_x2 = (-b - np.sqrt(b**2 - 3*a*c)) / (3*a)

    fturn_pt_y1 = a*fturn_pt_x1**3 + b*fturn_pt_x1**2 + c*fturn_pt_x1 + d
    fturn_pt_y2 = a*fturn_pt_x2**3 + b*fturn_pt_x2**2 + c*fturn_pt_x2 + d

    # Determine which turning-point to use (local minimum)
    if fturn_pt_y1 < fturn_pt_y2:
        fwhm_opt = fturn_pt_x1
    else:
        fwhm_opt = fturn_pt_x2


    # Fit cubic for gini curve
    # -----------------------------
    a, b, c, d = fit2.parameters[3], fit2.parameters[2], fit2.parameters[1], fit2.parameters[0]

    # Turning-point calculation (2 turning-points)
    gturn_pt_x1 = (-b + np.sqrt(b**2 - 3*a*c)) / (3*a)
    gturn_pt_x2 = (-b - np.sqrt(b**2 - 3*a*c)) / (3*a)
    #logger.info(f"gini_opt matrix = {[gturn_pt_x1, gturn_pt_x2]}")
    gturn_pt_y1 = a*gturn_pt_x1**3 + b*gturn_pt_x1**2 + c*gturn_pt_x1 + d
    gturn_pt_y2 = a*gturn_pt_x2**3 + b*gturn_pt_x2**2 + c*gturn_pt_x2 + d

    # Determine which turning-point to use (local maximum)
    if gturn_pt_y1 > gturn_pt_y2:
        gini_opt = gturn_pt_x1
    else:
        gini_opt = gturn_pt_x2

    logger.info(f"Optimal focus value based on FWHM curve = {fwhm_opt}")
    logger.info(f"Optimal focus value based on Gini curve = {gini_opt}")


    # Plotting in matplotlib 
    # -----------------------------
    
    fwhm_mean = np.mean(table['fwhm'])
    fwhm_max = np.max(table['fwhm'])
    eccen_min, eccen_max = np.min(table['eccentricity']), np.max(table['eccentricity'])
    theta_min, theta_max = np.min(table['orientation']), np.max(table['orientation'])
    counts_min, counts_max = np.min(counts), np.max(counts)
    used_min, used_max = np.min(used_per_image), np.max(used_per_image)
    kron_min, kron_max = np.min(table['kron_flux']), np.max(table['kron_flux'])


    # Initialize fig and axes
    fig1, (ax1, ax2, ax3, ax4, ax5) = plt.subplots(1, 5, figsize=(18,10))
    ax1.set_ylim([np.min(table['gini'])*fwhm_mean/1.1, fwhm_max*1.1])

    # Fig with only the FWHM/Gini plot
    fig2, (ax6) = plt.subplots(1, 1, figsize=(10,10))
    ax6.set_ylim([np.min(table['gini'])*fwhm_mean/1.1, fwhm_max*1.1])


    # Plot FWHM, gini, and cubic fits
    ax1.scatter(focus_value_list, table['fwhm'], label="FWHM Curve")
    ax1.plot(focus_value_list, fit(focus_value_list), 'r--', alpha=0.7)
    ax1.scatter(focus_value_list, table['gini']*fwhm_mean*1.3, label="Gini Curve (rescaled)")
    ax1.plot(focus_value_list, fit2(focus_value_list)*fwhm_mean*1.3, 'r--', alpha=0.7)

    # Plot selected turning points for FWHM and gini
    ax1.vlines(x=fwhm_opt, ymin=0, ymax=fwhm_max, linewidth=1, colors='tab:blue')
    ax1.vlines(x=gini_opt, ymin=0, ymax=fwhm_max, linewidth=1, colors='tab:orange')

    # Plot FWHM, gini, and cubic fits
    ax6.scatter(focus_value_list, table['fwhm'], label="FWHM Curve")
    ax6.plot(focus_value_list, fit(focus_value_list), 'r--', alpha=0.7)
    ax6.scatter(focus_value_list, table['gini']*fwhm_mean*1.3, label="Gini Curve (rescaled)")
    ax6.plot(focus_value_list, fit2(focus_value_list)*fwhm_mean*1.3, 'r--', alpha=0.7)

    # Plot selected turning points for FWHM and gini
    ax6.vlines(x=fwhm_opt, ymin=0, ymax=fwhm_max, linewidth=1, colors='tab:blue')
    ax6.vlines(x=gini_opt, ymin=0, ymax=fwhm_max, linewidth=1, colors='tab:orange')

    # Plot eccentricity with shaded area bounded by FWHM+gini turning-point
    ax2.scatter(focus_value_list, table['eccentricity'])
    ax2.vlines(x=fwhm_opt, ymin=eccen_min-0.1, ymax=eccen_max+0.1, linewidth=1, colors='tab:blue', label='FWHM opt')
    ax2.vlines(x=gini_opt, ymin=eccen_min-0.1, ymax=eccen_max+0.1, linewidth=1, colors='tab:orange')
    ax2.axvspan(fwhm_opt, gini_opt, alpha=0.2, color='tab:blue')

    # Plot orientation with shaded area bounded by FWHM+gini turning-point
    ax3.scatter(focus_value_list, table['orientation'])
    ax3.vlines(x=fwhm_opt, ymin=theta_min-10, ymax=theta_max+10, linewidth=1, colors='tab:blue', label='FWHM opt')
    ax3.vlines(x=gini_opt, ymin=theta_min-10, ymax=theta_max+10, linewidth=1, colors='tab:orange')
    ax3.axvspan(fwhm_opt, gini_opt, alpha=0.2, color='tab:blue')

    ax4.scatter(focus_value_list_2, counts, label = "Sources found")
    ax4.scatter(focus_value_list_2, used_per_image, label = "Sources used")
    ax4.vlines(x=fwhm_opt, ymin=counts_min-3, ymax=counts_max+3, linewidth=1, colors='tab:blue')
    ax4.vlines(x=gini_opt, ymin=counts_min-3, ymax=counts_max+3, linewidth=1, colors='tab:orange')
    ax4.axvspan(fwhm_opt, gini_opt, alpha=0.2, color='tab:blue')
    #fit3, mask3 = fitter(model, focus_value_list_2, counts)
    #ax4.plot(focus_value_list_2, fit3(focus_value_list_2), 'r--', alpha=0.7)

    ax5.scatter(focus_value_list, table['kron_flux'])
    ax5.vlines(x=fwhm_opt, ymin=kron_min-3, ymax=kron_max+3, linewidth=1, colors='tab:blue', label='FWHM opt')
    ax5.vlines(x=gini_opt, ymin=kron_max-3, ymax=kron_max+3, linewidth=1, colors='tab:orange')
    ax5.axvspan(fwhm_opt, gini_opt, alpha=0.2, color='tab:blue')


    #ax4.scatter(focus_value_list, filtered_counts, label = "Nonzero kron-flux")


    ax1.set_xlabel('Focus Value')
    ax2.set_xlabel('Focus Value')
    ax3.set_xlabel('Focus Value')
    ax4.set_xlabel('Focus Value')
    ax5.set_xlabel('Focus Value')
    ax6.set_xlabel('Focus Value')


    ax1.set_title('FWHM & Gini')
    ax2.set_title('eccentricity')
    ax3.set_title('orientation')
    ax4.set_title('sources detected')
    ax5.set_title('kron flux')
    ax6.set_xlabel('Focus Value')


    ax1.legend()
    ax4.legend()
    ax6.legend()

    used = 0
    for i in found:
        if i: 
            used += 1
    if found_feature:
        num -= 1

    # Save plot as focusloop_[num]_plots.png in the local directory
    fig1.suptitle(CubeName[:-10]+'    FocusVec = '+str(FocusVec)+'    FWHM Opt = '+str(fwhm_opt)[:6]+ '    Gini Opt = '+str(gini_opt)[:6] +'\n \n Master sources detected = '+str(num)+'    Num. sources used = '+str(used), fontsize = 16)
    fig1.savefig(CubeName[:-9]+'plots_additional.png')

    fig2.suptitle(CubeName[:-10]+'    FocusVec = '+str(FocusVec)+'\n FWHM Opt = '+str(fwhm_opt)[:6]+ '    Gini Opt = '+str(gini_opt)[:6] +'\n Master sources detected = '+str(num) +'    Num. sources used = '+str(used), fontsize = 12)
    fig2.savefig(CubeName[:-9]+'plots.png')

    logger.info('figures saved')


    # Credibility valve
    # -------------------------
    if abs(fwhm_opt - gini_opt) > 200:
        logger.error("WARNING: FWHM and gini do not agree. Going to predictive/original focus instead.")
        fwhm_opt = None
    return fwhm_opt, table


# ------------------------------------------ Telescope Operation -----------------------------------------

ImageBinningSize = {'1x1': 1, '2x2': 2, '4x4': 4}
ImageBinningModes = ['HostSum', 'FPGASum']

# __move_filter is from Navtej's take_images code, mainly used to bypass filterwheel here
# -----------------------------------------------------------------------------
def __move_filter(filter_name, logger, retries=6):
    """change filter"""

    fw = FLIFilterWheel()
    fw.connect()

    if fw.num_filter_wheels > 0:
        fw.set_filter_name(filter_name)
        rtn_flt_name = fw.get_filter_name()
        logger.info('Filter set to : %s' % rtn_flt_name)
        return rtn_flt_name
    else:
        logger.error('No FLI filter found')

    return

# Do a take_images --focus-vec and make 4D cube out of focus-vec
# --------------------------------------------------------------
def run(params, logger):
    
    if params['prefix'] is None:  # auto-determine prefix
        i=0
        while True:
            prefix = f'af_{i}'
            focus_vec_name = os.path.join(params['directory'], prefix)
            flist = glob(focus_vec_name + '_[0-9]*')
            if not flist:  # prefix doesn't already exist, let's use it
                params['prefix'] = prefix
                break
            i += 1

    # If no --skip_focus_vec is passed, do a --focus-vec
    # This is the normal operation mode
    # -----------------------------
    if params['skip_focus_vec'] == False:
        """entry point for take_images"""
        logger.info(f'Running autofocus.')
        # logger.info(f'Running autofocus {VERSION}.')
        if not params['skip_filter']:
            # move filter wheel
            logger.info('Moving filter wheel to : %s' % params['filter'].upper())
            status = __move_filter(params['filter'], logger)
            if not status:
                raise SystemExit('Unable to move the filter wheel. Stopping.')
        else:
            logger.warning('Skipping filter wheel')

        # Connect to ACE telescope control system
        logger.info('Connecting to ACE telescope control system')
        scope = Controller()
        scope.connect(photometrics.TELESCOPE_CONTROLLER)
        # Get current focus
        focus0 = scope.get_focus()
        logger.info(f"Current focus value = {focus0}")

        # Automatic asymmetric range or customize focus-vec value
        if params['focus_vec'] != None:
            params['focus_vec'] = [int(s.strip()) for s in params['focus_vec'].split(",")]
        else:
            params['focus_vec'] = [int(focus0-1200), int(focus0+900), int(200)]
        logger.info("focus_vec = {params['focus_vec']}")

        # connect to SynTrack server
        logger.info('Connecting to SynTrack server...')
        syntrack_obj = PySynTrack_Interface(params['syntrack_ip'], params['syntrack_port'])
        
        with syntrack_obj as syntrack_client:
            if not syntrack_client.is_syntrack_alive():
                logger.error('Unable to connect to SynTrack server. Stopping.')
            else:
                # Set syntrack archive path
                logger.info('Setting SynTrack archive path')
                tmp = os.path.abspath(params['directory']).split('/')
                #dirname = tmp[3] + ':'
                dirname = '{}/{}'.format(params['capture_dir_prefix'], tmp[3])
                for val in tmp[4:]:
                    dirname += '/' + val
                #syntrack_client.set_archive_path(dirname)
                syntrack_client.execute_cmd('remove_archive_paths')
                syntrack_client.execute_cmd('add_archive_path', dirname)
                logger.info('SynTrack archive path set')

                # Set syntrack metadata filename
                logger.info('Setting SynTrack metadata filename')
                #syntrack_client.set_metadata_filename('%s/%s' % (dirname, params['metadata_filename']))
                syntrack_client.execute_cmd('close_metadata_file')
                syntrack_client.execute_cmd('open_metadata_file', os.path.join(dirname, params['metadata_filename']))
                logger.info('SynTrack metadata filename set')
                
                cam_params = dict()
                logger.info(f"Using camera {params['camera'].lower()}")
                if params['camera'].lower() == 'photometrics':
                    cam_params['name'] = 'photometrics'
                    cam_params['sensor_width'] = 1608
                    cam_params['sensor_height'] = 1608
                    cam_params['readout_port_index'] = params['readout_port_index']
                    cam_params['readout_speed_index'] = params['readout_speed_index']
                    cam_params['readout_gain_index'] = params['readout_gain_index']
                    cam_params['clear_cycles'] = params['clear_cycles']
                    cam_params['expose_out_mode'] = params['expose_out_mode']
                    cam_params['clear_mode'] = 'Never'
                elif params['camera'].lower() == 'ximea':
                    cam_params['name'] = 'ximea'
                    cam_params['sensor_width'] = 6144
                    cam_params['sensor_height'] = 6144
                    cam_params['operation_mode'] = params['operation_mode']
                    cam_params['analog_gain'] = params['analog_gain']
                    cam_params['binning_mode'] = params['binning_mode']
                    cam_params['binning_size'] = params['binning_size']
                    cam_params['roi_startx'] = params['roi_startx']
                    cam_params['roi_starty'] = params['roi_starty']
                    cam_params['roi_width'] = params['roi_width']
                    cam_params['roi_height'] = params['roi_height']

                # Do a take_images --focus-vec
                logger.info('Acquire telescope focus images (focus values from a vector)')
                f_vec = params['focus_vec']
                focuses = range(*f_vec)
                nexps = len(focuses)
                expvec = range(nexps)
                exptimes = [float(params['focus_slope']) * abs(exp - expvec[nexps // 2]) * f_vec[2] +
                            float(params['exposure']) for exp in expvec]


                logger.info(cam_params)
                focus_and_capture(params['directory'], exptimes, 1, params['prefix'], 'focusloop',
                                focuses, syntrack_client, scope, append_datetime=params['no_datetime'],
                                do_bin2fits=True, skip_temp=params['skip_temp'],
                                skip_sqm=params['skip_sqm'], **cam_params)
    
    # Skip focus-vec if --skip_focus_vec is passed
    # Has to input --focus-vec flag as well
    # This is debug mode
    # -----------------------------
    else:
        logger.info("Skipping focus-vec. Doing photometry on named focusloop")
        try:
            params['focus_vec'] = [int(s.strip()) for s in params['focus_vec'].split(",")]
        except:
            raise NameError('Please feed me with focus-vec values because focus-vec has been skipped')


    # Make 4D Cube from focus-vec 
    # ---------------------------
    FocusVecName = os.path.join(params['directory'], params['prefix'])
    FileList = glob(FocusVecName + '_[0-9]*')
    FileList.sort()
    logger.info(f"Focusloop FITS list ={FileList}")

    img_list = []
    for FileName in FileList:
        img = fits.getdata(FileName)
        img_list.append(img)
    img_array = np.array(img_list)
    logger.info(f"FITS Cube shape = {np.shape(img_array)}")

    fits.writeto(FocusVecName+'_Cube.fits', img_array, overwrite=True)


    # Try photometry & error handling
    # -------------------------
    try:
        optimal_focus, table = FWHM_Curve(CubeDirectory=params['directory'], CubeName=FocusVecName+'_Cube.fits',\
                                     FocusVec=params['focus_vec'], prefix = params['prefix'], logger=logger,
                                    show_in_browser=params['show_in_browser'])
        table.write('./focusloop/'+params['prefix']+'_data.csv', overwrite=True)
        
    except TypeError:
        optimal_focus = None
        logger.error("WARNING: Photometry failed. Going to predictive/original focus. \n"
                "This is because no sources are detected in a frame. \n"
                "Double check if environment is correct. \n"
                "Check the focusloop cube by typing in terminal: ds9 focusloop_[loop number]_Cube.fits \n")
    except IndexError:
        optimal_focus = None
        logger.error("WARNING: Photometry failed. Going to predictive/original focus. \n"
                "This could be focus-vec skipping an exposure. \n"
                "Check the focusloop names by typing in terminal: ls -ltr, see if there are discontinuities in focus value.")
    except Exception as e:
        optimal_focus = None
        logger.error("WARNING: Did not get to photometry. Could be failing during focus-vec. \n"
                "Going to predictive/original focus now.")
        logger.error(repr(e))
        logger.error(e)
        raise e
    

    # Move focuser to value
    # -------------------------
    if optimal_focus != None:
        logger.info(f'Moving focuser to: {optimal_focus}')
        rv = scope.focus(optimal_focus)
        logger.info(f"Previous focus value: {focus0}")
        logger.info(f"Moving focuser to: {optimal_focus}")
        logger.info(f"Moved to optimal value. Check FWHM plot by typing in terminal: eog focusloop_[loop number]_plots.png or _plots_additional.png")
        if not rv:
            logger.error("WARNING: Failed to go to optimal focus. Go to predictive/original focus instead.")
            optimal_focus = None
    if optimal_focus == None:
        # Go to predictive focus or return to original focus (pre focus-vec)
        if params['predict'] != None:
            refocus = params['predict']
            logger.info(f'Moving focuser to: predictive focus = {refocus}')
            rv = scope.focus(refocus)
            if not rv:
                logger.error("WARNING: Failed to go to predictive focus. Going to original focus instead.")
                logger.info(f'Moving focuser to: original focus = {focus0}')
                rv = scope.focus(focus0)
        else:
            logger.info(f'Moving focuser to: original focus = {focus0}')
            rv = scope.focus(focus0)
        if not rv:
            logger.error("WARNING: Failed to go to original focus. Please change focus manually.")

    # disconnect telescope
    logger.info('Disconnect from ACE telescope control system')
    scope.disconnect()

    return

# Argument parser
# ------------------------
def main():
    # config_path = '/media/processor/ssdraid0/pomona/auto_observe.toml'
    # with open(config_path, "rb") as f:
    #     config = tomli.load(f)
    config = load_config()
    CAM_NAME = config['CAMERA_NAME']
    CAM_CONFIG = config['CAMERAS'][CAM_NAME.upper()]
    autofocus_cfg = CAM_CONFIG['COMMON']
    autofocus_cfg.update(CAM_CONFIG['AUTOFOCUS'])
    sensor_width = autofocus_cfg['sensor_width']
    sensor_height = autofocus_cfg['sensor_height']

    parser = argparse.ArgumentParser(description='TM23 Cassegrain instrument image acquisition utility')

    # Native take_images arguments
    parser.add_argument('--prefix', '-p', type=str, default=None, help='focusloop name')

    parser.add_argument('--directory', default='./focusloop/', type=str, help='target directory; default to ./focusloop')
    parser.add_argument('--exposure', default=2.0, type=float, help='exposure time (sec); default to 2 sec')
    parser.add_argument('--filter', default='CLEAR', type=str, help='filter name', choices=['V', 'R', '50NM', 'SHUTTER', 'CLEAR', 'NONE'])
    parser.add_argument('--no-datetime', help='Disable date/time suffix', action='store_false')
    parser.add_argument('--syntrack-ip', type=str, action='store', default=photometrics.SYNTRACK_IP, help='SynTrack server IP')
    parser.add_argument('--syntrack-port', type=int, action='store', default=photometrics.SYNTRACK_PORT, help='SynTrack server port')
    parser.add_argument('--capture-dir-prefix', type=str, action='store', default='/media', help='data source directory prefix')
    parser.add_argument('--metadata-filename', type=str, action='store', default='Metadata.db',help='SynTrack metadata file name')
    parser.add_argument('--skip-filter', action='store_true', default=False, help='skip filter wheel commands')
    parser.add_argument("--show_in_browser", type=bool, help = "show photometry datatable in Firefox; default to False", default=False)

    # Camera being used
    parser.add_argument('--camera', type=str, choices=['photometrics', 'ximea'], default='ximea', help='camera to use')
    

    parser.add_argument('--skip-temp', action='store', type=bool, default=None, help="Don't attempt to get dome temperature reading while taking image")
    parser.add_argument('--skip-sqm', action='store', type=bool, default=None, help="Don't attempt to get seeing reading while taking image")

    # Focusloop arguments
    parser.add_argument('--skip-focus-vec', action='store_true', default=False, help='skip focus-vec before photometry curve; for debugging')
    parser.add_argument('--predict', default=None, type=int, help="Drive to predictive focus as a safety net for autofocus failure")
    parser.add_argument('--focus-slope', default=0, help='Variable exposure time for focus images; default to 0')
    parser.add_argument('--focus-vec', default=None, help='start,stop,delta vector of focus positions; default to current-1200,current+900,100')

    # Photometrics camera parameters
    parser.add_argument('--readout-port-index', action='store', default=0, type=int,
        help='Readout port Index')
    parser.add_argument('--readout-speed-index', action='store', choices=[0, 1], default=1, type=int,
        help='Readout speed Index')
    parser.add_argument('--readout-gain-index', action='store', default=1, type=int,
        help='Readout gain Index')
    parser.add_argument('--clear-cycles', action='store', default=2, type=int,
        help='Number of clear cycles')
    parser.add_argument('--expose-out-mode', action='store', default='First Row', type=str,
        choices=['First Row', 'All Rows', 'Any Row', 'Rolling Shutter'], help='Number of clear cycles')

    # ------ Ximea camera parameters
    parser.add_argument('--operation-mode', type=int, action='store',
        default=None, help='Ximea operation mode')
    parser.add_argument('--analog-gain', type=float, action='store', default=None,
        help='Ximea analog gain in dB')
    parser.add_argument('--binning-mode', action='store', choices=[val for val in ImageBinningModes],
        default=None, help='image binning mode')
    parser.add_argument('--binning-size', action='store', choices=[val for val in ImageBinningSize.keys()],
        default=None, help='image binning')
    parser.add_argument('--roi-startx', action='store', default=0, type=int, help='Image startx')
    parser.add_argument('--roi-starty', action='store', default=0, type=int, help='Image starty')
    parser.add_argument('--roi-width', action='store', default=None, type=int,
        help='Image width in pixels')
    parser.add_argument('--roi-height', action='store', default=None, type=int,
        help='Image height in pixels')
        
    ## FOr later: operation_mode=11, roiheight=2260, roiwidth=2260, roistartx=656, roistarty=2700

    # parse arguments
    args = vars(parser.parse_args())
    
    for k in ['skip_sqm','skip_temp']:
        if args[k] is None:
            args[k] = config.get(k.upper(),False)

    for k in ['operation_mode','analog_gain','binning_mode','binning_size']:
        if args[k] is None:
            args[k] = autofocus_cfg[k]

    # set up detector size
    if args['roi_height'] is None:
        args['roi_height'] = int(sensor_height / int(args['binning_size'][2]))
    if args['roi_width'] is None:
        args['roi_width'] = int(sensor_width / int(args['binning_size'][0]))
      
    logger = configure_logger('autofocus','obs.log')
    #logger = make_logger(args['log_path'], args['log_filename'])
    
    outdir = args['directory']
    # create a focusloop folder inside the date folder
    if not os.path.exists(outdir):
        os.mkdir(outdir)
        logger.info(f'Created focusloop folder {outdir}')
        
    run(args, logger)

if __name__ == '__main__':
    main()

# Sage Santomenna 2026

import os
import sys
import time
from datetime import datetime
import numpy as np
import argparse
from os.path import join, abspath
from enum import Enum
import json
import subprocess
import tomli
import copy

from astropy.time import Time
from astropy import units as u
from astropy.io import ascii

import photometrics
from photometrics.pomona import Controller
from photometrics.filterwheel import FilterWheel

######## Added new FLI filter wheel control - Nez, July 2023
from photometrics.fli_filterwheel import FLIFilterWheel
from photometrics.syntrack_client import SynTrackClient
from photometrics.camera_control import (
    grid_and_capture,
    focus_and_capture,
    capture_single,
    recenter_and_capture,
    get_astrometric_pos,
)

from photometrics.pysyntrack_interface import PySynTrack_Interface, CompressionLevel

from tmo_obs.config import get_config_path
from tmo_obs.utils import load_horizon_box, zenith_slew_required, current_dt_utc

# +----------+------+--------+---------------+
# | Recenter | Slew | Offset |   Behavior    |
# +----------+------+--------+---------------+
# |        - |    0 |      0 | no slew       |
# |        1 |    1 |      0 | direct slew   |
# |        1 |    1 |      1 | indirect slew |
# |        - |    0 |      1 | offset        |
# |        1 |    1 |      0 | blind slew    |
# |        0 |    1 |      1 | [invalid]     |
# +----------+------+--------+---------------+

class SlewType(Enum):
    NoSlew = "noslew"
    Direct = 'direct'  # slew to target and perform recentering on target 
    Indirect = 'indirect'
    Offset = 'offset'
    Blind = 'blind'
    
class ResultsDbType(Enum):
    LID = "Lunar Impact Detector"  # moon
    GEO = "Synthetic Tracking"  # NEOs or GEOs
    NEO = "Synthetic Tracking"  # NEOs or GEOs

import logging
from tmo_obs.config import configure_logger

logger = configure_logger("observer","obs.log")
    
def input_to_enum(input_value, val_dispname, enum_class, default_val=None):
    try:
        val = enum_class(input_value)
    except ValueError as e:
        if default_val:
            logger.error(f"Invalid {val_dispname} '{input_value}'. Valid {val_dispname}s are {[opt.value for opt in enum_class]}. Defaulting to {default_val}.")
            val = default_val
        else:
            raise ValueError(f"Invalid {val_dispname} '{input_value}'. Valid {val_dispname}s are {[opt.value for opt in enum_class]}.") from e
    return val

def load_results_db_if_not_open(db_path:str, analysis_type:ResultsDbType, conn:PySynTrack_Interface):
    # get the list of currently-loaded dbs
    r = conn.execute_cmd("list_result_dbs","-j")
    if r is None:
        raise ValueError("Got error code when trying to check which results databases are loaded.")
    err, current_results_dbs = r
    if err:
        raise ValueError(f"Got error code {err} and message '{current_results_dbs}' when trying to check which results databases are loaded.")
    current_results_dbs = json.loads(current_results_dbs)
    
    # check whether this particularly db has already been loaded (if so, we do not want to load it again)
    if db_path in [r['path'] for r in current_results_dbs]:
        logger.info(f"Results database {db_path} has already been loaded - moving on without loading it again.")
        return
    # load the requested results db
    logger.info(f"Opening results database {db_path} for analysis type '{analysis_type.value}'")
    conn.open_result_db(db_path, analysis_type.value)
    time.sleep(3)  # ugh
    
def change_archive_journal_mode_if_necessary(conn:PySynTrack_Interface):
    # changes the sqlite db journal mode to 'delete' to allow camera control to read from the db while syntrack is using it 
    archive_settings = conn.get_archive_settings()
    if archive_settings.get('journalmode') == 'delete':
        logger.info("Archive journal mode is already set correctly - not setting it." )
        return
    logger.info('Setting archive journal mode')
    conn.change_archive_settings(journalmode='delete')

def generate_results_path(analysis_type:ResultsDbType, dirname:str, basedirs:dict[str,str]):
    basedir = basedirs[analysis_type.name]
    return join(basedir, f"{analysis_type.name}_{dirname}_Result.db")
    
def set_syntrack_paths(dirname, conn):
    # PEI: attempt to solve archiving in the wrong dir
    conn.execute_cmd("remove_archive_paths")
    conn.execute_cmd("add_archive_path", dirname)
    logger.info("SynTrack archive path set")

    # Set syntrack metadata filename
    logger.info("Setting SynTrack metadata filename")
    # syntrack_conn.set_metadata_filename('%s/%s' % (dirname, params['metadata_filename']))
    conn.execute_cmd("close_metadata_file")
    conn.execute_cmd(
        "open_metadata_file", os.path.join(dirname, "Metadata.db")
    )
    logger.info("SynTrack metadata filename set")
    time.sleep(1)
    change_archive_journal_mode_if_necessary(conn)

    logger.info(f"Path reset to {dirname}")
    # PEI end---------------
              
with open(get_config_path(), "rb") as f:
    config = tomli.load(f)

AUTOFOCUS_EXEC = config["AUTOFOCUS_EXEC"]
GUIDE_EXPOSURE = config["GUIDE_EXPOSURE"]
GUIDE_DELAY = config["GUIDE_DELAY"]
SKIP_TEMP = config['SKIP_TEMP']
SKIP_SQM = config['SKIP_SQM']
RESULTS_BASEPATHS = config['RESULTS_BASEPATH']  # dict of {<analysis type>: <directory where the results db should live>}

HORIZON_BOX_PATH = config['HORIZON_BOX_PATH']  # path to file that describes the telescope's pointing limits (bounding box / bbox)
BBOX_BUFFER_DEG = config['BBOX_BUFFER_DEG']  # how much to shrink the bbox by as a precaution
BBOX = load_horizon_box(config['HORIZON_BOX_PATH'], config['BBOX_BUFFER_DEG'])

CAM_NAME = config["CAMERA_NAME"]
CAM_CONFIG = config["CAMERAS"][CAM_NAME.upper()]

# start with the parts of the camera config that are assumed to be common to all science subconfigs (mpc, tess, etc) and to recentering
common = CAM_CONFIG.get("COMMON", {})

NON_CAM_PARAM_COLUMNS = config["non_cam_param_columns"]

AUTOFOCUS_CONFIG = CAM_CONFIG["AUTOFOCUS"]  # don't merge config for autofocus

RECENTER_CONFIG = copy.deepcopy(common)
RECENTER_CONFIG.pop('Bin2Fits')  # not a cam param
RECENTER_CONFIG.pop('column_mappings')  # not a cam param
RECENTER_CONFIG.update(CAM_CONFIG["RECENTER"])

recenter_exptime = RECENTER_CONFIG.pop("exptime")

def observe(args):
    scope = Controller(use_guider=True)
    scope.connect(photometrics.TELESCOPE_CONTROLLER)


    port = "/dev/ttyS0"
    linux_dirname = args["directory"]
    logger.info(f"Data saving to directory: {args['directory']}")

    # Begin by importing the exported Scheduler table back in.
    with open(join(linux_dirname, "Scheduler.txt"), "rb") as infile:
        Schedule = ascii.read(infile)

    # Convert time column back into time objects.
    Schedule["DateTimeObj"] = [Time(row["DateTime"]) for row in Schedule]

    # Get windows directory path.
    logger.info("Set SynTrack archive path")
    tmp = abspath(linux_dirname).split("/")
    # dirname = tmp[3] + ':'
    dirname = "{}/{}".format("/media", tmp[3])
    for val in tmp[4:]:
        dirname += "/" + val

    _syntrack_client = PySynTrack_Interface(
        photometrics.SYNTRACK_IP, photometrics.SYNTRACK_PORT
    )

    # after changes to pysyntrack_interface by sage in april 2026, the syntrack client 
    # will only be connected inside this 'with' statement. when we exit the 'with', the client will disconnect
    with _syntrack_client as syntrack_conn:
            
        set_syntrack_paths(dirname, syntrack_conn)

        waiting = 0

        def wrap_ra(ra):
            while ra < 0:
                ra += 360
            while ra > 360:
                ra -= 360
            return ra

        # pre-execution parsing and sanity check
        for row in Schedule:
            target_name = row['Target']
            slew_type = row['Slew']
            slew_type = input_to_enum(slew_type.lower(), 'slew type', SlewType)  # will raise error if can't convert
            
            max_offset_arcmin = config['MAX_OFFSET_ARCMIN']
            max_offset_deg = config['MAX_OFFSET_ARCMIN'] / 60
            
            if slew_type == SlewType.Offset and (np.hypot(float(row['RAOffset']), float(row['DecOffset'])) > max_offset_deg or float(row['RAOffset']) > max_offset_deg or float(row['DecOffset']) > max_offset_deg):
                #pass
                raise ValueError(f"Observation at time {row['DateTime']} has too large of an offset. Max allowed offset is {max_offset_arcmin} arcmin ({max_offset_deg:.4f} deg)")

            # commenting this so that external executables can have any image or slew type that they want  - Sage April 2026
            # if slew_type == SlewType.NoSlew and not row['Image']:
            #     raise ValueError(f"Observation at {row['DateTime']} has no Image flag and does not perform any kind of slew, and so is effectively a no-op. What did you mean by this?")

        for row in Schedule:
            target_name = row["Target"]
            while True:
                if Time.now() < row["DateTimeObj"] - 30 * u.second:
                    if not waiting % 15:
                        logger.info(f"Waiting until {row['DateTimeObj']-30*u.second}")
                    waiting += 1
                    time.sleep(1)
                    continue
                    
                elif Time.now() > row["DateTimeObj"]:
                    logger.info(f'{target_name} is no longer observable.')
                    break

                # it's within 30 seconds of the observation and we have not missed it. time to observe
                obs_cfg_name = row['Config']
                try:
                    if obs_cfg_name == "NONE":
                        _obs_cfg = {}
                    else:
                        _obs_cfg = CAM_CONFIG[obs_cfg_name]
                except KeyError as e:
                    raise KeyError(f"Could not find schedule-specified config '{obs_cfg_name}' in the config for camera {CAM_NAME.upper()}") from e
                
                logger.info(f"Observing target {target_name} with config '{obs_cfg_name}'")
                
                # load row-specific overrides that will be applied to the config
                # by default the overrides will be '{}' which will parse to empty dict, which won't change the config 
                cfg_overrides = row['CfgOverrides']
                try:
                    cfg_overrides = tomli.loads('overrides = ' + cfg_overrides)['overrides']
                except tomli.TOMLDecodeError as e:
                    raise tomli.TOMLDecodeError(f"Couldn't parse config override '{cfg_overrides}' for target {target_name}: {e}")
                
                # start with the common config as the baseline
                OBS_CONFIG = copy.deepcopy(common)
                # add/overwrite with the keys from this observation's chosen config
                OBS_CONFIG.update(_obs_cfg)
                # add/overwrite with the observation's config overrides
                OBS_CONFIG.update(cfg_overrides)
                
                # pop removes the key from the config while returning its value, 
                # which we need to do so that we dont pass 'Bin2Fits' to SynTrack (will cause SynTrack error)
                doB2F = bool(OBS_CONFIG.pop('Bin2Fits'))
                logger.info(f'Will {"" if doB2F else "not " }perform Bin2Fits on target {target_name}.')

                doGuide = bool(OBS_CONFIG.pop('guiding'))
                logger.info(f'Will {"" if doGuide else "not " }guide on target {target_name}.')
                
                slew_type = input_to_enum(row['Slew'].lower(), 'slew type', SlewType)  # will raise error if can't convert
                
                analysis = OBS_CONFIG.pop('analysis',{})
                if analysis:
                    valid_analysis_keys = ['analysis_type', 'analysis_queue_max_size']
                    for key in analysis.keys():
                        assert key in valid_analysis_keys, f"Analysis key {key} is invalid. Valid analysis keys are {valid_analysis_keys}"
                
                COL_MAPPINGS = OBS_CONFIG.pop("column_mappings",{})
                archive_mode = OBS_CONFIG.pop('archive_mode','AlwaysArchive')
                
                cam_params = copy.deepcopy(OBS_CONFIG)
                # some of the parameters need to be renamed from their scheduler column names to names that syntrack expects
                for colname in row.colnames:
                    if colname not in NON_CAM_PARAM_COLUMNS:  # only some of the columns (if any) in the scheduler are actually camera parameters
                        val = row[colname]
                        colname = COL_MAPPINGS.get(colname, colname)
                        cam_params[colname] = val
                        
        # ---------------------------------- Autofocus --------------------------------------------------
                if row["Target"] == "Focus":
                    logger.info("Refocusing...")
                    now = datetime.now()
                    suffix = now.strftime("%Y-%m-%dT%H:%M:%S")
                    os.system(f'autofocus --prefix focusloop_{suffix}')
                    logger.info("Done refocusing.")

                    break
                
        # --------------------------- Homing Dome ---------------------------------------
                if row["Target"] == "DomeHome":
                    logger.info("Sending the dome home...")
                    logger.info("Unlinking dome")
                    for i in range(3):
                        scope.unlink_dome()
                        time.sleep(3)
                        if not scope.is_dome_linked():
                            logger.info(f"Dome unlinked.")
                            break
                        logger.warning("Failed to unlink dome. Trying again.")
                    assert not scope.is_dome_linked(), "Could not unlink dome!"
                    logger.info("Homing the dome")
                    scope.go_to_dome_home()
                    time.sleep(5)
                    i = 0
                    while scope.is_dome_slewing():
                        i += 1
                        time.sleep(5)
                        if i == 36:
                            logger.error("Waited for dome to home for 3 minutes but it seems to still be slewing! Continuing as if it has homed successfully...")
                    logger.info("Dome arrived home.")
                    logger.info("Linking dome")
                    for i in range(3):
                        scope.link_dome()
                        time.sleep(3)
                        if scope.is_dome_linked():
                            logger.info(f"Dome linked.")
                            break
                        logger.warning("Failed to link dome. Trying again.")
                    assert scope.is_dome_linked(), "Could not link dome!"
                    logger.info("Done homing dome.")
                    
                    break    
        # --------------------------- External Command Execution ---------------------------------------
                # PEI: added this elif Apr 2024 to handle future script integration
                if row["Target"] == "External_Single":
                    # set_syntrack_paths(dirname)
                    logger.info("Running a single-line external command...")
                    logger.info(f"Running external command:\n{row['Description']}")
                    shell_cmd = row["Description"]
                    os.system(shell_cmd)
                    logger.info("Completed external executable.")
                    break

        # --------------------------- External Script Execution ---------------------------------------
                # PEI: added this elif June 2024 to handle future script integration
                if row["Target"] == "External_Executable":
                    # set_syntrack_paths(dirname)

                    logger.info(f"Running external executable:\n{row['Description']}")

                    executable = row["Description"]

                    # os.system(shell_cmd)
                    with open(executable, "r") as file:
                        for line in file:
                            try:
                                subprocess.run(line, shell=True)
                                logger.info("Completed external executable.")
                            except subprocess.CalledProcessError as e:
                                logger.error(
                                    f"Command '{line.strip()}' failed with error: {e}"
                                )
                    break

        # ------------------------------- Move the telescope if needed ----------------------------------
                if slew_type != SlewType.NoSlew:
                    #set_syntrack_paths(dirname)
                    
                    # ====================== direct slew, blind slew, or indirect slew ===========================
                    if slew_type in [SlewType.Blind, SlewType.Direct, SlewType.Indirect]:
                        ra = float(row["RA"])
                        if ra < 0:
                            ra += 360
                        if ra > 360:
                            ra -= 360
                        dec = float(row["Dec"])

                        (ra0, dec0) = scope.get_ra_dec()
                        if zenith_slew_required(BBOX, ra0, dec0, ra, dec, current_dt_utc()):   
                            logger.info("Zenith parking before next slew.")
                            scope.go_to_zenith()
                            time.sleep(20.0)
                            logger.info("Zenith parked.")
                        else:
                            logger.info(f'No zenith slew required when moving between ({ra0:.2f},{dec0:.2f}) and ({ra:.2f},{dec:.2f}).')

                        logger.info(f'Target name: {row["Target"]}')
                        logger.info(f"Moving to coordinates: ({ra},{dec})")
                        scope.ra_dec(ra, dec)
                        # 				time.sleep(5.0)

                        ######## NEW filter wheel control integration - Nez July 2023
                        fw = FLIFilterWheel()
                        fw.connect()

                        if fw.num_filter_wheels > 0:
                            fw.set_filter_name(row["Filter"])
                            filter_name = fw.get_filter_name()
                            logger.info(f"Filter set to : '{filter_name}'")
                        else:
                            logger.error("No FLI filter found")
                        ######## Filter wheel integration above

                        if slew_type == SlewType.Blind:
                            logger.info("Not recentering")
                        else:
                            # set_syntrack_paths(dirname)
                            logger.info("Re-centering...")
                            recenter_and_capture(
                                linux_dirname, 1, 1, "Re-Center", "Re-Center", recenter_exptime, syntrack_conn, scope, skip_temp=SKIP_TEMP, skip_sqm=SKIP_SQM,
                                do_bin2fits=False, filter_name=row["Filter"], skip_bkg=False, **RECENTER_CONFIG,
                            )  # passing in **RECENTER_CONFIG sets pix scale and binning to whatever its set to in the utility profile, plus sets other camera params

                        # Perform indirect slew - Sage SP2026
                        if slew_type == SlewType.Indirect:
                            # we want to slew to a bright target at position X, but we can't perform recentering
                            # there because it's too bright. instead, we slew to a nearby position A, recenter there,
                            # and then do a blind slew from point A to point X (the assumption being that the slew error is
                            # related to the slew duration so is lower going from point A to X than from far away).
                            
                            # we have faced difficulty applying offsets directly because of unknown ACE software or hardware limitations,
                            # so I'm implementing this workaround

                            # the plan is as follows:
                                # instruct the telescope to slew to position A (completed)
                                # the telescope attempts this and instead ends up at some other position B, which it thinks is A (completed)
                                # recentering brings the telescope from position B to position A. (completed)
                                # the telescope then thinks that it's at position C = B + (B-A)
                                # we then ask the telescope to slew to the position D = (X-A) + C
                                    # this has the effect of applying the required offset (X-A) to the position that the telescope 
                                    # thinks that it is at, prompting the scope to apply the correct offset 
                            
                            # set_syntrack_paths(dirname)
                            ra_offset = float(row["RAOffset"])
                            dec_offset = float(row["DecOffset"])
                            
                            # the target ra, dec
                            X_ra = wrap_ra(ra + ra_offset)
                            X_dec = dec + dec_offset
                            
                            # naive ra, dec where the scope thinks it currently is
                            (C_ra, C_dec) = scope.get_ra_dec()
                            
                            A_ra, A_dec = get_astrometric_pos(
                                linux_dirname, recenter_exptime, syntrack_conn, scope, skip_temp=SKIP_TEMP, skip_sqm=SKIP_SQM,
                                filter_name=row["Filter"], skip_bkg=False, **RECENTER_CONFIG,
                            )
                            
                            if A_ra is None or A_dec is None:
                                logger.error("Couldn't determine actual astrometric position when performing offset. adopting commanded pre-slew position as truth. slew accuracy will be degraded as a result.")
                                A_ra = ra
                                A_dec = dec
                                
                            D_ra = X_ra - A_ra + C_ra
                            D_dec = X_dec - A_dec + C_dec
                            
                            logger.info(f"Commanded (pre-offset) position: {ra,dec}")
                            logger.info(f"Astrometrically-derived post-offset position (A): {A_ra,A_dec}")
                            logger.info(f"Desired post-offset position (X): {X_ra,X_dec}")
                            logger.info(f"Current naive (scope-derived) position (C): {C_ra, C_dec}")
                            logger.info(f"Next slew position (D): {D_ra, D_dec}")
                            logger.info("Slewing...")
                            scope.ra_dec(D_ra, D_dec)

                            logger.info("Done with offset.")

                    # =============== not a slew but an offset =================
                    elif slew_type == SlewType.Offset:
                        ra_offset = float(row["RAOffset"])
                        dec_offset = float(row["DecOffset"])
                        logger.info(f"Performing ({ra_offset*60:.2f}, {dec_offset*60:.2f}) arcmin offset.")
                        scope.offset(ra_offset, dec_offset)
                        time.sleep(config['OFFSET_SETTLE_TIME'])

        # ------------------------------- Take data ----------------------------------
                if row['Image']:
                                    
                    # set_syntrack_paths(dirname)
                    exptime = float(str(row["ExposureTime"]))
                    nframes = int(row["#Exposure"])  # MUST be an integer
                        
                    cfg_compression_level = OBS_CONFIG.get("CompressionLevel", CompressionLevel.NoCompression)
                    compression_level = input_to_enum(cfg_compression_level, 'compression level', CompressionLevel, default_val=CompressionLevel.NoCompression)
                    
                    if doGuide:
                        logger.info("Initiating guiding...")
                        scope.guider.start(GUIDE_EXPOSURE, GUIDE_DELAY, 100)
                        
                    # get the sequence length if we're taking multiple datasets 
                    sequence_length = None
                    row_seq = row.get("Seq",1)
                    if row_seq > 1:
                        sequence_length = int(row_seq)
                    
                    perform_analysis = bool(analysis)  # if we got an analysis dict from the config, we are performing analysis
                    if perform_analysis:
                        analysis_type = analysis.get('analysis_type')
                        if analysis_type is None:
                            raise ValueError(f'{row["Target"]} row has analysis True but is missing an analysis_type config keyword!')
                        
                        results_type = ResultsDbType[analysis_type] 
                        linux_dirname_base = linux_dirname.split(os.sep)[-1]  # this will be something like '20260424'
                        results_db_path = generate_results_path(results_type, linux_dirname_base, RESULTS_BASEPATHS)
                        load_results_db_if_not_open(results_db_path,results_type,syntrack_conn)
                    
                    logger.info("Acquiring science data...")
                    capture_single(
                        linux_dirname,
                        exptime,
                        nframes,
                        row["Target"],
                        row["Description"],
                        syntrack_conn,
                        scope=scope,
                        do_bin2fits=doB2F,
                        filter_name=row["Filter"],
                        skip_temp=SKIP_TEMP,
                        skip_sqm=SKIP_SQM,
                        sequence_length=sequence_length,
                        archive_mode=archive_mode,
                        compression_level=compression_level,
                        perform_analysis=perform_analysis,
                        **analysis,
                        **cam_params,
                    )

                    if doGuide:
                        logger.info("Stopping guider...")
                        scope.guider.stop()
                    logger.info(f"Exposed for {float(exptime)*float(nframes)} seconds.")        

                break
    # ---------------------Sanity Checks---------------------------

from photometrics.camera_control import __get_sky_background
from photometrics.sqm import SQM

# from photometrics.utils import get_sidereal_time
# from tcs.telemetry import RoofStatus, Weather, Seeing, SkyBrightness

def main():
    parser = argparse.ArgumentParser(description="TMO Automation Code")
    # parser.add_argument('directory', type=str, help="Input/Output directory")
    parser.add_argument(
        "--directory",
        default=os.getcwd(),
        type=str,
        help="target directory; default to curent working directory",
    )
    args = vars(parser.parse_args())
    observe(args)

if __name__ == "__main__()":
    main()
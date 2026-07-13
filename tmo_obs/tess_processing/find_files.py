import sys, os
from os.path import join
from rich import print as rprint
from typing import Callable, Dict
import functools

from tmo_obs.tess_processing.database.metadata import MetadataDat, MetadataDB, get_obs_details
    
def is_dark(obs_details:dict):
    if "FILTER" not in obs_details: return False
    return obs_details['FILTER'] == 'DARK' and obs_details['ExposureTime'] > 0 and 'dark' in obs_details['Name'].lower()

def is_bias(obs_details:dict):
    if "FILTER" not in obs_details: return False
    return obs_details['FILTER'] == 'DARK' and obs_details['ExposureTime'] == 0 and "bias" in obs_details['Name'].lower()

def is_flat(obs_details:dict):
    if "FILTER" not in obs_details: return False
    return obs_details['FILTER'] != 'DARK' and obs_details['ExposureTime'] > 0 and "twilight" in obs_details['Name'].lower()

def is_calib(obs_details:dict):
    return is_flat(obs_details) or is_bias(obs_details) or is_dark(obs_details)

def is_science(obs_details):
    name = obs_details['Name']
    return not is_calib(obs_details) and "re-center" not in name.lower() and 'recenter' not in name.lower() and 'focusloop' not in name.lower() and 'focusloop' not in obs_details['Description'].lower()

def has_matching_camera_configuration(details_1:dict, details_2:dict):
    for k in ['Camera Name','Binning Size','ROI_StartX','ROI_StartY','ROI_Width','ROI_Height']:
        if details_1.get(k) != details_2.get(k):
            return False
    for k in ['Binning Mode','Operation Mode','Gain']:
        if details_1['cam_params'].get(k) != details_2['cam_params'].get(k):
            return False
    return True
    
def bias_matches(bias_details:dict,obs_details:dict):
    return is_bias(bias_details) and has_matching_camera_configuration(bias_details, obs_details)

def dark_matches(exptime_tolerance:float, dark_details:dict, obs_details:dict):
    if not is_dark(dark_details) or not has_matching_camera_configuration(dark_details, obs_details):
        return False 
    return abs(dark_details['ExposureTime'] - obs_details['ExposureTime']) <= exptime_tolerance

def flat_matches(flat_details:dict, obs_details:dict):
    if not is_flat(flat_details) or not has_matching_camera_configuration(flat_details, obs_details):
        return False
    if not flat_details.get('FILTER') or not obs_details.get('FILTER'):
        return False
    return flat_details['FILTER'] == obs_details['FILTER'] 
     
def find_matching_rows(criteria:Callable[dict,dict],obs_details:dict,cal_metadata_db:MetadataDB,cal_md_dat:MetadataDat):
    res = cal_metadata_db.query(f"SELECT * FROM DatasetMetaData")
    if not len(res):
        print('No files in db')
        return None
    
    rows = [get_obs_details(r,cal_metadata_db,cal_md_dat) for r in res]
    matching = []
    for r in rows:
        if criteria(r,obs_details):
            matching.append(r)
    if not len(matching):
        return None
    return matching

if __name__ == '__main__':
    from find_tess import find_all_tess_obs
    import argparse
    parser = argparse.ArgumentParser(description="Get information about TESS datasets from a metadata db/dat pair")
    
    parser.add_argument('dir', type=str, nargs='?', default=os.getcwd(), help="Target directory, defaults to cwd. Not necessary if both --db and --dat are provided.")    

    args = parser.parse_args()
    base_dir = args.dir or os.getcwd()
    calib_dir = join(base_dir,'Calibs')
    
    obs_dat = MetadataDat(base_dir)
    with MetadataDB(base_dir) as db:
        tess_row = find_all_tess_obs(db)[0]
        tess_details = get_obs_details(tess_row,db,obs_dat)
    rprint(tess_details)
    calib_dat = MetadataDat(calib_dir)
    with MetadataDB(calib_dir) as db:
        bias_rows = find_matching_rows(bias_matches,tess_details,db,calib_dat)
        f_dark_match = functools.partial(dark_matches,0)
        dark_rows = find_matching_rows(f_dark_match,tess_details,db,calib_dat)
    
    rprint(bias_rows)
    rprint(dark_rows)
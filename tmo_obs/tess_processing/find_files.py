import sys, os
from os.path import join
from rich import print as rprint
from typing import Callable, Dict

from tmo_obs.tess_processing.database.metadata import MetadataDat, MetadataDB, get_obs_details
    
def is_dark(md_row):
    pass

def is_bias(obs_details:dict):
    # print(f"{obs_details['Name']} is a bias: {obs_details['FILTER'] == 'DARK' and obs_details['ExposureTime'] == 0 and 'bias' in obs_details['Name'].lower()}")
    # print(f"\t Filter is DARK: {obs_details['FILTER'] == 'DARK'}")
    # print(f"\t Exptime is zero: {obs_details['ExposureTime'] == 0}")
    # print(f"\t Bias in name: {obs_details['Name'].lower()}")
    if "FILTER" not in obs_details: return False
    return obs_details['FILTER'] == 'DARK' and obs_details['ExposureTime'] == 0 and "bias" in obs_details['Name'].lower()

def is_flat(md_row):
    pass
    
def bias_matches(bias_details:dict,obs_details:dict):
    print('')
    if not is_bias(bias_details):
        return False
    for k in ['Camera Name','Binning Size','ROI_StartX','ROI_StartY','ROI_Width','ROI_Height']:
        if bias_details.get(k) != obs_details.get(k):
            # print(f'{k} does not match for datasets: {bias_details.get(k)} != {obs_details.get(k)}' )
            return False
    for k in ['Binning Mode','Operation Mode','Gain']:
        if bias_details['cam_params'].get(k) != obs_details['cam_params'].get(k):
            # print(f"{k} does not match for datasets: {bias_details['cam_params'].get(k)} != {obs_details['cam_params'].get(k)}")
            return False
    return True
    
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

# def find_matching_dark_row(obs_row,cal_metadata_db:MetadataDB,cal_md_dat_path):
if __name__ == '__main__':
    from find_tess import find_all_tess_obs
    import argparse
    parser = argparse.ArgumentParser(description="Get information about TESS datasets from a metadata db/dat pair")
    
    parser.add_argument('--dir', type=str, default=None, help="Target directory, defaults to cwd. Not necessary if both --db and --dat are provided.")    

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
    
    rprint(bias_rows)
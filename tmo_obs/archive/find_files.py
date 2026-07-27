import sys, os
from os.path import join
from rich import print as rprint
from typing import Callable, Dict
import functools

from tmo_obs.archive.calibs import bias_matches, dark_matches
from tmo_obs.archive.database.metadata import MetadataDat, MetadataDB, get_obs_details
    
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
    from tmo_obs.tess_processing.find_tess import find_all_tess_obs
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
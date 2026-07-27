import sys, os
from os.path import abspath, relpath, basename
import argparse
import rich
from rich import print as rprint, box
from rich.panel import Panel 
from rich.table import Table
from datetime import timedelta
from sqlalchemy import select

from .queries import flexible_dataset_select, matches_configuration_stmt, darks_for_obs_stmt, biases_for_obs_stmt, flats_for_obs_stmt
from tmo_obs.config import load_config
from .database import DEFAULT_DB_PATH, get_record_db, Observation
from .database.utils import guess_binfile_path

def main():
    # locate the dataset the user is referring to from cmdline args
    parser = argparse.ArgumentParser(description="Find calibrations for a given observation")
    obs_group = parser.add_argument_group('Observation', "Identifiers to locate the observation. One or more must be provided")
    obs_group.add_argument('--fits',type=str, default=None, help='Name of a fits file')
    obs_group.add_argument('--name',type=str, default=None, help='Name of an observation')
    obs_group.add_argument('--bin',type=str, default=None, help='path to a bin file')
    
    obs_group.add_argument('--fuzzy',action="store_true", help='Match observation with name/filepath that contains the provided name/filepath, instead of requiring exact match. default: False')

    parser.add_argument('--exptime-tolerance',type=float, default=0.0, help='Allow exposure times of matched darks to vary by up to this amount, in seconds. Default 0')
    parser.add_argument('--date-tolerance',type=float, default=None, help='Allow the difference between the the date that the data was taken and the date that the calibs were taken to be up to this amount, in days. Default: unlimited')
    parser.add_argument('--db', type=str, default=None, help="Path to master records db. If not provided, looks in config for 'obs_db_path' key and then for default db name")

    args = parser.parse_args()
    
    if args.fits is None and args.bin is None and args.name is None:
        parser.error("Must provide at least one of --fits, --name, or --bin")
        
    if args.bin is not None: 
        args.bin = basename(args.bin)
        
    if args.fits is not None and not args.fuzzy: 
        args.fits = abspath(args.fits)
    
    obs_db_path = args.db
    DATA_BASE_DIR = None
    try:
        config = load_config()
    except:
        config = {}
    
    DATA_BASE_DIR = config.get('DATA_BASE_DIR', None)
            
    if obs_db_path is None:
        obs_db_path = config.get('obs_db_path', DEFAULT_DB_PATH)
        print(f'Using db {obs_db_path}')
    
    with get_record_db(obs_db_path) as db:
        # get obs that could match the one the user is inquiring about
        observations = db.execute(
            flexible_dataset_select(fits_filename=args.fits,name=args.name,bin_filename=args.bin,exact=not args.fuzzy)
        ).scalars().all()
        if not len(observations):
            print("ERROR: no observation matching the provided identifier(s) exists.")
            return 1
        if len(observations) > 1:
            print("ERROR: provided identifiers matched more than one dataset:")
            for o in observations:
                print(f"#{o.id} {o.name}")
            return 1
        obs = observations[0]
        
        exp_tol = args.exptime_tolerance
        dt_tol = args.date_tolerance
        
        msg = f"Matching: Obs #{obs.id} {obs.name} ({obs.exptime:.2f}s, {obs.obstime.isoformat(timespec='seconds')})\n"
        msg += f"Taken: Between {(obs.obstime-timedelta(days=args.date_tolerance)).isoformat(timespec='minutes')} and {(obs.obstime+timedelta(days=args.date_tolerance)).isoformat(timespec='minutes')}\n" if dt_tol is not None else "Taken: Any time\n"
        msg += f"Exposure time: {obs.exptime:.2f}s" if exp_tol == 0 else f"Exposure time: {(obs.exptime - exp_tol):.2f}s to {(obs.exptime + exp_tol):.2f}s"
        rprint(Panel.fit(msg,title='Search'))
        
        # find the matching calibs
        stmt = darks_for_obs_stmt(obs, time_tolerance_days=args.date_tolerance, exptime_tolerance_s=args.exptime_tolerance)
        dark = db.execute(stmt.limit(1)).scalars().one_or_none()
        
        stmt = flats_for_obs_stmt(obs, time_tolerance_days=args.date_tolerance)
        flat = db.execute(stmt.limit(1)).scalars().one_or_none()
        
        
        stmt = biases_for_obs_stmt(obs, time_tolerance_days=args.date_tolerance)
        bias = db.execute(stmt.limit(1)).scalars().one_or_none()
        
        table = Table('Calib','Name','Date','Exptime','File',box=box.SIMPLE)
        
        for calib, cname in zip((dark,flat,bias),('Dark','Flat','Bias')):
            if calib is None:
                table.add_row(cname,'Not Found','-','-','-')
            else:
                file = calib.fits_files[0].filepath if len(calib.fits_files) else guess_binfile_path(calib)
                if DATA_BASE_DIR is not None:
                    file = relpath(file,DATA_BASE_DIR)
                table.add_row(cname,calib.name,calib.obstime.isoformat(timespec='minutes'),f"{calib.exptime:.2f}",file)
        rprint(table)

if __name__ == "__main__":
    sys.exit(main())
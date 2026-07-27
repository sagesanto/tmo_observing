import sys, os
from os.path import abspath, relpath, basename
import argparse
import rich
from rich import print as rprint, box
from rich.panel import Panel 
from rich.table import Table
from datetime import timedelta

from .queries import flexible_dataset_select, matches_configuration_stmt, darks_for_obs_stmt, biases_for_obs_stmt, flats_for_obs_stmt
from sqlalchemy import select
from tmo_obs.config import load_config
from .database import DEFAULT_DB_PATH, get_record_db, Observation
from .database.utils import guess_binfile_path

def main():
    # locate the dataset the user is referring to from cmdline args
    parser = argparse.ArgumentParser(description="Find a dataset given identifying information")
    obs_group = parser.add_argument_group('Observation', "Identifiers to locate the observation. One or more must be provided")
    obs_group.add_argument('--fits',type=str, default=None, help='Name of a fits file')
    obs_group.add_argument('--name',type=str, default=None, help='Name of an observation')
    obs_group.add_argument('--bin',type=str, default=None, help='path to a bin file')
    
    obs_group.add_argument('--fuzzy',action="store_true", help='Match observation with name/filepath that contains the provided name/filepath, instead of requiring exact match. default: False')

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
            flexible_dataset_select(fits_filename=args.fits,
                                    name=args.name,
                                    bin_filename=args.bin,
                                    exact=not args.fuzzy
            ).order_by(Observation.obstime.desc())
        ).scalars().all()
        
        if not len(observations):
            print("No observation matching the provided identifier(s) exists.")
            return 0
        
        table = Table('Type','Name','Date','File',box=box.SIMPLE)
        
        for obs in observations:
            if obs is None:
                table.add_row('NONE','Not Found','-','-')
            else:
                if obs.is_science:
                    dtype = "SCIENCE"
                elif obs.is_bias:
                    dtype = "BIAS"
                elif obs.is_dark:
                    dtype = "DARK"
                elif obs.is_flat:
                    dtype = "FLAT"
                else:
                    dtype = "OTHER"
                file = obs.fits_files[0].filepath if len(obs.fits_files) else guess_binfile_path(obs)
                if DATA_BASE_DIR is not None:
                    file = relpath(file,DATA_BASE_DIR)
                table.add_row(dtype,obs.name,obs.obstime.isoformat(timespec='minutes'),file)
        rprint(table)

if __name__ == "__main__":
    sys.exit(main())
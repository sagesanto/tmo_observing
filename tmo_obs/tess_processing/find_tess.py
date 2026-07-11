import sys, os
from os.path import join, dirname, abspath, exists, splitext, basename
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import json
import sqlite3
from rich import print as rprint

from tmo_obs.tess_processing.database.metadata import MetadataDat, MetadataDB, get_obs_details, read_schedule

def find_all_tess_obs(db:MetadataDB):
    return db.query("SELECT * FROM DatasetMetaData WHERE substr(Name,1,4) = 'TESS' AND Name NOT LIKE '%recenter%'")

def find_tess_obs_by_name(db:MetadataDB,name_fragment):
    res = db.query(f"SELECT * FROM DatasetMetaData WHERE substr(Name,1,4) = 'TESS' AND Name NOT LIKE '%recenter%' and Name LIKE '%{name_fragment}%'")
    return res

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Get information about TESS datasets from a metadata db/dat pair")
    
    parser.add_argument("names",nargs='*', help='Names of targets. If none, will provide detail on all TESS targets found')
    parser.add_argument('--db', type=str, default=None, help="DB filepath. If not provided, assumes one called 'Metadata.db' exists in the target directory")    
    parser.add_argument('--dat', type=str, default=None, help="Metadata dat filepath. If not provided, looks for  one called 'Metadata.dat' in the target directory")    
    parser.add_argument('--schedule', type=str, default=None, help="Schedule filepath. If not provided, looks for one called 'Scheduler.txt' in the target directory")    
    parser.add_argument('--dir', type=str, default=None, help="Target directory, defaults to cwd. Not necessary if both --db and --dat are provided.")    

    args = parser.parse_args()
    
    directory = args.dir or os.getcwd()
    db_path = args.db or join(directory,'Metadata.db')
    if not exists(db_path):
        print(f"No such metadata database {db_path}")
        sys.exit(1)
    
    dat = None
    dat_path = args.dat
    if not args.dat and exists(join(directory,'Metadata.dat')): 
        dat_path = join(directory,'Metadata.dat')
    if dat_path:
        dat = MetadataDat(dat_path)
    
    schedule = None
    schedule_path = args.schedule
    if not schedule_path and exists(join(directory,'Scheduler.txt')): 
        schedule_path = join(directory,'Scheduler.txt')
    if schedule_path:
        schedule, _ = read_schedule(schedule_path)
        
    with MetadataDB(db_path) as db:
        if len(args.names):
            rows = []
            for n in args.names:
                r = find_tess_obs_by_name(db,n)
                if not len(r):
                    print(f'{n}: Not found.')
                else:
                    rows.extend(r)
        else:
            rows = find_all_tess_obs(db)
        if not len(rows):
            print("No TESS targets found. Names of TESS targets must start with 'TESS' and must not contain the word 'recenter'.")
            exit(1)

        for row in rows:
            rprint(get_obs_details(row,db,dat,schedule,directory=directory))

if __name__ == "__main__":
    main()
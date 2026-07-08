import sys, os
from os.path import join, dirname, abspath, exists, splitext, basename,isdir
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import json
import sqlite3
from pytz import timezone
from datetime import datetime

from tmo_obs.utils import parse_date_obs, write_date_obs

# what info do we care about?
DAT_KEYWORDS = ['FILTER','RAWX','RAWY','Temperature','Sky','Focus']
DB_KEYWORDS = ['Name','rowid','Description','ExposureTime','Frames','BinningSize','ROI_Width','ROI_Height','TelescopeRA','TelescopeDEC','ROI_StartX','ROI_StartY','Temperature','CameraName']

def res_rows_to_dicts(row):
    dictionary = [dict(r) for r in row if r]
    return [{k: v for k, v in a.items() if v is not None} for a in dictionary if a]

def parse_camera_param(value, value_type):
    try:
        if value_type == "Single" or value_type=="Double":
            return float(value)
        if 'int' in value_type.lower():
            return int(value)
        if value_type == 'Boolean':
            return True if value=='true' else False
    except:
        pass
    return value  # default to returning as string

def read_metadata_dat(fpath):
    with open(fpath,'r') as f:
        lines = f.readlines()
    header = [h for h in lines[1].strip().replace('## ','').split(' ') if h]
    return pd.read_csv(fpath,sep='\t',comment='#',header=None,names=header)

def acq_bin_filename(obs_row):
    return f"{obs_row['AcqSystemID']}_{obs_row['AcqTimestamp']}_{obs_row['AcqNum1']}_{obs_row['AcqNum2']}.bin"

def utc_obs_timestamp(obs_row) -> float:
    ts = obs_row['AcquisitionTime'] + obs_row['AcquisitionTimeNs'] * 1e-9
    return datetime.fromtimestamp(ts, tz=timezone('US/Pacific')).astimezone(timezone('UTC')).timestamp()

def utc_obs_datetime(obs_row) -> datetime:
    return datetime.fromtimestamp(utc_obs_timestamp(obs_row),tz=timezone('UTC'))

def utc_obs_time(obs_row) -> str:
    return write_date_obs(utc_obs_datetime(obs_row))

class MetadataDat:
    def __init__(self,fname):
        if isdir(fname):
            fname = join(fname,'Metadata.dat')
        self.fname = abspath(fname)
        self.df = read_metadata_dat(self.fname)
    
    def get_obs(self,filename):
        rows = self.df[self.df['FileName'] == filename]
        if not len(rows):
            return None
        return [dict(r) for _,r in rows.iterrows()][0]
            

class MetadataDB:
    def __init__(self, db_file, check_same_thread=True, read_only=True):
        if isdir(db_file):
            db_file = join(db_file,'Metadata.db')
        self.fname = abspath(db_file)
        self.cur = None
        self.conn = None
        self.check_same_thread = check_same_thread
        self.read_only = read_only
    
    @property
    def is_connected(self):
        return self.cur is not None
    
    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
            
    def open(self, **kwargs):
        if not exists(self.fname):
            raise FileNotFoundError(f"Could not find file '{self.fname}'")

        det_types = sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        if "detect_types" in kwargs:
            det_types = kwargs["detect_types"] | sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
            del kwargs["detect_types"]
            
        if self.read_only:
            self.conn = sqlite3.connect(f'file:{self.fname}?mode=ro', uri=True, check_same_thread=self.check_same_thread, detect_types=det_types, **kwargs)
        else:
            self.conn = sqlite3.connect(self.fname, check_same_thread=self.check_same_thread, detect_types=det_types, **kwargs)
        
        self.conn.row_factory = sqlite3.Row
        self.cur = self.conn.cursor()
    
    def close(self):
        if self.is_connected:
            self.conn.close()
            self.cur = None
            self.conn = None 
            
    def query(self, query_text):
        self.cur.execute(query_text)
        rows = self.cur.fetchall()
        return res_rows_to_dicts(rows)

    def find_cam_metadata(self,row_id,parse=False):
        rows = self.query(f"SELECT * FROM DatasetMetaData_CameraParameters WHERE MetaDataRowID = {row_id}")
        md = {}
        for row in rows:
            key = row['Name']
            value = row['Value']
            if parse:
                value = parse_camera_param(value,row['ValueType'])
            md[key] = value
        return md

def extract_dat_md(obs_row,dat:MetadataDat,dat_kwords=None):
    if dat_kwords is None:
        dat_kwords = DAT_KEYWORDS
    # have to search by bin file, unfortunately
    fname = acq_bin_filename(obs_row)
    row = dat.get_obs(fname)
    if row is None: return {}
    return dict(**{k:row.get(k) for k in dat_kwords})

def read_schedule(fpath) -> tuple[list[dict],list[str]]:
    with open(fpath,'r') as f:
        lines = [l.strip() for l in f.readlines() if l.strip()]
    header = lines[0].split('|')
    l_dicts = [dict({'path':fpath},**dict(zip(header,l.split('|')))) for l in lines[1:]]
    return l_dicts, lines

def find_schedule_line(obs_row,schedule:list[dict],time_tolerance_minutes=2):
    # find the line in a schedule text file that matches an observation pulled from the metadata db

    name_match = [d for d in schedule if d['Target'] in obs_row['Name']]
    if not len(name_match):
        print('No schedule lines with matching name')
        return None

    obs_ts = utc_obs_timestamp(obs_row)
    line_timestamps = np.array([parse_date_obs(d['DateTime']).timestamp() for d in name_match])
    time_match = [(d,t) for d,t in zip(name_match,line_timestamps) if abs(obs_ts-t)/60 < time_tolerance_minutes]
    if len(name_match) and len(time_match) == 0:
        print(f"Found schedule line(s) with matching name but at the incorrect time for observation '{obs_row['Name']}'. Not keeping them.")
        return None    
    
    # find the line with closest matching time
    idx = np.argmin(np.abs(np.array([t for d,t in time_match])-obs_ts))
    d,t = time_match[idx]
    d['schedule_idx'] = int(idx)
    return d

def get_obs_details(obs_row:dict,db:MetadataDB,dat:MetadataDat=None,schedule:list[dict]=None,dat_kwords=None,db_kwords=None,directory=None):
    # providing a directory doesn't change the behavior, just tells us where the data is
    # if not provided, we try to infer it
    if db_kwords is None:
        db_kwords = DB_KEYWORDS
    info = {k:obs_row.get(k) for k in db_kwords}
    info['CamTemperature'] = info.get('Temperature')
    del info['Temperature']
    
    info['datetime'] = utc_obs_datetime(obs_row)
    info['obs_time'] = utc_obs_time(obs_row)
    info['timestamp'] = utc_obs_timestamp(obs_row)
    
    dir_inferred = directory is None
    
    if dir_inferred: 
        # these are only used to see if they agree and infer a dir. not used elsewhere
        db_directory = dirname(abspath(db.fname))
        dat_directory = dirname(abspath(dat.fname)) if dat else db_directory
        if dat_directory == db_directory:
            directory = db_directory
        else:
            print(f'db directory ({db_directory}) and .dat directory ({dat_directory}) do not match. Assuming metadata db is correct.')
            directory = db_directory
            
    bin_name = abspath(join(directory,acq_bin_filename(obs_row)))
    info['bin_filename'] = bin_name
    info['bin_file_exists'] = exists(bin_name)
    # if not exists(bin_name):
    #     print(f"Warning: Can't actually locate the bin file '{bin_name}'{' (directory inferred)' if dir_inferred else ''}. Proceeding anyway.")
    
    info['metadata_db_path'] = db.fname
    if dat is not None:
        info['metadata_dat_path'] = dat.fname
        md = extract_dat_md(obs_row,dat,dat_kwords)
        info.update(md)
    if schedule is not None:
        sched_line = find_schedule_line(obs_row,schedule)
        if sched_line:
            info['schedule_path'] = sched_line.pop('path')
        info['schedule_line'] = sched_line
    cam_params = db.find_cam_metadata(obs_row['rowid'])
    info['cam_params'] = cam_params
    return info
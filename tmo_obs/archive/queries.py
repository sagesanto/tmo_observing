from typing import Tuple
from sqlalchemy import select, func, and_, or_, not_, inspect, Select
from sqlalchemy.orm import joinedload

from .database import MetadataDBRecord, Observation, Schedule, FitsFile

def flexible_dataset_select(name=None,fits_filename=None,bin_filename=None,exact=True):
    """ return a statement that locates dataset(s) based on any/all of the provided attributes, flexibly or not """
    if name is None and fits_filename is None and bin_filename is None:
        raise ValueError('Must provide at least one of fits_filename, name, or bin_filename to select a dataset.')
    stmt = select(Observation)
    conditions = []

    if name is not None:
        conditions.append(Observation.name == name if exact else Observation.name.like(f"%{name}%"))

    if fits_filename is not None:
        stmt = stmt.join(FitsFile)
        conditions.append(FitsFile.filepath == fits_filename if exact else FitsFile.filepath.like(f"%{fits_filename}%"))

    if bin_filename is not None:
        stem = bin_filename
        if stem.endswith(".bin"):
            stem = stem[: -len(".bin")]
        acq_system_id, acquisition_timestamp, acq_num_1, acq_num_2 = stem.split("_")
        conditions.append(and_(
            Observation.acq_system_id == int(acq_system_id),
            Observation.acquisition_timestamp == int(acquisition_timestamp),
            Observation.acq_num_1 == int(acq_num_1),
            Observation.acq_num_2 == int(acq_num_2),
        ))

    stmt = stmt.where(and_(*conditions))
    return stmt

def matches_configuration_stmt(stmt:Select, obs:Observation) -> Select[Tuple[Observation]]:
    # add a WHERE clause to a sqlalchemy select stmt)
    return (stmt.where(Observation.operation_mode == obs.operation_mode)
            .where(Observation.gain == obs.gain)
            .where(Observation.binning_size == obs.binning_size)
            .where(Observation.binning_mode == obs.binning_mode)
            .where(Observation.camera_name == obs.camera_name)
            .where(Observation.roi_height == obs.roi_height)
            .where(Observation.roi_width == obs.roi_width)
            .where(Observation.roi_start_x == obs.roi_start_x)
            .where(Observation.roi_start_y == obs.roi_start_y)
    )
    
def time_difference(obs):
    # partial col for select stmt that computes dt between this obs and other obs 
    return func.abs(func.julianday(Observation.obstime) - func.julianday(obs.obstime)).label("dt") 

def darks_for_obs_stmt(obs:Observation,time_tolerance_days=None, exptime_tolerance_s=0):
    """
        get a SELECT statement for darks matching a specific obs, with tolerance for different exptimes if desired.
        statement results are ordered by those with the least deviation in exptime and those taken nearest in time to the observation indicated 
        
        if time_tolerance_days is None (default), no limit on the difference in time between when the obs and calib were taken. 
    """
    
    # make up a column that computes dt between this obs and the calib obs
    dt = time_difference(obs)
    d_exptime = func.abs(Observation.exptime - obs.exptime).label("d_exptime")
    
    # select calibs within acceptable exptime tolerance
    stmt = (
        select(Observation, dt, d_exptime)
            .order_by(d_exptime,dt)
            .where(Observation.is_dark)
            .where(d_exptime <= exptime_tolerance_s)
    )
    
    # narrow that statement to just those that match our camera configuration
    stmt = matches_configuration_stmt(stmt=stmt, obs=obs)
    
    if time_tolerance_days is not None:
        stmt = stmt.where(dt < time_tolerance_days)
    
    return stmt
    
def biases_for_obs_stmt(obs:Observation,time_tolerance_days=None,**kwargs):
    """
        get a SELECT statement for bias matching a specific obs.
        statement results are ordered nearest in time to the observation indicated 
        if time_tolerance_days is None (default), no limit on the difference in time between when the obs and calib were taken. 
    """
    
    # make up a column that computes dt between this obs and the calib obs
    dt = time_difference(obs)
    
    stmt = (
        select(Observation, dt)
            .order_by(dt)
            .where(Observation.is_bias)
    )
    
    # narrow that statement to just those that match our camera configuration
    stmt = matches_configuration_stmt(stmt=stmt, obs=obs)
    
    if time_tolerance_days is not None:
        stmt = stmt.where(dt < time_tolerance_days)
    
    return stmt

def flats_for_obs_stmt(obs:Observation,time_tolerance_days=None,**kwargs):
    """
        get a SELECT statement for flats matching a specific obs.
        statement results are ordered nearest in time to the observation indicated 
        if time_tolerance_days is None (default), no limit on the difference in time between when the obs and calib were taken. 
    """
    # make up a column that computes dt between this obs and the calib obs
    dt = time_difference(obs)
    
    stmt = (
        select(Observation, dt)
            .order_by(dt)
            .where(Observation.is_flat)
            .where(Observation.filter==obs.filter)
    )
    
    # narrow that statement to just those that match our camera configuration
    stmt = matches_configuration_stmt(stmt=stmt, obs=obs)
    
    if time_tolerance_days is not None:
        stmt = stmt.where(dt < time_tolerance_days)
    
    return stmt

if __name__ == "__main__":
    from database import get_record_db
    
    with get_record_db('/home/sage/tmo_observing/obs_master_7_27_26.sqlite3') as db:
        obs = db.execute(select(Observation).join(FitsFile).limit(1)).scalars().first()
        print(f'target obs id: {obs.id}')
        fpath = obs.fits_files[0].filepath
        name = obs.name
        bin_file = f"{obs.acq_system_id}_{obs.acquisition_timestamp}_{obs.acq_num_1}_{obs.acq_num_2}"
        
        
        stmt = flexible_dataset_select(fits_filename=fpath)
        
        stmts = {
            'fits search': flexible_dataset_select(fits_filename=fpath),
            'fits search (inexact)': flexible_dataset_select(fits_filename=fpath, exact=False),
            'name search (exact)': flexible_dataset_select(name=name),
            'name search (inexact)': flexible_dataset_select(name=name, exact=False),
            'bin search (no ext)': flexible_dataset_select(bin_filename=bin_file),
            'bin search (with ext)': flexible_dataset_select(bin_filename=bin_file+".bin"),
            'all search (inexact)': flexible_dataset_select(bin_filename=bin_file+".bin", name=name,fits_filename=fpath),
        }
        
        for s_name, stmt in stmts.items():
            found = db.execute(stmt).scalars().first()
            if found is not None:
                print(f'{s_name} found obs id: {found.id}')
            else:
                print(f'{s_name} found None!!!!')
import os
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Tuple
import matplotlib.pyplot as plt
from sqlalchemy import select, func, and_, or_, not_, inspect
from sqlalchemy.orm import joinedload
from tmo_obs.archive.database.record_models import FitsFile, Observation, Schedule, MetadataDBRecord as RecordMetadataDB
from tmo_obs.archive.database.record_db import get_record_db
from datetime import datetime, timezone


def record_to_dict(record):
    return {c.key:getattr(record,c.key) for c in inspect(record).mapper.column_attrs}

def resolve_attr(obj, path):
    for part in path.split('.'):
        obj = getattr(obj, part)
        if obj is None:
            return None
    return obj

def standard_df_serializer(records,*args,columns=None,exclude_columns=None,**kwargs) -> List[Dict[str,Any]]:
    if not len(records):
        return None
    if columns is None:
        columns = [c.key for c in inspect(records[0]).mapper.column_attrs]
    if exclude_columns is None:
        exclude_columns = []
    columns = [c for c in columns if c not in exclude_columns]
    rows = [{column:resolve_attr(curr, column) for column in columns} for curr in records]
    return rows

def records_to_df(records, *serializer_args, serializer=standard_df_serializer, **serializer_kwargs):
    rows = serializer(records,*serializer_args,**serializer_kwargs)
    return pd.DataFrame(rows)

def quick_query(stmt, db):
    return db.execute(stmt).scalars().all()

def query_as_csv(stmt, db, *serializer_args, serializer=standard_df_serializer, **serializer_kwargs):
    """
    ex: :: 
    
        from tmo_obs.tess_processing.database.record_db import get_record_db
        
        stmt = (select(Observation)
            .where(Observation.cooler_on == False)
            .where(or_(Observation.is_calib,Observation.is_science))
            .options(joinedload(Observation.metadata_db))
        )
        
        with get_record_db(db_path) as db:
            query_as_csv(stmt, db)
            query_as_csv(stmt,db, columns=['name','metadata_db.filename'])
    
    """
    obs = db.execute(stmt).scalars().all()
    df = records_to_df(obs,*serializer_args, serializer=serializer, **serializer_kwargs)
    return df    
from contextlib import contextmanager
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from tmo_obs.tess_processing.database.record_models import Base

DEFAULT_DB_PATH = "records.sqlite3"

_engine = None
_Session: Optional[sessionmaker] = None


def get_engine(db_path: str = DEFAULT_DB_PATH, echo: bool = False):
    global _engine, _Session
    if _engine is None:
        _engine = create_engine(f"sqlite:///{db_path}", echo=echo)
        Base.metadata.create_all(_engine)
        _Session = sessionmaker(bind=_engine)
    return _engine

@contextmanager
def get_record_db(db_path: str = DEFAULT_DB_PATH, echo: bool = False):
    get_engine(db_path, echo)
    session: Session = _Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

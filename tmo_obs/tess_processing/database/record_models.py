from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass

class MetadataDB(Base):
    __tablename__ = "metadata_dbs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    filename: Mapped[Optional[str]] = mapped_column(nullable=True)
    filesize: Mapped[Optional[str]] = mapped_column(nullable=True)
    last_file_update: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    date_ingested: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    date_updated: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    observations: Mapped[list["Observation"]] = relationship(back_populates="metadata_db", cascade="all, delete-orphan")

class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(nullable=False, unique=True)

    observations: Mapped[list["Observation"]] = relationship(back_populates="schedule")

class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(nullable=False)
    metadata_db_id: Mapped[int] = mapped_column(ForeignKey("metadata_dbs.id"), nullable=False)
    schedule_id: Mapped[Optional[int]] = mapped_column(ForeignKey("schedules.id"), nullable=True)
    sequence_len: Mapped[int] = mapped_column(default=1)
    obstime: Mapped[datetime] = mapped_column(nullable=False)
    rowid: Mapped[int] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(nullable=False)
    is_calib: Mapped[bool] = mapped_column(nullable=False)
    is_science: Mapped[bool] = mapped_column(nullable=False)
    is_bias: Mapped[bool] = mapped_column(nullable=False)
    is_dark: Mapped[bool] = mapped_column(nullable=False)
    is_flat: Mapped[bool] = mapped_column(nullable=False)
    
    exptime: Mapped[float] = mapped_column(nullable=False)
    frames: Mapped[int] = mapped_column(nullable=False)
    filter: Mapped[Optional[str]] = mapped_column(nullable=True)
    
    tele_ra: Mapped[float] = mapped_column(nullable=False)
    tele_dec: Mapped[float] = mapped_column(nullable=False)
    
    camera_name: Mapped[str] = mapped_column(nullable=False)
    gain: Mapped[float] = mapped_column(nullable=False)
    binning_mode: Mapped[str] = mapped_column(nullable=False)
    operation_mode: Mapped[str] = mapped_column(nullable=False)
    
    binning_size: Mapped[int] = mapped_column(nullable=False)
    roi_start_x: Mapped[int] = mapped_column(nullable=False)
    roi_start_y: Mapped[int] = mapped_column(nullable=False)
    roi_width: Mapped[int] = mapped_column(nullable=False)
    roi_height: Mapped[int] = mapped_column(nullable=False)
    
    acq_system_id: Mapped[int] = mapped_column(nullable=False)
    acquisition_timestamp: Mapped[datetime] = mapped_column(nullable=False)
    acq_num_1: Mapped[int] = mapped_column(nullable=False)
    acq_num_2: Mapped[int] = mapped_column(nullable=False)

    metadata_db: Mapped["MetadataDB"] = relationship(back_populates="observations")
    schedule: Mapped[Optional["Schedule"]] = relationship(back_populates="observations")
    fits_files: Mapped[list["FitsFile"]] = relationship(back_populates="observation", cascade="all, delete-orphan")

class FitsFile(Base):
    __tablename__ = "fits_files"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    observation_id: Mapped[int] = mapped_column(ForeignKey("observations.id"), nullable=False)
    filepath: Mapped[str] = mapped_column(nullable=False)

    observation: Mapped["Observation"] = relationship(back_populates="fits_files")

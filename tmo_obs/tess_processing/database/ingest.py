import glob
from datetime import datetime, timezone
from os.path import dirname, exists, getmtime, getsize, join
from typing import Optional

from sqlalchemy.orm import Session

from tmo_obs.tess_processing.database.metadata import MetadataDat, MetadataDB, get_obs_details, read_schedule
from tmo_obs.tess_processing.find_files import is_bias, is_dark, is_flat
from tmo_obs.tess_processing.database.record_db import get_record_db
from tmo_obs.tess_processing.database.record_models import FitsFile, Observation, Schedule
from tmo_obs.tess_processing.database.record_models import MetadataDB as RecordMetadataDB


def to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)

def find_fits_files(data_dir: str, name: str) -> list[str]:
    exact = join(data_dir, f"{name}.fits")
    paths = [exact] if exists(exact) else []
    paths += sorted(glob.glob(join(data_dir, f"{name}_*.fits")))
    return paths

def get_db_file_stats(path: str) -> tuple[Optional[str], Optional[datetime]]:
    if not exists(path):
        return None, None
    filesize = str(getsize(path))
    last_file_update = to_naive_utc(datetime.fromtimestamp(getmtime(path), tz=timezone.utc))
    return filesize, last_file_update

def find_existing_metadata_db(db: Session, path: str) -> Optional[RecordMetadataDB]:
    return db.query(RecordMetadataDB).filter_by(filename=path).one_or_none()

def find_or_create_schedule(db: Session, path: str) -> Schedule:
    schedule = db.query(Schedule).filter_by(path=path).one_or_none()
    if schedule is None:
        schedule = Schedule(path=path)
        db.add(schedule)
        db.flush()  # populates schedule.id
    return schedule

def find_existing_observation(db: Session, acquisition_timestamp: datetime, acq_system_id: int, acq_num_1: int, acq_num_2: int) -> Optional[Observation]:
    return db.query(Observation).filter_by(
        acquisition_timestamp=acquisition_timestamp,
        acq_system_id=acq_system_id,
        acq_num_1=acq_num_1,
        acq_num_2=acq_num_2,
    ).one_or_none()

def build_observation_fields(obs_row: dict, obs_details: dict) -> dict:
    cam_params = obs_details.get("cam_params", {})

    bias = bool(is_bias(obs_details))
    dark = bool(is_dark(obs_details))
    flat = bool(is_flat(obs_details))

    return dict(
        name=obs_details["Name"],
        obstime=to_naive_utc(obs_details["datetime"]),
        rowid=obs_details["rowid"],
        description=obs_details["Description"],
        is_calib=bias or dark or flat,
        is_bias=bias,
        is_dark=dark,
        is_flat=flat,
        exptime=obs_details["ExposureTime"],
        frames=obs_details["Frames"],
        filter=obs_details["FILTER"],
        tele_ra=obs_details["TelescopeRA"],
        tele_dec=obs_details["TelescopeDEC"],
        camera_name=obs_details["CameraName"],
        gain=float(cam_params["Gain"]),
        binning_mode=cam_params["Binning Mode"],
        operation_mode=cam_params["Operation Mode"],
        binning_size=obs_details["BinningSize"],
        roi_start_x=obs_details["ROI_StartX"],
        roi_start_y=obs_details["ROI_StartY"],
        roi_width=obs_details["ROI_Width"],
        roi_height=obs_details["ROI_Height"],
        acq_system_id=obs_row["AcqSystemID"],
        acquisition_timestamp=to_naive_utc(datetime.fromtimestamp(obs_row["AcqTimestamp"], tz=timezone.utc)),
        acq_num_1=obs_row["AcqNum1"],
        acq_num_2=obs_row["AcqNum2"],
    )

def ingest_md_db(target_db: MetadataDB, target_dat: MetadataDat, data_dir: str, schedule_path: str = None, force_ingest: bool = False, record_db_path=None):
    schedule = None
    if schedule_path:
        schedule, _ = read_schedule(schedule_path)

    filesize, last_file_update = get_db_file_stats(target_db.fname)

    with get_record_db(record_db_path) as db:
        db_record = find_existing_metadata_db(db, target_db.fname)

        if db_record is not None and not force_ingest:
            if db_record.filesize == filesize and db_record.last_file_update == last_file_update:
                return db_record.id  # nothing has changed, skip re-ingesting

        if db_record is None:
            db_record = RecordMetadataDB(filename=target_db.fname)
            db.add(db_record)

        db_record.filesize = filesize
        db_record.last_file_update = last_file_update
        db.flush()  # populates db_record.id

        obs_rows = target_db.query("SELECT * FROM DatasetMetaData")
        for obs_row in obs_rows:
            obs_details = get_obs_details(obs_row, target_db, target_dat, schedule, directory=data_dir)
            fields = build_observation_fields(obs_row, obs_details)

            obs_schedule_path = obs_details.get("schedule_path")
            fields["schedule_id"] = find_or_create_schedule(db, obs_schedule_path).id if obs_schedule_path else None

            observation = find_existing_observation(
                db, fields["acquisition_timestamp"], fields["acq_system_id"], fields["acq_num_1"], fields["acq_num_2"]
            )
            if observation is not None:
                for key, value in fields.items():
                    setattr(observation, key, value)
                observation.metadata_db_id = db_record.id
                for existing_fits in list(observation.fits_files):
                    db.delete(existing_fits)
            else:
                observation = Observation(metadata_db_id=db_record.id, **fields)
                db.add(observation)
            db.flush()  # populates observation.id

            for fpath in find_fits_files(data_dir, obs_details["Name"]):
                db.add(FitsFile(observation_id=observation.id, filepath=fpath))

        return db_record.id

def main():
    import argparse
    import shutil
    import tempfile
    from os import remove, walk
    from os.path import basename, join

    from tqdm import tqdm

    from tmo_obs.config import configure_logger, load_config
    from tmo_obs.tess_processing.database.record_db import DEFAULT_DB_PATH

    logger = configure_logger("ingest")

    parser = argparse.ArgumentParser(description="Recursively ingest Metadata.db files into the records database")
    parser.add_argument("start_directory", nargs="?", default=".", help="Directory to search for Metadata.db files (default: cwd)")
    parser.add_argument("--rebuild", action="store_true", help="Wipe the existing records database before ingesting")
    args = parser.parse_args()

    config = load_config()
    remote_db_path = config.get('obs_db_path', DEFAULT_DB_PATH)

    # use tempfile to avoid network drive
    local_db_path = join(tempfile.gettempdir(), basename(remote_db_path))
    if args.rebuild:
        if exists(local_db_path):
            remove(local_db_path)
    elif exists(remote_db_path):
        shutil.copy2(remote_db_path, local_db_path)

    db_paths = []
    for root, _, files in walk(args.start_directory):
        if "Metadata.db" in files:
            db_paths.append(join(root, "Metadata.db"))

    try:
        for metadata_db_path in tqdm(db_paths, desc="Ingesting metadata dbs"):
            data_dir = dirname(metadata_db_path)
            dat_path = join(data_dir, "Metadata.dat")
            if not exists(dat_path):
                logger.warning(f"No Metadata.dat found next to {metadata_db_path}, skipping.")
                continue

            schedule_path = join(data_dir, "Scheduler.txt")
            if not exists(schedule_path):
                schedule_path = None

            with MetadataDB(metadata_db_path) as target_db:
                target_dat = MetadataDat(dat_path)
                ingest_md_db(target_db, target_dat, data_dir, schedule_path=schedule_path, record_db_path=local_db_path)
    finally:
        # sync back to local disk
        if exists(local_db_path):
            shutil.copy2(local_db_path, remote_db_path)


if __name__ == "__main__":
    main()

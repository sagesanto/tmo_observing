import os
from os.path import join
import argparse
from datetime import datetime, timedelta, timezone
import re
import urllib

import matplotlib.pyplot as plt
import numpy as np
import requests
from astroquery.jplhorizons import Horizons
from pytz import UTC
import astropy.units as u
from astropy.coordinates import Angle
from tmo_obs.utils import load_horizon_box, get_hour_angle, get_current_sidereal_time, observability_mask, break_into_windows, alt_az, ra_dec, is_observable, parse_time_arg
from tmo_obs.config import load_config

DEFAULT_OPMODE = 17
DEFAULT_BINMODE = 'FPGASum'
DEFAULT_BIN_LEVEL = 2

DEFAULT_OFFSET_DURATION = 7
DEFAULT_CAMERA_OVERHEAD = 9
DEFAULT_INDIRECT_SLEW_DURATION = 3
DEFAULT_DIRECT_SLEW_DURATION = 2
DEFAULT_BLIND_SLEW_DURATION = 1
DEFAULT_SLEW_TYPE = 'indirect'
DEFAULT_FPS = 24


def ephemerides_from_tle(tle_text: str, location, start: datetime, stop: datetime, step_seconds: float, horizons_url=None, **kwargs):
    """Query Horizons for ephemeris using a user-supplied Two-Line Element."""
    _ = kwargs

    utc = timezone.utc
    if start.tzinfo is not None:
        start = start.astimezone(utc)
    else:
        start = start.replace(tzinfo=utc)
    if stop.tzinfo is not None:
        stop = stop.astimezone(utc)
    else:
        stop = stop.replace(tzinfo=utc)

    horizons_base_url = horizons_url or 'https://ssd.jpl.nasa.gov/api/horizons.api?'

    duration = (stop - start).total_seconds()
    interval = f'{int(duration / step_seconds)}'
    start_str = start.strftime('%Y-%m-%d %H:%M:%S')
    stop_str = stop.strftime('%Y-%m-%d %H:%M:%S')

    obj = Horizons(id='DUMMY', location=location, epochs={'start': start_str, 'stop': stop_str, 'step': interval})
    payload_dict = obj.ephemerides(get_query_payload=True)

    payload_dict['COMMAND'] = 'TLE'
    payload_dict['TLE'] = tle_text

    query_url = horizons_base_url + urllib.parse.urlencode(payload_dict)
    response = requests.get(query_url, timeout=30)
    return obj._parse_result(response, True)


def build_arg_parser():
    parser = argparse.ArgumentParser(description='Observe moving targets using Horizons ephemeris or TLEs, offsetting the telescope to recenter the object.')
    
    parser.add_argument('exptime', type=float, help='Exposure time, in seconds')
    parser.add_argument('nframes', type=int, help='Number of frames per dataset')
    parser.add_argument('start', type=str, help=r"UTC Start time, in format YY-MM-DDTHH:MM:SS, or given relative to a date or to special keyword 'now', ex. now+1hr, now+2h3m2s or {some date}+3hr2s, {some date}-13hr")
    parser.add_argument('end', type=str, help=r"UTC End time, in format YY-MM-DDTHH:MM:SS, or given relative to a date or to special keyword 'now', ex. now+1hr, now+2h3m2s or {some date}+3hr2s, {some date}-13hr")
    parser.add_argument('offset_interval', type=float, help='Offset interval, minutes. will perform offset to compensate for target motion every offset_interval minutes')
    parser.add_argument('config_profile', type=str, help='Name of the robo-observer config to use')
    parser.add_argument('--outdir', '-o', type=str, default=None, help='Directory to save output in. Will be created if does not exist. Default is current working directory.')

    parser.add_argument('--outfile', type=str, default='Scheduler.txt', help="Name of the file to write the schedule to. File will be overwritten. Defaults to 'Scheduler.txt'")
    parser.add_argument('--shh', action='store_true', help='Write less information to terminal while generating schedule')
    
    parser.add_argument('--no-image', action='store_true', help="Don't perform imaging (just offset)")
    parser.add_argument('--no-slew', action='store_true', help="Don't perform initial slew (just start immediately)")
    
    parser.add_argument('--horizons-id', default=301, help='ID for horizons lookup, if not using TLE. Defaults to 301 (Moon)')
    parser.add_argument('--tle', type=str, default=None, help='TLE file to use for target ephemeris. If not provided, uses Horizons lookup instead.')
    parser.add_argument('--save-ephems', '-e', action='store_true', help='Save the retrieved ephemeris to file')
    
    parser.add_argument('--buffer', type=float, default=10, help='Buffer time between the end of one dataset and the beginning of the next, seconds. Distinct from camera overhead, this is free time that is used as a buffer for any unexpected observation time overruns')
    parser.add_argument('--dataset-overhead', type=float, default=DEFAULT_CAMERA_OVERHEAD, help=f'Total overhead (at beginning and end) of taking a dataset, seconds. Defaults to {DEFAULT_CAMERA_OVERHEAD} second(s).')
    
    parser.add_argument('--slew', choices=['indirect', 'direct', 'blind'], default=DEFAULT_SLEW_TYPE, help=f"What type of slew to perform. Defaults to '{DEFAULT_SLEW_TYPE}'")
    parser.add_argument('--preslew', action='store_true', help='Whether to slew to the RA/Dec where the target WILL be in advance of it becoming observable in order to save time. Currently does not work.')
    parser.add_argument('--ind-slew-duration', type=float, default=DEFAULT_INDIRECT_SLEW_DURATION, help=f'Total length of indirect slew, minutes. Defaults to {DEFAULT_INDIRECT_SLEW_DURATION} minute(s).')
    parser.add_argument('--dir-slew-duration', type=float, default=DEFAULT_DIRECT_SLEW_DURATION, help=f'Total length of direct slew, minutes. Defaults to {DEFAULT_DIRECT_SLEW_DURATION} minute(s).')
    parser.add_argument('--blind-slew-duration', type=float, default=DEFAULT_BLIND_SLEW_DURATION, help=f'Total length of blind slew, minutes. Defaults to {DEFAULT_BLIND_SLEW_DURATION} minute(s).')
    
    parser.add_argument('--slew-delta-ra', type=float, default=5, help="RA delta for indirect slew, in deg (how far away from the target should we perform recentering). Defaults to 5 degrees. Treated as an unsigned magnitude unless slew-delta-direction is 'manual'")
    parser.add_argument('--slew-delta-dec', type=float, default=0, help="Dec delta for indirect slew, in deg. Defaults to 0 degrees. Treated as an unsigned magnitude unless slew-delta-direction is 'manual'")
    parser.add_argument('--slew-delta-direction', choices=['auto', 'manual'], default='auto', help="Whether to automatically point the indirect slew delta towards the center of the bounding box ('auto') or to treat the --slew-delta-ra and --slew-delta-dec components as directional ('manual')")

    parser.add_argument('--horizon-box-path', type=str, help='Path to the horizon box, stored in Alora json format. Gets path from config if not specified.')
    parser.add_argument('--skip-bbox-check', action='store_false', dest='check_bbox', help='Whether to skip the check on whether the target is in the horizon box when outputting the schedule (when this is not skipped, will not write lines that are outside of horizon box to schedule). When provided, also skips nighttime check.')
    parser.add_argument('--skip-night-check', action='store_false', dest='check_night', help='Whether to skip the check on whether it is night time (type of night set with --night-type) when writing the schedule (when this is not skipped, will not write lines that are during daytime). When --skip-bbox-check is provided, nighttime checks are also skipped.')
    parser.add_argument('--night-type', choices=['astronomical', 'civil'], default='astronomical', help="What type of night ('astronomical' or 'civil') to use if checking nighttime (--check-night). Defaults to 'astronomical'")
    
    parser.add_argument('--fps', type=int, default=DEFAULT_FPS, help=f'FPS of the observing mode. Defaults to {DEFAULT_FPS}')
    parser.add_argument('--offset-duration', type=float, default=DEFAULT_OFFSET_DURATION, help=f'Total time it takes to perform a small offset, seconds. Defaults to {DEFAULT_OFFSET_DURATION} second(s).')
    parser.add_argument('--min-dataset-len', type=float, default=0, help='Minimum length, in seconds, of each schedule line (integration + overhead + buffer + idle) (will round up shorter observations and wait the idle time). Defaults to 0 second(s).')
    
    parser.add_argument('--cadence', nargs=2, type=float, help='A pair of numbers - the first defines the number of on-target datasets and the second specifies the off-target time in seconds. Ex: --cadence 5 600 takes 5 datasets on target, does not take data for 600 seconds (but still tracks the target), and then repeats. If not provided, performs default behavior of continuous observation.')
    parser.add_argument('--sequenced', action='store_true', help='Whether to take the observations sequenced, using a number of frames equal to the frame rate and requesting a sequence of datasets that will fill the intermediate time. Overrides the nframes argument.')
    
    parser.add_argument('--dataset-name', type=str, default=None, help='Name of the dataset. If not provided, takes the form {target name}_{YYMMDD}')
    parser.add_argument('--manual-slew-offset-ra', type=float, default=0, help='Add a manual offset, in degrees, to the slew target location (ex. to offset from the center of the moon)')
    parser.add_argument('--manual-slew-offset-dec', type=float, default=0, help='Add a manual offset, in degrees, to the slew target location (ex. to offset from the center of the moon)')
    
    return parser


def run(args):
    try:
        config = load_config()
    except Exception as e:
        config = None
        print(f"[WARNING] Couldn't load config ({e}). Won't be able to auto-determine indirect slew direction or check observability.")

    outdir = args.outdir
    if outdir is None:
        outdir = os.getcwd()
    os.makedirs(outdir,exist_ok=True)
    
    def out(fname):
        return join(outdir,fname)
    
    def savefig(fname,bbox_inches='tight',dpi=300):
        plt.savefig(out(fname),bbox_inches=bbox_inches,dpi=dpi)

    quiet = args.shh
    
    exptime_s = args.exptime
    n_frames = args.nframes
    schedule_config_profile = args.config_profile
    no_image = args.no_image
    no_slew = args.no_slew
    
    t_start = parse_time_arg(args.start)
    t_finish = parse_time_arg(args.end)
    orig_start_time, orig_finish_time = t_start, t_finish  # t_start, t_finish will change based on observability
    
    offset_every_min = args.offset_interval
    outfile = args.outfile
    buffer_s = args.buffer  # adding extra seconds to avoid missing a dataset
    
    offset_duration_s = args.offset_duration
    overhead_between_datasets_s = args.dataset_overhead
    
    min_dataset_len_s = args.min_dataset_len
    dataset_name = args.dataset_name
    tle_file = args.tle
    sequenced = args.sequenced
    fps = args.fps

    # determine observation timing 
    cadenced = False
    n_on = 0
    cadence_off_s = 0
    if args.cadence:
        cadenced = True
        n_on, cadence_off_s = args.cadence

    if sequenced:
        assert not cadenced, 'Observations that are both sequenced and cadenced are currently not supported.'

    check_bbox = args.check_bbox
    check_night = args.check_night
    night_type  = args.night_type 
    if check_bbox:
        print("Checking bounding box for observability when producing schedule")
        if check_night:  # intentionally indented
            print(f"Checking whether it is {night_type} night when producing schedule")

    bbox = None
    if config is not None:
        bbox_path = None
        if args.horizon_box_path is not None:
            bbox_path = args.horizon_box_path 
        else:
            bbox_path = config.get('HORIZON_BBOX_PATH')
        if bbox_path is None:
            print(f"No horizons box path found in config or from commandline arguments. Won't be able to auto-determine indirect slew direction or check observability.")
        else:
            try:
                bbox = load_horizon_box(bbox_path, config['BBOX_BUFFER_DEG'])
            except Exception as e:
                print(f"Couldn't load bounding box: {e}. Won't be able to auto-determine indirect slew direction or check observability.")

    # slewing logistics 
    delta_ra_deg = args.slew_delta_ra  # offset in deg for indirect slew
    delta_dec_deg = args.slew_delta_dec  # offset in deg for indirect slew
    slew_type = args.slew
    manual_slew_offset_ra = args.manual_slew_offset_ra
    manual_slew_offset_dec = args.manual_slew_offset_dec
    if slew_type == 'indirect':
        slew_buffer_minutes = args.ind_slew_duration
    elif slew_type == 'direct':
        slew_buffer_minutes = args.dir_slew_duration
    else:
        slew_buffer_minutes = args.blind_slew_duration

    if no_slew:
        slew_buffer_minutes = 0

    offset_dataset_len = offset_duration_s + max(buffer_s - offset_duration_s, 0)

    seq = 1
    if sequenced:
        if exptime_s <= 1 / fps:
            n_frames = fps
            ds_len = 1
        else:
            n_frames = max(int(np.floor(1 / exptime_s)), 1)
            ds_len = n_frames * exptime_s
        seq = int(np.floor(offset_every_min * 60 - overhead_between_datasets_s - buffer_s - offset_dataset_len) / ds_len)
        assert seq > 0, 'Combination of exposure time and offset cadence leads to infeasibly-sequenced observations.'
        ds_len = max(exptime_s * n_frames, n_frames / fps)
        raw_dataset_len = ds_len * seq + overhead_between_datasets_s + buffer_s
        duration_description = f'Using sequencing, we will take a series of {seq} {n_frames}-frame, {exptime_s}s datasets between offsets, plus {overhead_between_datasets_s}s of overhead and {buffer_s}s of buffer'
    else:
        raw_dataset_len = exptime_s * n_frames + overhead_between_datasets_s + buffer_s
        duration_description = f'Dataset duration: {exptime_s}s * {n_frames} frames = {round(exptime_s * n_frames, 5)}s, plus {overhead_between_datasets_s}s of overhead and {buffer_s}s of buffer'

    dataset_len = max(raw_dataset_len, min_dataset_len_s)


    if raw_dataset_len < min_dataset_len_s:
        duration_description += f', plus {min_dataset_len_s - raw_dataset_len}s of downtime to meet minimum dataset length of {min_dataset_len_s}s (set with --min-dataset-len)'
    duration_description += f', yielding a {dataset_len}s dataset.'
    
    if timedelta(minutes=offset_every_min) < timedelta(seconds=dataset_len) and not no_image:
        raise ValueError(
            f'Offsetting every {offset_every_min} minute(s) will not allow any {dataset_len}s datasets '
            '(includes overhead and integration) to be taken! Reduce single-dataset integration time or increase delays between offsets.'
        )
    if sequenced:
        datasets_between_offset = 1
    else:
        datasets_between_offset = int((offset_every_min * 60 - offset_dataset_len) / dataset_len)

    block_len = datasets_between_offset * dataset_len + offset_dataset_len

    if tle_file is not None:
        print(f'Using TLE file {tle_file} to get ephemerides')
        with open(tle_file, 'r') as f:
            tle_text = f.read()
        target_name = tle_text.splitlines()[0].strip()
        ephems = ephemerides_from_tle(
            tle_text,
            location='654',
            start=t_start,
            stop=t_finish + (t_finish - t_start) * 0.1,
            step_seconds=dataset_len / 2,
        )
    else:
        start_str = t_start.strftime('%Y-%m-%d %H:%M:%S')
        stop_str = (t_finish + (t_finish - t_start) * 0.1).strftime('%Y-%m-%d %H:%M:%S')
        interval_s = int(dataset_len / 2)
        interval = f'{int( (t_finish - t_start).total_seconds() / interval_s)}'
        if args.horizons_id == 301:
            print('Scheduling Moon observations. To change targets, use --horizons-id')
        print(f'Querying for ephemeris at {interval} intervals between {start_str} and {stop_str}')
        obj = Horizons(id=args.horizons_id, location='654', epochs={'start': start_str, 'stop': stop_str, 'step': interval})
        ephems = obj.ephemerides()
        target_name = re.split(r'(\s\(\d*\))$', ephems['targetname'][0])[0]

    tname = re.sub(r'[^a-zA-Z0-9\.]', '', target_name)
    tname = '_'.join(tname.lower().split(' '))
    if dataset_name is None:
        dataset_name = f"{tname}_{datetime.now().strftime('%Y%m%d')}"

    if not quiet:
        print('Got ephems.')
    
    if args.save_ephems:
        ephems.write(out(f"{dataset_name}_ephems.csv"),overwrite=True)
        # ephems.write(out(f"{dataset_name}_ephems.ecsv"),overwrite=True)
        print('Saved ephems.')
        
    print(f'Writing schedule for target {target_name}')

    horizons_ras = ephems['RA']
    horizons_decs = ephems['DEC']
    horizons_dts = [datetime.strptime(s, '%Y-%b-%d %H:%M:%S.%f').replace(tzinfo=UTC) for s in ephems['datetime_str']]
    horizons_epochs = np.array([dt.timestamp() for dt in horizons_dts])

    obs_mask = np.ones_like(horizons_dts,dtype=bool)
    obs_windows = [[t_start, t_finish]]
    if check_bbox and bbox is not None:
        obs_mask = observability_mask(horizons_ras, horizons_decs, horizons_dts, bbox, check_night=check_night, night_type=night_type)
        ephems['observable'] = obs_mask
        if args.save_ephems:
            ephems.write(out(f"{dataset_name}_ephems.csv"),overwrite=True)
            # ephems.write(out(f"{dataset_name}_ephems.ecsv"),overwrite=True)
        if np.all(~obs_mask):
            print("Target is not observable in the specified window. Exiting.")
            exit(0)
            
        obs_windows = break_into_windows(obs_mask,horizons_dts)
        from pytz import timezone as pytimezone
        pacific_tz = pytimezone('US/Pacific')

        lines = [f'{target_name} Observability']
        for start, end in obs_windows:
            if start == end:
                continue
            duration = (end-start).total_seconds()/3600
            L = f"{start.astimezone(pacific_tz).strftime('%Y-%m-%d %H:%M')} to {end.astimezone(pacific_tz).strftime('%Y-%m-%d %H:%M')} Local"
            L += f" ({start.astimezone(UTC).strftime('%Y-%m-%d %H:%M')} to {end.astimezone(UTC).strftime('%Y-%m-%d %H:%M')} UTC)"
            lines.append(L)
        lines.insert(1,'-' * len(lines[-1]))
    
        print()
        for l in lines:
            print(l)
        print()
    
    t_start = obs_windows[0][0]
    t_finish = obs_windows[-1][1]
    
    t_start_data = t_start + timedelta(minutes=slew_buffer_minutes)
    n_datasets = int(np.floor((t_finish - t_start_data).total_seconds() / block_len) * (datasets_between_offset)) + 1
    window_duration_s = (t_finish - t_start).total_seconds()
    
    if not quiet:
        print(f"Scheduling between {t_start.strftime('%Y-%m-%d %H:%M')} and {t_finish.strftime('%Y-%m-%d %H:%M')} UTC")
        print(duration_description)
        print(f'Offset duration: {offset_duration_s}s of offset time, plus {round(max(buffer_s - offset_duration_s, 0), 2)}s of buffer.')
        print(f'Doing {n_datasets} datasets, with {datasets_between_offset} dataset(s) {dataset_len}s each being followed by 1 offset ({offset_dataset_len}s each)')
    

    def target_pos(t):
        if isinstance(t, datetime):
            assert t.tzinfo is not None
            t = t.astimezone(UTC)
            epoch = t.timestamp()
        else:
            epoch = t
        if np.all(epoch < min(horizons_epochs)) or np.all(epoch > max(horizons_epochs)):
            raise ValueError(f'Epoch {epoch} not in bounds ({min(horizons_epochs)} to {max(horizons_epochs)})')
        ra = np.interp(epoch, horizons_epochs, horizons_ras)
        dec = np.interp(epoch, horizons_epochs, horizons_decs)
        return np.array([ra, dec])

    def accrued_target_drift(ti, tf):
        pos_i = target_pos(ti)
        pos_f = target_pos(tf)
        return pos_f[0] - pos_i[0], pos_f[1] - pos_i[1]

    overrides = '{}'

    def fmt(num, n_decimals=4):
        if not num:
            return '0.0'
        return f"{num:.{n_decimals}f}"

    def write_blind_slew(dt, ra, dec, dra, ddec):
        time = dt.strftime('%Y-%m-%dT%H:%M:%S.000')
        return f"{time}|0|{schedule_config_profile}|{dataset_name}|Blind|{fmt(ra)}|{fmt(dec)}|0.0|0|0|CLEAR|-1|{fmt(dra, 5)}|{fmt(ddec, 5)}|{overrides}|\"{target_name} Blind Slew\""

    def write_indirect_slew(dt, ra, dec, dra, ddec):
        if args.slew_delta_direction == 'auto':
            if bbox is not None:  # the slew delta should point towards the center of the box (so that we dont offset out-of-bounds)
                bbox_x, bbox_y = bbox.exterior.coords.xy
                ha = get_hour_angle(ra*u.deg,dt)
                if ha.to_value('degree') < (max(bbox_x) + min(bbox_x))/2:
                    dra = abs(dra)
                else:
                    dra = -abs(dra)
                    
        print(f"ra: {ra}, dec: {dec}, dra: {dra}, ddec: {ddec}")
        # print(f"ra: {ra}, dec: {dec}, dra: {dra}, ddec: {ddec}")
            
        time = dt.strftime('%Y-%m-%dT%H:%M:%S.000')
        return f"{time}|0|{schedule_config_profile}|{dataset_name}|Indirect|{fmt(ra-dra)}|{fmt(dec-ddec)}|0.0|0|0|CLEAR|-1|{fmt(dra, 5)}|{fmt(ddec, 5)}|{overrides}|\"{target_name} Indirect Slew\""

    def write_direct_slew(dt, ra, dec, dra, ddec):
        _ = (dra, ddec)
        time = dt.strftime('%Y-%m-%dT%H:%M:%S.000')
        return f"{time}|0|{schedule_config_profile}|{dataset_name}|Direct|{fmt(ra)}|{fmt(dec)}|0.0|0|0|CLEAR|-1|0.0|0.0|{overrides}|\"{target_name} Direct Slew\""

    def write_slew_line(dt, ra, dec, dra, ddec):
        if slew_type == 'indirect':
            return write_indirect_slew(dt, ra, dec, dra, ddec)
        if slew_type == 'direct':
            return write_direct_slew(dt, ra, dec, dra, ddec)
        return write_blind_slew(dt, ra, dec, dra, ddec)

    def write_offset_line(dt, dra, ddec):
        time = dt.strftime('%Y-%m-%dT%H:%M:%S.000')
        description = f'{target_name} [OFFSET]'
        return f"{time}|0|{schedule_config_profile}|{dataset_name}|Offset|0.0|0.0|0.0|0|0|CLEAR|-1|{fmt(dra, 5)}|{fmt(ddec, 5)}|{overrides}|\"{description}\""

    def write_dataset_line(dt):
        if no_image:
            return ''
        time = dt.strftime('%Y-%m-%dT%H:%M:%S.000')
        description = f'{target_name} Data'
        return f"{time}|1|{schedule_config_profile}|{dataset_name}|NoSlew|0.0|0.0|{exptime_s}|{n_frames}|{seq}|CLEAR|-1|0.0|0.0|{overrides}|\"{description}\""

    times = []
    is_dataset = []
    is_offset = []
    off_ra, off_dec = [], []
    ra, dec = [], []
    schedule_lines = []
    running_time = t_start
    time_of_last_offset = running_time

    if not no_slew:
        # TODO: i think this preslew thing only works if we dont track between when we arrive and when the target arrives, or if we re-slew (but reslewing defeats the purpose)
        # slew to the position where the target *will* be before it gets there (for when target is not yet observable)
        preslew=False
        if preslew and orig_start_time + timedelta(minutes=slew_buffer_minutes) < t_start:  # we have enough time for this to be relevant
            slew_time = t_start - timedelta(minutes=slew_buffer_minutes)
            time_after_slew = t_start
            print("Preslewing to target before it becomes observable")  
            ra_start_obs, dec_start_obs = target_pos(t_start)  # where the target will be when it is first observable
            alt, az = alt_az(ra_start_obs, dec_start_obs, t_start)  # what alt az will that position be at
            ra_i, dec_i = ra_dec(alt, az, slew_time)  # where is that alt az now
            ra_i, dec_i = ra_i.degree, dec_i.degree
        else:        
            time_after_slew = running_time + timedelta(minutes=slew_buffer_minutes)
            ra_i, dec_i = target_pos(time_after_slew)
            slew_time = running_time
        print(f'Scheduling slew to target {target_name} at time {slew_time}')
        times.append(time_after_slew)
        ra.append(ra_i)
        dec.append(dec_i)
        is_offset.append(False)
        is_dataset.append(False)
        schedule_lines.append(write_slew_line(slew_time, ra_i + manual_slew_offset_ra, dec_i + manual_slew_offset_dec, delta_ra_deg, delta_dec_deg) + '\n\n')
        # schedule_lines.append(write_slew_line(slew_time, ra_i - delta_ra_deg + manual_slew_offset_ra, dec_i - delta_dec_deg + manual_slew_offset_dec, delta_ra_deg, delta_dec_deg) + '\n\n')
        running_time = time_after_slew
        time_of_last_offset = slew_time

    currently_on = True
    datasets_before_break = n_on
    waiting_until = None

    while running_time < t_finish:
        r, d = target_pos(running_time)
        if bbox is not None and check_bbox and not is_observable(r, Angle(d*u.degree), running_time, bbox, check_night=check_night,night_type=night_type):
            running_time += timedelta(seconds=30)
            continue
        if not currently_on:
            if time_of_last_offset + timedelta(minutes=offset_every_min) < waiting_until:
                running_time = time_of_last_offset + timedelta(minutes=offset_every_min)
                dra, ddec = accrued_target_drift(ti=time_of_last_offset, tf=running_time)
                t_ra, t_dec = target_pos(running_time)
                schedule_lines.append(write_offset_line(running_time, dra, ddec) + '\n')
                ra.append(t_ra)
                dec.append(t_dec)
                off_ra.append(dra)
                off_dec.append(ddec)
                is_offset.append(True)
                is_dataset.append(False)
                time_of_last_offset = running_time
                running_time += timedelta(seconds=offset_dataset_len)
                times.append(running_time)
                continue

            currently_on = True
            datasets_before_break = n_on
            running_time = max(running_time, waiting_until)
            schedule_lines.append('\n')
            continue

        if (running_time + timedelta(seconds=dataset_len) - time_of_last_offset) > timedelta(minutes=offset_every_min):
            is_dataset.append(False)
            times.append(running_time)
            dra, ddec = accrued_target_drift(ti=time_of_last_offset, tf=running_time)
            t_ra, t_dec = target_pos(running_time)
            schedule_lines.append(write_offset_line(running_time, dra, ddec) + ('\n' if cadenced else '\n\n'))
            ra.append(t_ra)
            dec.append(t_dec)
            is_offset.append(True)
            off_ra.append(dra)
            off_dec.append(ddec)
            time_of_last_offset = running_time
            running_time += timedelta(seconds=offset_dataset_len)
            continue

        is_dataset.append(True)
        is_offset.append(False)
        times.append(running_time)
        schedule_lines.append(write_dataset_line(running_time) + '\n')
        if len(ra):
            ra.append(ra[-1])
            dec.append(dec[-1])
        else:
            ra_i, dec_i = target_pos(running_time)
            ra.append(ra_i)
            dec.append(dec_i)
        running_time += timedelta(seconds=dataset_len)

        if cadenced:
            datasets_before_break -= 1
            if not datasets_before_break:
                currently_on = False
                waiting_until = running_time + timedelta(seconds=cadence_off_s)
                schedule_lines.append('\n')
                if waiting_until > t_finish:
                    if not quiet:
                        print(f'Remaining time would be spent waiting. Finishing early at {running_time}.')
                    break

    print(f'Made a schedule with {len(np.where(is_dataset)[0])} dataset(s) and {len(np.where(is_offset)[0])} offset(s).')

    with open(out(outfile), 'w+') as f:
        f.write('DateTime|Image|Config|Target|Slew|RA|Dec|ExposureTime|#Exposure|Seq|Filter|CandidateID|RAOffset|DecOffset|CfgOverrides|Description\n\n')
        f.writelines(schedule_lines)
    print(f'Wrote schedule to {out(outfile)}')

    ra = np.array(ra)
    dec = np.array(dec)
    off_ra = np.array(off_ra)
    off_dec = np.array(off_dec)
    is_dataset = np.array(is_dataset)
    times = np.array(times)
    dataset_epochs = np.array([t.timestamp() for t in times[is_dataset]])
    offset_epochs = np.array([t.timestamp() for t in times[is_offset]])

    plt.figure()
    plt.plot(ra, dec, color='tab:gray', alpha=0.5)
    plt.xlabel('RA')
    plt.ylabel('DEC')
    plt.title(f'{target_name} Observing Plan')
    plt.scatter(ra[is_dataset], dec[is_dataset], color='tab:red', s=1, marker='s', zorder=2, label='Observation')
    plt.scatter(ra[~is_dataset], dec[~is_dataset], color='tab:blue', s=1, marker='s', label='Offset')
    plt.legend()
    savefig(f'{tname}_observing_plan.png')
    plt.close()

    fig, ax = plt.subplots(figsize=(12, 2))
    ax.scatter(times[is_dataset], np.ones_like(times[is_dataset]), s=2)
    for t in times[is_dataset]:
        ax.plot([t, t + timedelta(seconds=raw_dataset_len)], [1, 1], color='tab:blue')
    ax.scatter(times[~is_dataset], 1.1 * np.ones_like(times[~is_dataset]), s=2)
    ax.set_ylim(0.9, 1.2)
    ax.set_yticks([1, 1.1])
    ax.set_yticklabels(['Datasets', 'Offsets'])
    savefig(f'{tname}_timeline.png')
    plt.close(fig)

    hor_mask = horizons_epochs <= running_time.timestamp()
    fig, axes = plt.subplots(nrows=3, sharex=True)
    plt.tight_layout()

    ax = axes[0]
    t0 = min(dataset_epochs)
    ax.plot(dataset_epochs - t0, ra[is_dataset], label='Telescope')
    ax.plot(horizons_epochs[hor_mask] - t0, horizons_ras[hor_mask], label=target_name)
    ax.legend()
    ax.set_ylabel('RA (deg)')
    ax.set_title(f'{target_name} Observations')

    ax = axes[1]
    ax.plot(dataset_epochs - t0, dec[is_dataset], label='Telescope')
    ax.plot(horizons_epochs[hor_mask] - t0, horizons_decs[hor_mask], label=target_name)
    ax.legend()
    ax.set_ylabel('DEC (deg)')

    ax = axes[2]
    ax.plot(offset_epochs - t0, off_ra * 60, label='RA')
    ax.plot(offset_epochs - t0, off_dec * 60, label='DEC')
    ax.set_xlabel('t (s)')
    ax.legend(ncol=2)
    ax.set_ylabel('Offset (arcmin)')

    savefig(f'{dataset_name}.png')
    plt.close(fig)
    print('Made visualizations.')

    if len(off_ra):
        fig, ax = plt.subplots()
        plt.tight_layout()
        frac_ra_off = off_ra / off_ra[0]
        frac_dec_off = off_dec / off_dec[0]
        ax.plot(offset_epochs - t0, frac_ra_off, label='RA')
        ax.plot(offset_epochs - t0, frac_dec_off, label='DEC')
        ax.set_xlabel('t (s)')
        ax.legend(ncol=2)
        ax.set_title('Fractional Offsets (relative to first offset)')
        ax.set_ylabel('Offset (fraction of initial)')
        savefig(f'{dataset_name}_fraction.png')
        plt.close(fig)

    return 0


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return run(args)


if __name__ == '__main__':
    main()

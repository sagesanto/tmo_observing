import sys, os
from os.path import exists
from argparse import ArgumentParser
from astral import LocationInfo, Observer
from datetime import datetime
from pytz import UTC
import tomli
import astropy.units as u
from astropy.coordinates import Angle

import rich
from rich.table import Table as rich_table
from rich import box
import matplotlib.pyplot as plt

from tmo_obs.utils import ( get_current_sidereal_time, dateToSidereal, current_dt_utc, tmo_loc, 
                           parse_time_arg, get_current_hour_angle, get_hour_angle, input_to_angle,
                           copy_to_clipboard, format_angle_str, AngleFormat, load_horizon_box, plot_bbox, 
                           timestr)
from tmo_obs.config import get_config_path

def main():
    parser = ArgumentParser(description="Print the bounding/horizon box of the telescope in HA/DEC or RA/DEC. Config required (default) or bbox path must be provided.")

    parser.add_argument('--abs',action='store_true', help="Get the bbox in RA/DEC instead of HA/DEC. Can specify time to calculate RA at. Assumes current time if time is not provided.")

    parser.add_argument('time',type=str,nargs='?', help="[Optional] UTC time, interpreted as local time if --local also provided. Used with --abs to get the bbox at a certain time. Assumes current time if this arg is not provided. Datetime, in format YY-MM-DDTHH:MM:SS, or given relative to a date or to special keyword 'now', ex. now+1hr, now+2h3m2s or {some date}+3hr2s, {some date}-13hr")
    parser.add_argument('--local',action='store_true',help="Interpret the provided time as local instead of UTC. Will not work as intended if the provided date is relative to 'now'")

    coord_group = parser.add_argument_group("location", "[Optional] Provide both latitude and longitude along with --abs to get RA at sites other than TMO. Providing neither defaults to TMO")
    coord_group.add_argument("--lat", type=float, required=False, help="Decimal latitude, deg")
    coord_group.add_argument("--lon", type=float, required=False, help="Decimal longitude, deg")

    fmt_group = parser.add_argument_group("[Optional] Output format for RA/HA","Mutually exclusive. Default HMS for RA/HA. DEC always given in decimal degrees.")
    format = fmt_group.add_mutually_exclusive_group()

    format.add_argument('--hms', action='store_const', dest='fmt', const=AngleFormat.HMS, default=AngleFormat.HMS, help="Output in HMS (default)")
    format.add_argument('--dms', action='store_const', dest='fmt', const=AngleFormat.DMS, help="Output in DMS")
    format.add_argument('--degrees','-d', action='store_const', dest='fmt', const=AngleFormat.DEGREES, help='Output in decimal degrees')
    format.add_argument('--decimal-hours', action='store_const', dest='fmt', const=AngleFormat.DECIMAL_HOURS, help='Output decimal hours')
    format.add_argument('--sexagesimal','-s', action='store_const', dest='fmt', const=AngleFormat.SEXAGESIMAL, help="Output sexagesimal with ':' as separator")
    parser.add_argument('--precision','-p', type=int, default=None,help="Precision of the RA/HA output. Default is 5 places for decimal degrees or hours and 0 for DMS, HMS, and sexagesimal")

    parser.add_argument('--bbox','-b',type=str, default=None, help='[Optional] Path to the bounding box. Must be provided if tmo_obs config not configured. If not provided, looks for config key HORIZON_BBOX_PATH.')
    parser.add_argument('--buffer',type=float, default=None, help='[Optional] How much the bounding box is shrunk by during observing, in deg. If config configured, pulled from config with key BBOX_BUFFER_DEG if key can be found. Defaults to 0 if not provided and no config or no such key.')
    parser.add_argument('--raw','-r',action='store_true',help="Print only the angles, with no additional information")
    parser.add_argument('--plot','-v',action='store_true',help="Plot the bounding box")

    args = parser.parse_args()
    
    DEC_FORMAT = AngleFormat.DEGREES  # const for now

    bbox_path = args.bbox
    config = None
    if bbox_path is None:
        cfg_path = get_config_path()
        with open(cfg_path, 'rb') as f:  # will raise if cfg not exist
            config = tomli.load(f)
            bbox_path = config.get('HORIZON_BBOX_PATH')
            if bbox_path is None:
                print(f"Error: Can't find key 'HORIZON_BBOX_PATH' in config {cfg_path}. Must exist if --bbox/-b not provided.")
                return 1
    if not exists(bbox_path):
        print(f"Error: Bbox file {bbox_path} does not exist")
        return 1
    
    buffer = args.buffer
    if buffer is None:
        try: 
            if config is None:
                with open(get_config_path(), 'rb') as f:
                    config = tomli.load(f)
            buffer = config['BBOX_BUFFER_DEG']
        except:
            buffer = 0
            
    bbox = load_horizon_box(bbox_path,buffer,raw=True)
    bbox_geom = load_horizon_box(bbox_path,buffer,raw=False)
    
    if not args.abs and args.time is not None:
        print('Warn: time provided but --abs is not. Ignoring time arguments.')
    
    if (args.lat is None) != (args.lon is None):
        parser.error("Both --lat and --lon must be provided together, or neither")
    
    if args.abs:
        loc = tmo_loc
        if args.lat is not None:
            loc = LocationInfo(name="unkn", region="UNKN",timezone="UTC",
                            latitude=args.lat,longitude=args.lon)
        
        time = None
        if args.time is not None:
            time = parse_time_arg(args.time)
            if args.local:
                if 'now' in args.time:
                    pass
                else:
                    local_tz = datetime.now().astimezone().tzinfo
                    time = time.replace(tzinfo=local_tz).astimezone(UTC)
        else:
            time = datetime.now(UTC)

        current_lst = get_current_sidereal_time(loc)
        lst = dateToSidereal(time,current_lst)
        alt_bbox = {}
        for (dec1, dec2), (ha1, ha2) in bbox.items():
            # -> RA = ST - HA
            ra1 = (lst - Angle(ha1*u.deg)).wrap_at(360*u.deg)
            ra2 = (lst - Angle(ha2*u.deg)).wrap_at(360*u.deg)
            alt_bbox[(dec1, dec2)] = (ra2, ra1)  # intentional
        bbox = alt_bbox
    
    if args.raw:
        table = rich_table(box=None,show_header=False)
    else:
        title = "Bounding Box"
        if args.abs:
            title = f"Bounding Box\n{timestr(time)} UT (LST {format_angle_str(lst,AngleFormat.HMS)})"
        table = rich_table(box=box.SIMPLE,show_footer=True, title=title)
    table.add_column('DEC Range',footer=DEC_FORMAT.name,justify='center')
    # table.add_column('Min DEC',footer=DEC_FORMAT.name,justify='right')
    # table.add_column('Max DEC',footer=DEC_FORMAT.name,justify='right')
    if args.abs:
        table.add_column('Min RA',footer=args.fmt.name,justify='center')
        table.add_column('Max RA',footer=args.fmt.name,justify='center')
    else:
        table.add_column('Min HA',footer=args.fmt.name,justify='center')
        table.add_column('Max HA',footer=args.fmt.name,justify='center')
        
    for (dec1, dec2), (ha1_ra1, ha2_ra2) in bbox.items():
        fd1 = format_angle_str(Angle(dec1,unit=u.deg), DEC_FORMAT, 0)
        fd2 = format_angle_str(Angle(dec2,unit=u.deg), DEC_FORMAT, 0)
        dstr = f"{fd1:>3} < DEC < {fd2:>3}"
        frh1 = format_angle_str(Angle(ha1_ra1,unit=u.deg), args.fmt, args.precision)
        frh2 = format_angle_str(Angle(ha2_ra2,unit=u.deg), args.fmt, args.precision)
        table.add_row(dstr,frh1,frh2)
        # table.add_row(fd1,fd2,frh1,frh2)
    print()
    rich.print(table)
    if args.plot:
        plot_bbox(bbox_geom)
        plt.show()

if __name__ == '__main__':
    sys.exit(main())
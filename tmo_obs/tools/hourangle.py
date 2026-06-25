# Sage Santomenna 2026

import sys, os
from argparse import ArgumentParser
from astral import LocationInfo, Observer
from datetime import datetime
from pytz import UTC

from tmo_obs.utils import ( get_current_sidereal_time, dateToSidereal, current_dt_utc, tmo_loc, 
                           parse_time_arg, get_current_hour_angle, get_hour_angle, input_to_angle,
                           copy_to_clipboard, format_angle_str, AngleFormat )

def main():
    parser = ArgumentParser(description="Get the hour angle of a target with the provided RA, now or in the future")

    parser.add_argument('ra', type=str, help='RA of the target, in hms, decimal deg, or colon-separated format')

    coord_group = parser.add_argument_group("location", "Provide both latitude and longitude to get LST at sites other than TMO, or neither for TMO")
    coord_group.add_argument("--lat", type=float, required=False, help="Decimal latitude, deg")
    coord_group.add_argument("--lon", type=float, required=False, help="Decimal longitude, deg")
    
    parser.add_argument('time',nargs='?',type=str, help="[Optional] Time to get LST at. Assumes current if this arg is not provided. Datetime, in format YY-MM-DDTHH:MM:SS, or given relative to a date or to special keyword 'now', ex. now+1hr, now+2h3m2s or {some date}+3hr2s, {some date}-13hr")
    parser.add_argument('--local',action='store_true',help="Interpret the provided time as local instead of UTC. Will not work as intended if the provided date is relative to 'now'")

    parser.add_argument('--copy','-c',action='store_true',help="Copy the output to clipboard in addition to printing it")
    parser.add_argument('--precision','-p', type=int, default=None,help="Precision of the output. Default is 5 places for decimal degrees or hours and 0 for DMS, HMS, and sexagesimal")
    
    fmt_group = parser.add_argument_group("Output format","Mutually exclusive. Default HMS")
    format = fmt_group.add_mutually_exclusive_group()
    
    format.add_argument('--hms', action='store_const', dest='fmt', const=AngleFormat.HMS, default=AngleFormat.HMS, help="Output in HMS (default)")
    format.add_argument('--dms', action='store_const', dest='fmt', const=AngleFormat.DMS, help="Output in DMS")
    format.add_argument('--degrees','-d', action='store_const', dest='fmt', const=AngleFormat.DEGREES, help='Output in decimal degrees')
    format.add_argument('--decimal-hours', action='store_const', dest='fmt', const=AngleFormat.DECIMAL_HOURS, help='Output decimal hours')
    format.add_argument('--sexagesimal','-s', action='store_const', dest='fmt', const=AngleFormat.SEXAGESIMAL, help="Output sexagesimal with ':' as separator")
    
        
    args = parser.parse_args()
    
    if (args.lat is None) != (args.lon is None):
        parser.error("Both --lat and --lon must be provided together, or neither")

    time = None
    if args.time is not None:
        time = parse_time_arg(args.time)
        if args.local:
            if 'now' in args.time:
                pass
            else:
                local_tz = datetime.now().astimezone().tzinfo
                time = time.replace(tzinfo=local_tz).astimezone(UTC)
                # assume that the date that we got from parse_time_arg (which is utc by default) is
                # actually supposed to be a local time obj. get that local time as utc    
        
    loc = tmo_loc
    if args.lat is not None:
        loc = LocationInfo(name="unkn", region="UNKN",timezone="UTC",
                        latitude=args.lat,longitude=args.lon)
    
    lst = get_current_sidereal_time(loc)
    
    RA = input_to_angle(args.ra,hms=True)
    
    if time is None:
        time = datetime.now(UTC)
    ha = get_hour_angle(RA, time, lst, loc)    

    outstr = format_angle_str(ha, args.fmt, args.precision)
    
    print(outstr)
    if args.copy:
        copy_to_clipboard(outstr)
        
if __name__ == "__main__":
    sys.exit(main())
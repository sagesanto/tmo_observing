# Sage Santomenna 2026

import sys, os
from argparse import ArgumentParser
from astral import LocationInfo, Observer
from datetime import datetime
from pytz import UTC

from tmo_obs.utils import ( get_current_sidereal_time, dateToSidereal, current_dt_utc, tmo_loc, 
                           parse_time_arg, get_current_hour_angle, get_hour_angle, input_to_angle )

def main():
    parser = ArgumentParser(description="Get the hour angle of a target with the provided RA, now or in the future")

    parser.add_argument('ra', type=str, help='RA of the target, in hms, decimal deg, or colon-separated format')

    coord_group = parser.add_argument_group("location", "Provide both latitude and longitude to get LST at sites other than TMO, or neither for TMO")
    coord_group.add_argument("--lat", type=float, required=False, help="Decimal latitude, deg")
    coord_group.add_argument("--lon", type=float, required=False, help="Decimal longitude, deg")
    
    parser.add_argument('time',nargs='?',type=str, help="[Optional] Time to get LST at. Assumes current if this arg is not provided. Datetime, in format YY-MM-DDTHH:MM:SS, or given relative to a date or to special keyword 'now', ex. now+1hr, now+2h3m2s or {some date}+3hr2s, {some date}-13hr")
    parser.add_argument('--local',action='store_true',help="Interpret the provided time as local instead of UTC. Will not work as intended if the provided date is relative to 'now'")
    
    format = parser.add_mutually_exclusive_group()
    
    format.add_argument('--degrees','-d', action='store_true',help='Give output in decimal degrees instead of hms.')
    format.add_argument('--decimal-hours', action='store_true',help='Give output in decimal hours instead of hms.')
    format.add_argument('--sexagesimal','-s', action='store_true',help="Give output in sexagesimal with ':' as separator")
    
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
    
    if args.degrees:
        print(f"{ha.to_value('deg'):.2f}")
        return
    
    if args.decimal_hours:
        kwargs = dict(decimal=True,precision=4)
    else:
        kwargs = dict(sep=(':' if args.sexagesimal else 'hms'), precision=2)
    print(ha.to_string(**kwargs))
        
if __name__ == "__main__":
    sys.exit(main())
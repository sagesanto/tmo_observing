# Sage Santomenna 2026

import sys
from argparse import ArgumentParser
import rich
from rich.table import Table as rich_table
from rich import box

from tmo_obs.utils import input_to_angle, format_angle_str, AngleFormat, copy_to_clipboard, determine_angle_fmt

def main():
    parser = ArgumentParser(description="Convert angles between degrees, hms/dms, decimal deg, decimal hours")

    parser.add_argument('angles', type=str, nargs='+', help='Angles to convert, in hms/dms, decimal deg, or colon-separated format.')
    parser.add_argument('--precision','-p', type=int, default=None,help="Precision of the output. Default is 5 places for decimal degrees or hours and 0 for DMS, HMS, and sexagesimal")
    parser.add_argument('--copy','-c',action='store_true',help="Copy the output to clipboard in addition to printing it. Only applicable when: used with the raw argument using auto formatting OR (using raw AND the number of requested output formats is one).")
    parser.add_argument('--raw','-r',action='store_true',help="Print only the angles, with no additional information")
    
    format = parser.add_argument_group("Output format", "If not provided, will automatically choose output format based on input format")
    format.add_argument('--hms', action='store_const', const=AngleFormat.HMS, help="Output in HMS (default)")
    format.add_argument('--dms', action='store_const', const=AngleFormat.DMS, help="Output in DMS")
    format.add_argument('--degrees','-d', action='store_const', const=AngleFormat.DEGREES, help='Output in decimal degrees')
    format.add_argument('--decimal-hours', action='store_const', const=AngleFormat.DECIMAL_HOURS, help='Output decimal hours')
    format.add_argument('--sexagesimal','-s', action='store_const', const=AngleFormat.SEXAGESIMAL, help="Output sexagesimal with ':' as separator")
    format.add_argument('--all','-a', action='store_true', help="Output in all formats")
    
    args = parser.parse_args()
    angles = [input_to_angle(a) for a in args.angles]
    
    formats = [args.degrees, args.hms, args.dms, args.decimal_hours, args.sexagesimal]
    formats = [f for f in formats if f is not None]
    if args.all:
        formats = [AngleFormat.DEGREES, AngleFormat.HMS, AngleFormat.DMS, AngleFormat.SEXAGESIMAL, AngleFormat.DECIMAL_HOURS]
    auto_format = len(formats) == 0  # if the user didnt specify an output format, determine it automatically
    
    if auto_format:
        fmted_angs = []
        table = rich_table(box=box.SIMPLE,show_footer=True)
        for i, (ang, input_ang) in enumerate(zip(angles, args.angles)):
            current_fmt = determine_angle_fmt(input_ang)
            output_fmt = AngleFormat.DEGREES if current_fmt != AngleFormat.DEGREES else AngleFormat.HMS
            fmted_angs.append(format_angle_str(ang, output_fmt, args.precision))
            table.add_column(f"'{input_ang}'", footer=output_fmt.name,justify='center')
        raw_outstr = ' '.join(fmted_angs)
        if args.copy:
            copy_to_clipboard(raw_outstr)
        if args.raw:
            print(raw_outstr)
            exit(0)
        else:
            table.add_row(*fmted_angs)
            rich.print(table)
        exit(0)
    
    fmted_angs = []
    if args.raw:
        table = rich_table(box=None,show_header=False)
    else:
        table = rich_table(box=box.SIMPLE,show_footer=True)
        table.add_column('Format',style='reverse')
    for input_ang in args.angles:
        table.add_column(f"'{input_ang}'")
    for format in formats:
        row = [format.name] if not args.raw else []
        for ang in angles:
            fmted = format_angle_str(ang, format, args.precision)
            row.append(fmted)
            fmted_angs.append(fmted)
        table.add_row(*row)
    if len(angles) == 1 and args.raw:
        outstr = ' '.join(fmted_angs)
        print(outstr)
        if args.copy:
            copy_to_clipboard(outstr)
        exit(0)
    rich.print(table)
        
    
if __name__ == "__main__":
    sys.exit(main())
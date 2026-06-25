from datetime import datetime, timedelta
from pytz import UTC
from astropy.time import Time
from pandas.io import clipboard

def timestr(dt):
    return dt.strftime("%m/%d/%Y %H:%M")

def file_timestamp(dt:datetime=None):
    if dt is None:
        dt = current_dt_utc()
    return dt.strftime("%Y%m%d_%H_%M")    

def current_dt_utc():
    try:
        return datetime.now(UTC)
    except: 
        return datetime.utcnow().replace(tzinfo=UTC)

def jd_to_dt(hjd):
    time = Time(hjd, format='jd', scale='tdb')
    return time.to_datetime().replace(tzinfo=UTC)

def dt_to_jd(datetime):
    return Time(datetime).jd

def is_numeric(s):
    try:
        float(s)
        return True
    except ValueError:
        if s == '.':
            return True
        return False
    
SECOND_UNITS = ['s', 'sec', 'secs', 'second', 'seconds']
MINUTE_UNITS = ['m', 'min', 'mins', 'minute', 'minutes']
HOUR_UNITS = ['h', 'hr', 'hrs', 'hour', 'hours']

def parse_time_quantity(qstring):
    """Parse a duration of time from a string like '1min', '1m', '2d3h2s', etc
    """
    vals, units = [], []
    working_str = ''
    is_val = is_numeric(qstring[0])
    for char in qstring:
        if is_numeric(char):
            if not is_val:
                if not working_str:
                    raise ValueError(f"Invalid quantity string '{qstring}'")
                units.append(working_str)
                working_str = ''
            is_val = True
            working_str += char
        else:
            if is_val:
                if not working_str:
                    raise ValueError(f"Invalid quantity string '{qstring}'")
                vals.append(float(working_str))
                working_str = ''
            working_str += char
            is_val = False
    if is_val:
        raise ValueError(f"Invalid quantity string '{qstring}' - cannot end with a unitless number")
    units.append(working_str)

    dt = timedelta(seconds=0)
    for val, unit in zip(vals, units):
        if unit in SECOND_UNITS:
            dt += timedelta(seconds=val)
        elif unit in MINUTE_UNITS:
            dt += timedelta(minutes=val)
        elif unit in HOUR_UNITS:
            dt += timedelta(hours=val)
        else:
            raise ValueError(f"Invalid time unit '{unit}' in quantity string '{qstring}'")
    return dt

def parse_absolute_time(tstr,fmt='%Y-%m-%dT%H:%M:%S'):
    try:
        return datetime.strptime(tstr, fmt).replace(tzinfo=UTC)
    except Exception as exc:
        if tstr == 'now':
            return datetime.now(tz=UTC)
        raise ValueError(
            f"Error parsing absolute time argument '{tstr}': {exc}. "
            "Valid format for absolute time is 'YYYY-MM-DDTHH:MM:SS' or 'now'"
        ) from exc

def parse_time_arg(s):
    try:
        return parse_absolute_time(s)
    except Exception as exc:
        if '+' in s or '-' in s:
            try:
                s = s.replace(' ', '')
                t = datetime.now(tz=UTC)
                if '+' in s:
                    base = s.split('+')[0]
                    relative = s.split('+')[1]
                    t = parse_absolute_time(base)
                    t += parse_time_quantity(relative)
                if s.count('-') == 1:
                    base = s.split('-')[0]
                    relative = s.split('-')[1]
                    t = parse_absolute_time(base)
                    t -= parse_time_quantity(relative)
                if s.count('-') > 2:
                    base = '-'.join(s.split('-')[:-1])
                    relative = s.split('-')[-1]
                    t = parse_absolute_time(base)
                    t -= parse_time_quantity(relative)
                return t
            except Exception as relative_exc:
                raise ValueError(
                    f"Error parsing relative time argument '{s}': {relative_exc}. "
                    f"Valid format for relative time is 'now+XXUU', 'now+XXUUXXUU', or 'now+XXUUXXUUXXUU', where XX is a number and UU is a valid time unit. All valid time units: {SECOND_UNITS}, {MINUTE_UNITS}, {HOUR_UNITS} "
                    "Examples: now+1hr, now-2h3m2s, {some date}+3hr2s, {some date}-13hr"
                ) from relative_exc
        raise ValueError(f"Error parsing time argument '{s}': {exc}") from exc

def copy_to_clipboard(content:str):
    clipboard.copy(content)
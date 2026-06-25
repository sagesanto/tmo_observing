import re
import inspect
from functools import wraps
from typing import Union

from astropy.coordinates import Angle
from astropy import units as u
from astropy.units import Quantity

from enum import Enum

from tmo_obs.utils.general import is_numeric

class AngleFormat(Enum):
    DEGREES = 'degrees'
    HMS = 'hms'
    DMS = 'dms'
    DECIMAL_HOURS = 'decimal_hours'
    SEXAGESIMAL = 'sexagesimal'

def ensure_angle(value, quantity_name=None, assume_unit=u.deg) -> Angle:
    """Ensure that the value argument is an angle, converting if possible. Gives float arguments the assumed units. Tries to cast arguments with units to an angular unit and then converts to Angle. """
    if isinstance(value, Angle):
        return value
    try:
        value = float(value)
    except: 
        pass
    try:
        if isinstance(value, str) or isinstance(value, tuple):
            return Angle(value)
        value.to(assume_unit)
        return Angle(value)
    except u.UnitsError as e:
        if isinstance(value, Quantity):
            if quantity_name is not None:
                raise u.UnitsError(f"{quantity_name} must have units equivalent to degrees.") from e
            raise u.UnitsError("Quantity must have units equivalent to degrees.") from e
    except Exception:
        pass
    if isinstance(value,float):
        return Angle(value * assume_unit)
    if quantity_name is not None:
        raise TypeError(f"{quantity_name} must be an Angle or a float (not {type(value)}).")
    raise TypeError(f"Quantity must be an Angle or a float (not {type(value)}).")

def determine_angle_fmt(user_input):
    try:
        a = ensure_angle(user_input)
    except:
        return None
    try:
        a = float(user_input)
        return AngleFormat.DEGREES
    except:
        pass
    if user_input.endswith('h'):
        return AngleFormat.DECIMAL_HOURS
    if ':' in user_input:
        return AngleFormat.SEXAGESIMAL
    if 'h' in user_input:
        return AngleFormat.HMS
    if 'd' in user_input:
        return AngleFormat.DMS
    raise ValueError(f"can't guess format for '{user_input}'")
    # try:
        

def ensure_angles(func):
    """Wraps a function and ensures that any arguments with the Angle type annotation are Angles by passing them through ``ensure_angle`` """
    sig = inspect.signature(func)

    angle_params = {name for name, param in sig.parameters.items() if param.annotation is Angle}

    @wraps(func)
    def wrapper(*args, **kwargs):
        bound = sig.bind(*args, **kwargs)

        for name in angle_params:
            value = bound.arguments[name]
            bound.arguments[name] = ensure_angle(value,quantity_name=name)
            
        return func(*bound.args, **bound.kwargs)
    return wrapper


def input_to_angle(text, hms:bool=None):
    """
    Try to convert user string into angle. developed for use in Maestro, may be generally useful
    :rtype: Angle
    """
    try:
        return ensure_angle(float(text))
    except:
        pass
    
    if hms is None:
        hms = not 'd' in text
    
    dh, minutes, seconds = 0, 0, [0]
    vals = list(map(float, [t for t in re.split("[:dhms]", text) if t]))
    if ':' in text:
        dh, minutes, *seconds = vals
    else:
        chars = [c for c in text if not is_numeric(c)]
        for i,c in enumerate(chars):
            if c in ('d','h'):
                dh = vals[i]
            if c == 'm':
                minutes = vals[i]
            if c == 's':
                seconds = [vals[i]]                

    sign = text[0] if text[0] in ("+", "-") else ""
    if hms:
        text = f"{sign}{abs(int(dh))}h{int(minutes)}m{seconds[0]}s" if seconds else f"{sign}{abs(int(dh))}h{int(minutes)}m"
    else:
        text = f"{sign}{abs(int(dh))}d{int(minutes)}m{seconds[0]}s" if seconds else f"{sign}{abs(int(dh))}d{int(minutes)}m"
    return ensure_angle(text)

def format_angle_str(angle:Angle, fmt:AngleFormat, precision:Union[int,None]=None):
    if precision is None:
        precision = 5 if fmt in (AngleFormat.DEGREES, AngleFormat.DECIMAL_HOURS) else 0
    
    if fmt == AngleFormat.DEGREES:
        return f"{angle.to_value('deg'):.{precision}f}"
    if fmt == AngleFormat.DECIMAL_HOURS:
        return angle.to_string(decimal=True, unit='hourangle', precision=precision)+'h'
    
    kwargs = dict(precision=precision)
    if fmt == AngleFormat.SEXAGESIMAL:
        kwargs.update(dict(sep=':', unit='hourangle'))
    elif fmt == AngleFormat.HMS:
        kwargs.update(dict(sep='hms', unit='hourangle'))
    elif fmt == AngleFormat.DMS:
        kwargs.update(dict(sep='dms', unit='degree'))
        
    return angle.to_string(**kwargs)
    
def wrap_around(value):
    a = -180
    b = 180
    return (value - a) % (b - a) + a
import json
from collections.abc import Iterable
from datetime import datetime, timezone
import pytz
from pytz import UTC

import numpy as np
import numpy.typing as npt
from shapely import geometry

from astropy.coordinates import AltAz, Angle, EarthLocation, SkyCoord
from astropy import units as u
from astropy.time import Time

from astral import LocationInfo
from skyfield import almanac
from skyfield.api import wgs84, Loader

from tmo_obs.config import data_path

from tmo_obs.utils.angles import ensure_angle, ensure_angles, wrap_around
from tmo_obs.utils.general import current_dt_utc


LATITUDE = 34.3819
LONGITUDE = -117.6815
ELEVATION = 2254 # meters, sourced from tmocass library

tmo_loc = LocationInfo(name="TMO", region="CA/USA",timezone="UTC",
                        latitude=LATITUDE,longitude=LONGITUDE)
tmo_observer = tmo_loc.observer
tz = pytz.timezone(tmo_loc.timezone)

# from skyfield.api import load
load = Loader(data_path)
ts = load.timescale()
eph = load("de440s.bsp")  # or de421.bsp
location = wgs84.latlon(latitude_degrees=LATITUDE,
                        longitude_degrees=LONGITUDE,
                        elevation_m=ELEVATION)
skyfield_observer = eph["Earth"] + location
sun_state = almanac.dark_twilight_day(eph, location)


def skyfield_time(dt: datetime):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return ts.from_datetime(dt)

def is_astronomical_night(dt: datetime) -> bool:
    return sun_state(skyfield_time(dt)) == 0

def is_civil_night(dt: datetime) -> bool:
    return sun_state(skyfield_time(dt)) <= 2

def is_civil_twilight(dt: datetime) -> bool:
    return sun_state(skyfield_time(dt)) == 3

def get_current_sidereal_time(locationInfo=tmo_loc,kind="mean"):
    now = current_dt_utc()
    # now = current_dt_utc().replace(second=0, microsecond=0)
    return Time(now).sidereal_time(longitude=locationInfo.longitude,kind=kind)

def dateToSidereal(dt: datetime, current_sidereal_time):
    """Apply an offset to get a sidereal time from a datetime object, using the current sidereal time as a reference. Assumes the current sidereal time is, in fact, current."""
    timeDiff = dt.astimezone(UTC) - current_dt_utc()
    sidereal_factor = 1.0027
    st = current_sidereal_time + Angle(str(timeDiff.total_seconds() * sidereal_factor / 3600) + "h")
    # st = st.wrap_at(360 * u.deg)
    return st

def get_current_hour_angle(ra:Angle, location:LocationInfo=tmo_loc):
    """Gets the current hour angle of a target with the given ra. See also get_hour_angle

    :param ra: the right ascension of the target to find the hour angle of
    :type ra: Angle
    :param location: location of the observatory, defaults to tmo_loc
    :type location: LocationInfo, optional
    :return: the current hour angle, as an Angle
    :rtype: Angle
    """
    sidereal = dateToSidereal(current_dt_utc(), get_current_sidereal_time(location))
    return Angle(wrap_around((sidereal - ra).deg), unit=u.deg)

def get_hour_angle(ra:Angle, dt:datetime, current_sidereal_time=None, location=tmo_loc):
    """Gets the hour angle of a target with the given ra at time dt. See also get_hour_angle

    :param ra: the right ascension of interest
    :type ra: Angle
    :param dt: the time at which to find the hour angle
    :type dt: datetime
    :param current_sidereal_time: the current sidereal time at the observatory location, if avoiding recomputation when calling this function in a loop is desired
    :type current_sidereal_time: Angle, optional
    :param location: location of the observatory, defaults to tmo_loc
    :type location: LocationInfo, optional
    :return: the current hour angle, as an Angle
    :rtype: Angle
    """
    if current_sidereal_time is None:
        current_sidereal_time = get_current_sidereal_time(location)
    sidereal = dateToSidereal(dt, current_sidereal_time)
    ra = ensure_angle(ra)
    return Angle(wrap_around((sidereal - ra).deg), unit=u.deg)


@ensure_angles
def alt_az(ra:Angle, dec:Angle, dt:datetime, loc=tmo_loc):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    target = SkyCoord(ra=ra, dec=dec, frame="icrs")
    observer_location = EarthLocation(
        lat=loc.latitude * u.deg,
        lon=loc.longitude * u.deg,
        height=ELEVATION * u.m,
    )
    altaz = target.transform_to(AltAz(obstime=Time(dt), location=observer_location))
    return Angle(altaz.alt), Angle(altaz.az)

@ensure_angles
def ra_dec(alt:Angle, az:Angle, dt:datetime, loc=tmo_loc):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    observer_location = EarthLocation(
        lat=loc.latitude * u.deg,
        lon=loc.longitude * u.deg,
        height=ELEVATION * u.m,
    )
    target = SkyCoord(
        alt=alt,
        az=az,
        frame=AltAz(obstime=Time(dt), location=observer_location),
    )
    icrs = target.transform_to("icrs")
    return Angle(icrs.ra), Angle(icrs.dec)


def load_horizon_box(horizon_box_path, BBOX_BUFFER_DEG):
    """Load a json file specifying the pointing limits (horizon box) of the telescope

    :param horizon_box_path: the path to the horizon box file
    :type horizon_box_path: str
    :param BBOX_BUFFER_DEG: shrink the horizon box edges by this many degrees as a safety margin
    :type BBOX_BUFFER_DEG: float
    :return: the horizon box
    :rtype: shapely.geometry.Polygon
    """
    with open(horizon_box_path, "r") as f:
        data = json.load(f)
    HORIZON_BOX = {}
    for i in np.arange(len(data),step=2):
        HORIZON_BOX[tuple(data[i])] = tuple(data[i+1])

    def sign(num):
        return 0 if num == 0 else num/abs(num)

    # ugly - shrink the bbox by BBOX_BUFFER_DEG
    HORIZON_BOX_2 = HORIZON_BOX.copy()
    for k,v in HORIZON_BOX.items():
        v1 = (sign(v[0]) * (abs(v[0])-BBOX_BUFFER_DEG), sign(v[1]) * (abs(v[1])-BBOX_BUFFER_DEG))
        HORIZON_BOX_2[k] = v1
    HORIZON_BOX = HORIZON_BOX_2

    _bbox_x, _bbox_y = [],[]
    for (min_dec,max_dec),(min_ha,max_ha) in HORIZON_BOX.items():
        _bbox_x.append(min_ha); _bbox_y.append(min_dec)
        _bbox_x.append(min_ha); _bbox_y.append(max_dec)
        _bbox_x.append(max_ha); _bbox_y.append(min_dec)
        _bbox_x.append(max_ha); _bbox_y.append(max_dec)
    _bbox_x = np.array(_bbox_x)
    _bbox_y = np.array(_bbox_y)

    neg_x = _bbox_x[_bbox_x<0]
    neg_x_y = _bbox_y[_bbox_x<0]
    pos_x = _bbox_x[_bbox_x>=0]
    pos_x_y = _bbox_y[_bbox_x>=0]
    bbox_x = np.concatenate([neg_x,pos_x[::-1],[neg_x[0]]])
    bbox_y = np.concatenate([neg_x_y,pos_x_y[::-1],[neg_x_y[0]]])
    paired = np.c_[bbox_x, bbox_y]
    line = geometry.LineString(paired)
    bbox = geometry.Polygon(line)
    return bbox

def points_along_slew(ha_i,dec_i, ha_f, dec_f):
    x = np.linspace(0,ha_f-ha_i,1000)+ha_i
    y = np.linspace(0,dec_f-dec_i,1000)+dec_i
    return np.c_[x,y]

def zenith_slew_required(bbox:geometry.Polygon, ra_i:float, dec_i:float, ra_f:float, dec_f:float, obstime:datetime) -> bool:
    """Determine whether a slew between (ra_i, dec_i) and (ra_f, dec_f) at time obstime would involve crossing outside of the supplied horizon box (bbox), requiring instead an intermediate slew to zenith"""
    lst = get_current_sidereal_time()
    # the assumption here is that the slew is relatively short so that obstime is basically the same at the beginning and end of the slew. this should already be fine; the bbox buffer makes it even more fine
    ha_i = get_hour_angle(ra_i, obstime, lst).to_value('degree')
    ha_f = get_hour_angle(ra_f, obstime, lst).to_value('degree')
    slew = points_along_slew(ha_i, dec_i, ha_f, dec_f)
    line = geometry.LineString(slew)
    return not bbox.contains(line)

def is_observable(ra, dec, dt, bbox, check_night=True, lst=None,night_type='astronomical'):
    if lst is None:
        lst = get_current_sidereal_time()
    # if not isinstance(ra, Angle):
    #     ra = ra * u.deg
    ha = get_hour_angle(ra,dt,lst)
    p = geometry.Point(ha.degree, dec.degree)
    at_night = True
    if check_night:
        if night_type == 'astronomical':
            at_night = is_astronomical_night(dt)
        if night_type == 'civil':
            at_night = is_civil_night(dt) 
    return bbox.contains(p) and at_night

@ensure_angles
def observability_mask(ra:Angle, dec:Angle, dts, bbox, check_night=True, night_type='astronomical', lst=None):
    if isinstance(ra, Iterable):
        return np.array([is_observable(r, d, t, bbox, check_night=check_night, night_type=night_type, lst=lst) for r, d, t in zip(ra, dec, dts)])
    return np.array([is_observable(ra, dec, t, bbox, check_night=check_night, night_type=night_type, lst=lst) for t in dts])

def break_into_windows(mask:npt.NDArray[np.bool_], t_arr:npt.NDArray):
    """Take a mask that corresponds to an array of times and returns a list of windows that correspond to continuous windows of 'True' values. For example, if `mask` is an array that is True if a target is observable and False otherwise and `t_arr` is the array of times at which this mask was calculated, this function will return a list of [start, end] windows where the target is continuously observable.

    :param mask: a true-false mask (ex. a mask that is true if a target is observable and false otherwise)
    :type mask: np.ndarray[bool]
    :param t_arr: an array of times (can be datetimes, timestamps, or really anything at all) with a corresponding entry for each entry of mask 
    :type t_arr: np.ndarray
    :return: a list of [start, end] windows that correspond to continuous runs of 'True' values, where the start and end values are drawn from t_arr and so are of the same type as t_arr
    :rtype: list
    """
    windows = []
    current_window = None
    for i, y in enumerate(mask):
        if y and current_window is None:
            current_window = [t_arr[i], t_arr[i]]
        elif y and current_window is not None:
            current_window[1] = t_arr[i]
        elif not y and current_window is not None:
            windows.append(current_window)
            current_window = None
    if current_window is not None:
        windows.append(current_window)
    return windows
import pytest
from astropy import units as u
from astropy.coordinates import Angle

from tmo_obs.utils import (
    AngleFormat,
    determine_angle_fmt,
    ensure_angle,
    ensure_angles,
    format_angle_str,
    input_to_angle,
    wrap_around,
)


def assert_angles_match(left, right, tolerance_arcsec=1e-6):
    left_angle = ensure_angle(left)
    right_angle = ensure_angle(right)
    difference = (left_angle - right_angle).wrap_at(180 * u.deg)
    assert abs(difference.arcsecond) <= tolerance_arcsec

@pytest.mark.angles
def test_determining_angle_format():
    assert determine_angle_fmt('0h38m08.11s') == AngleFormat.HMS
    assert determine_angle_fmt('10d40m37.17s') == AngleFormat.DMS
    assert determine_angle_fmt('10.2h') == AngleFormat.DECIMAL_HOURS
    assert determine_angle_fmt('01:02:03') == AngleFormat.SEXAGESIMAL
    assert determine_angle_fmt(123.28) == AngleFormat.DEGREES
    assert determine_angle_fmt('123.28') == AngleFormat.DEGREES
    assert determine_angle_fmt('not-an-angle') is None


@pytest.mark.angles
@pytest.mark.parametrize(
    ('value', 'expected_degrees'),
    [
        (123.28, 123.28),
        ('123.28', 123.28),
        ('10.2h', 153.0),
        ('0h38m08.11s', Angle('0h38m08.11s').degree),
        ('10d40m37.17s', Angle('10d40m37.17s').degree),
    ],
)
def test_ensure_angle_parses_supported_inputs(value, expected_degrees):
    angle = ensure_angle(value)
    assert angle.degree == pytest.approx(expected_degrees)


@pytest.mark.angles
def test_ensure_angle_converts_quantities_and_reports_invalid_units():
    assert ensure_angle(2 * u.hourangle).degree == pytest.approx(30.0)

    with pytest.raises(u.UnitsError, match='must have units equivalent to degrees'):
        ensure_angle(5 * u.m, quantity_name='ra')

    with pytest.raises(TypeError, match='must be an Angle or a float'):
        ensure_angle((1, 2, 3))

    with pytest.raises(TypeError, match='must be an Angle or a float'):
        ensure_angle(object(), quantity_name='ra')


@pytest.mark.angles
@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        ('123.28', Angle(123.28, unit=u.deg)),
        ('0h38m08.11s', Angle('0h38m08.11s')),
        ('10d40m37.17s', Angle('10d40m37.17s')),
        ('01:02:03', Angle('1h2m3s')),
        ('-01:02:03', Angle('-1h2m3s')),
        ('-12d30m15s', Angle('-12d30m15s')),
    ],
)
def test_input_to_angle_parses_text_inputs(text, expected):
    assert_angles_match(input_to_angle(text), expected)


@pytest.mark.angles
@pytest.mark.parametrize(
    ('angle', 'fmt', 'precision'),
    [
        (Angle('123.45678d'), AngleFormat.DEGREES, 5),
        (Angle('10.2h'), AngleFormat.DECIMAL_HOURS, 4),
        (Angle('0h38m08.11s'), AngleFormat.HMS, 2),
        (Angle('10d40m37.17s'), AngleFormat.DMS, 2),
        (Angle('0h38m08.11s'), AngleFormat.SEXAGESIMAL, 2),
    ],
)
def test_format_angle_round_trip_through_input_to_angle(angle, fmt, precision):
    formatted = format_angle_str(angle, fmt, precision=precision)
    reparsed = input_to_angle(formatted)
    tolerance_arcsec = 10 ** (-precision) * 3600 if fmt in (AngleFormat.DEGREES, AngleFormat.DECIMAL_HOURS) else 10 ** (-precision)
    assert_angles_match(reparsed, angle, tolerance_arcsec=tolerance_arcsec)


@pytest.mark.angles
def test_format_detection_and_round_trip_stay_consistent():
    samples = [
        Angle('0h38m08.11s'),
        Angle('10d40m37.17s'),
        Angle('123.28d'),
        Angle('-12d30m15s'),
    ]
    formats = [
        AngleFormat.HMS,
        AngleFormat.DMS,
        AngleFormat.SEXAGESIMAL,
        AngleFormat.DEGREES,
        AngleFormat.DECIMAL_HOURS,
    ]

    for angle in samples:
        for fmt in formats:
            formatted = format_angle_str(angle, fmt, precision=3)
            detected = determine_angle_fmt(formatted)
            if fmt == AngleFormat.HMS:
                assert detected == AngleFormat.HMS
            elif fmt == AngleFormat.DMS:
                assert detected == AngleFormat.DMS
            elif fmt == AngleFormat.SEXAGESIMAL:
                assert detected == AngleFormat.SEXAGESIMAL
            elif fmt == AngleFormat.DEGREES:
                assert detected == AngleFormat.DEGREES
            else:
                assert detected == AngleFormat.DECIMAL_HOURS
            if fmt == AngleFormat.DEGREES:
                tolerance_arcsec = 10 ** (-3) * 3600
            elif fmt == AngleFormat.DECIMAL_HOURS:
                tolerance_arcsec = 10 ** (-3) * 15 * 3600
            else:
                tolerance_arcsec = 10 ** (-3)
            assert_angles_match(input_to_angle(formatted), angle, tolerance_arcsec=tolerance_arcsec)


@pytest.mark.angles
def test_ensure_angles_decorator_coerces_annotated_arguments():
    @ensure_angles
    def add_angles(left: Angle, right: Angle, label: str):
        return left + right, label

    result, label = add_angles('10d0m0s', 5.5, label='sum')
    assert isinstance(result, Angle)
    assert result.degree == pytest.approx(15.5)
    assert label == 'sum'


@pytest.mark.angles
@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        (0, 0),
        (180, -180),
        (181, -179),
        (-181, 179),
        (540, -180),
    ],
)
def test_wrap_around(value, expected):
    assert wrap_around(value) == expected
    
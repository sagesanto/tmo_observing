import pytest

from tmo_obs.utils import determine_angle_fmt, AngleFormat

@pytest.mark.angles
def test_determining_angle_format():
    assert determine_angle_fmt('0h38m08.11s') == AngleFormat.HMS
    assert determine_angle_fmt('10d40m37.17s') == AngleFormat.DMS
    assert determine_angle_fmt('10.2h') == AngleFormat.DECIMAL_HOURS
    assert determine_angle_fmt(123.28) == AngleFormat.DEGREES
    assert determine_angle_fmt('123.28') == AngleFormat.DEGREES
    
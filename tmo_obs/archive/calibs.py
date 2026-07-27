from tmo_obs.archive.configuration import has_matching_camera_configuration


def is_dark(obs_details:dict):
    if "FILTER" not in obs_details: return False
    return obs_details['FILTER'] == 'DARK' and obs_details['ExposureTime'] > 0 and 'dark' in obs_details['Name'].lower()


def is_bias(obs_details:dict):
    if "FILTER" not in obs_details: return False
    return obs_details['FILTER'] == 'DARK' and obs_details['ExposureTime'] < 1e-5 and "bias" in obs_details['Name'].lower()


def is_flat(obs_details:dict):
    if "FILTER" not in obs_details: return False
    return obs_details['FILTER'] != 'DARK' and obs_details['ExposureTime'] > 0 and "twilight" in obs_details['Name'].lower()


def bias_matches(bias_details:dict,obs_details:dict):
    return is_bias(bias_details) and has_matching_camera_configuration(bias_details, obs_details)


def dark_matches(exptime_tolerance:float, dark_details:dict, obs_details:dict):
    if not is_dark(dark_details) or not has_matching_camera_configuration(dark_details, obs_details):
        return False
    return abs(dark_details['ExposureTime'] - obs_details['ExposureTime']) <= exptime_tolerance


def flat_matches(flat_details:dict, obs_details:dict):
    if not is_flat(flat_details) or not has_matching_camera_configuration(flat_details, obs_details):
        return False
    if not flat_details.get('FILTER') or not obs_details.get('FILTER'):
        return False
    return flat_details['FILTER'] == obs_details['FILTER']


def is_calib(obs_details:dict):
    return is_flat(obs_details) or is_bias(obs_details) or is_dark(obs_details)


def is_science(obs_details):
    name = obs_details['Name']
    return not is_calib(obs_details) and "re-center" not in name.lower() and 'recenter' not in name.lower() and 'focusloop' not in name.lower() and 'focusloop' not in obs_details['Description'].lower()

def has_matching_camera_configuration(details_1:dict, details_2:dict):
    for k in ['Camera Name','Binning Size','ROI_StartX','ROI_StartY','ROI_Width','ROI_Height']:
        if details_1.get(k) != details_2.get(k):
            return False
    for k in ['Binning Mode','Operation Mode','Gain']:
        if details_1['cam_params'].get(k) != details_2['cam_params'].get(k):
            return False
    return True
import tomli
import sys, os
from os.path import join, dirname, pardir, abspath
import shutil

logging_config_path = join(dirname(__file__), "logging.json")
data_path = join(dirname(__file__), "data")
os.makedirs(data_path,exist_ok=True)

def get_stub_path():
    stub_directory = dirname(__file__)
    return join(stub_directory,'stub.toml')
    
def get_config_path():
    stub_path = get_stub_path()
    if not os.path.exists(stub_path):
        shutil.copy(f"{stub_path}.example",stub_path)
        print(f"[tmo_obs]: Initialized {stub_path} by copying {stub_path.example} because {stub_path} did not exist. See file for details.")
    with open(stub_path,'rb') as f:
        stub = tomli.load(f)
    try:
        return stub['OBS_CONFIG_PATH']
    except KeyError as e:
        raise KeyError(f"Can't find an OBS_CONFIG_PATH entry in {stub_path} that points to an observing config file. See {stub_path}.example for details.") from e

def load_config():
    config_path = get_config_path()
    stub_path = get_stub_path()
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Can't find config file {config_path}. If you think tmo_obs should use a different config file, change the OBS_CONFIG_PATH entry in {stub_path}. Otherwise, make sure this file exists.")
    with open(get_config_path(), 'rb') as f:
        config = tomli.load(f)        
    return config

def config_info():
    stub_path = get_stub_path()
    config_path = get_config_path()
    config = load_config()  # just check that everything actually works
    return f"Config loaded from {config_path}. Stub config file (which points to main config) is at {stub_path}."
import sys, os
from os.path import join, dirname, pardir, abspath
from pathlib import Path
import shutil
import json
import logging
import logging.config
import tomli

logging_config_path = join(dirname(__file__), "logging.json")
data_path = join(dirname(__file__), "data")  # ex. the sun ephemeris file goes here (downloaded on first run)
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

def configure_logger(name, outfile_path=None):
    # first, check if the logger has already been configured
    if logging.getLogger(name).hasHandlers():
        return logging.getLogger(name)
    try:
        with open(logging_config_path, 'r') as log_cfg:
            logging.config.dictConfig(json.load(log_cfg))
            logger = logging.getLogger(name)
            # set outfile of existing filehandler. need to do this instead of making a new handler in order to not wipe the formatter off
            # NOTE RELIES ON FILE HANDLER BEING THE SECOND HANDLER
            root_logger = logging.getLogger()
            if outfile_path is not None:
                file_handler = root_logger.handlers[1]
                file_handler.setStream(Path(outfile_path).open('a'))
            else:
                # remove the file handler
                root_logger.removeHandler(root_logger.handlers[1])
            try:
                os.remove("should_be_set_by_code.log")  # pardon this
            except:
                pass

    except Exception as e:
        print(f"Can't load logging config ({e}). Using default config.")
        logger = logging.getLogger(name)
        if outfile_path is not None:
            file_handler = logging.FileHandler(outfile_path, mode="a+")
            logger.addHandler(file_handler)

    return logger
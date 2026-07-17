#!/usr/bin/env python3
import os
import sys
import logging
from config_loader import CONFIG

LOG_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

LEVEL_MAP = {'DEBUG': logging.DEBUG, 'INFO': logging.INFO,
             'WARNING': logging.WARNING, 'ERROR': logging.ERROR}

def get_logger(name: str):
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    level = LEVEL_MAP.get(CONFIG.get('logging', {}).get('level', 'INFO'), logging.INFO)
    logger.setLevel(level)

    log_file = CONFIG.get('logging', {}).get('file', 'logs/hil.log')
    fh = logging.FileHandler(os.path.join(LOG_DIR, os.path.basename(log_file)))
    fh.setLevel(level)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
                            datefmt='%Y-%m-%d %H:%M:%S')
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger
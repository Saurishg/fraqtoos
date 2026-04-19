#!/usr/bin/env python3
"""Central logger — all bots write to /home/work/fraqtoos/logs/fraqtoos.log"""
import logging, os, sys
from logging.handlers import RotatingFileHandler

LOG_DIR  = "/home/work/fraqtoos/logs"
LOG_FILE = os.path.join(LOG_DIR, "fraqtoos.log")
os.makedirs(LOG_DIR, exist_ok=True)

def get_logger(name: str = "fraqtoos") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s  %(name)-16s  %(levelname)-8s  %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger

log = get_logger()

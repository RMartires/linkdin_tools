"""Logging configuration"""

import logging
import sys
from typing import Optional

def setup_logger(name: str = "linkedin_automate", level: int = logging.INFO) -> logging.Logger:
    """Set up and configure logger"""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False  # Prevent propagation to root logger to avoid duplicate logs
    
    # Avoid duplicate handlers
    if logger.handlers:
        return logger
    
    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    return logger

# Default logger instance
logger = setup_logger()

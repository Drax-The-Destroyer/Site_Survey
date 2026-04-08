"""
Production-grade logging framework for the Site Survey application.

Provides structured logging with:
- File output (INFO and above) with rotation
- Console output (WARNING and above)
- Contextual fields (timestamp, level, module, message)
"""

import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logger(name: str) -> logging.Logger:
    """
    Setup a logger with both file and console handlers.
    
    Args:
        name: Logger name (typically __name__ from calling module)
        
    Returns:
        Configured logger instance
        
    Configuration:
        - File: logs/survey.log (INFO+, max 10MB, 5 backups)
        - Console: stderr (WARNING+)
    """
    logger = logging.getLogger(name)
    
    # Only configure if not already done
    if logger.handlers:
        return logger
    
    logger.setLevel(logging.INFO)
    
    # Create logs directory if it doesn't exist
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    
    # File handler - INFO and above, with rotation
    log_file = os.path.join(log_dir, "survey.log")
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    
    # Console handler - WARNING and above
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    
    # Format: timestamp | level | module | message
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

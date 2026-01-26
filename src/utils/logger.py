
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from colorama import Fore, Style, init

# Initialize Colorama
init(autoreset=True)

class LogManager:
    _instances = {}

    @staticmethod
    def get_logger(name, log_file=None, level=logging.INFO, console=True):
        """
        Returns a configured logger instance.
        Ensures handlers are not added multiple times.
        """
        if name in LogManager._instances:
            return LogManager._instances[name]

        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.propagate = False # Prevent double logging if attached to root

        formatter = logging.Formatter(
            '%(asctime)s [%(name)s] [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        if log_file:
            # Ensure log dir exists
            log_dir = os.path.dirname(log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir)

            # Rotating File Handler (UTF-8 Enforced)
            file_handler = RotatingFileHandler(
                log_file, 
                maxBytes=10*1024*1024, # 10MB
                backupCount=5, 
                encoding='utf-8'
            )
            file_handler.setFormatter(formatter)
            file_handler.setLevel(level)
            logger.addHandler(file_handler)

        if console:
            # Console Handler with Colors (Optional enhancement could go here)
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            console_handler.setLevel(level)
            logger.addHandler(console_handler)

        LogManager._instances[name] = logger
        return logger

    @staticmethod
    def setup_console_colors():
        # Helper to make raw prints colored if needed, though logger handles formatting
        pass

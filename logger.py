import logging
import sys


def setup_logger(name: str = "aeolus") -> logging.Logger:
    logger = logging.getLogger(name)

    if not logger.handlers and name == "aeolus":
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)

        formatter = logging.Formatter("[%(name)s] %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


def get_logger(module_name: str) -> logging.Logger:
    return logging.getLogger(f"aeolus.{module_name}")


aeolus_logger = setup_logger("aeolus")

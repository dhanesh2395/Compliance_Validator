import logging
import os
import sys


def get_logger(name: str):
    logger = logging.getLogger(name)

    if not logger.handlers:
        logger.setLevel(logging.DEBUG)

        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        )

        # -----------------------------
        # UTF-8 Console Handler
        # -----------------------------
        sys.stdout.reconfigure(encoding='utf-8')

        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(formatter)

        # -----------------------------
        # UTF-8 File Handler
        # -----------------------------
        os.makedirs("logs", exist_ok=True)

        fh = logging.FileHandler(
            "logs/app.log",
            encoding="utf-8"
        )

        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)

        logger.addHandler(ch)
        logger.addHandler(fh)

        logger.propagate = False

    return logger
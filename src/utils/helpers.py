"""Various helper utilities."""

import logging

logging.basicConfig(level=logging.INFO)


def log(message: str) -> None:
    logging.info(message)

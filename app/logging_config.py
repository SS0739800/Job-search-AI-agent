import logging


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # httpx logs every request at INFO; keep that out of normal output.
    logging.getLogger("httpx").setLevel(logging.DEBUG if verbose else logging.WARNING)

# app/device_manager.py

import logging
import os

from .mentalab_device import (
    mentalab_device_manager as real_manager,
)

from .simulated_device import (
    simulated_mentalab_device_manager
    as simulated_manager,
)


logger = logging.getLogger(
    "mentalab.manager"
)


# ============================================================
# MODE SELECTION
# ============================================================

MENTALAB_MODE = (
    os.getenv(
        "MENTALAB_MODE",
        "real",
    )
    .strip()
    .lower()
)


if MENTALAB_MODE == "simulator":

    mentalab_device_manager = (
        simulated_manager
    )

    logger.warning(
        "===================================================="
    )

    logger.warning(
        "MENTALAB BRIDGE RUNNING IN SIMULATOR MODE"
    )

    logger.warning(
        "NO PHYSICAL EEG DEVICE WILL BE USED"
    )

    logger.warning(
        "SIMULATED RECORDINGS MUST NOT BE USED "
        "AS CLINICAL DATA"
    )

    logger.warning(
        "===================================================="
    )

elif MENTALAB_MODE == "real":

    mentalab_device_manager = (
        real_manager
    )

    logger.info(
        "Mentalab Bridge running "
        "in REAL DEVICE mode."
    )

else:
    raise RuntimeError(
        "Invalid MENTALAB_MODE. "
        "Expected 'real' or 'simulator', "
        f"received '{MENTALAB_MODE}'."
    )
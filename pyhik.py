"""Source-checkout compatibility shim; install/import hikvision_native instead."""

import warnings

from hikvision_native import *  # noqa: F403

warnings.warn(
    "pyhik is now hikvision_native; this checkout shim is not part of the wheel",
    DeprecationWarning,
    stacklevel=2,
)

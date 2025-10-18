"""Compatibility proxy for :mod:`coolbox.setup.stages`."""
# pyright: reportUnsupportedDunderAll=none
from __future__ import annotations

from coolbox.setup import stages as _stages
from coolbox.setup.stages import *  # type: ignore F401,F403

__all__ = list(getattr(_stages, "__all__", []))

if hasattr(_stages, "_candidate_site_packages"):
    _candidate_site_packages = _stages._candidate_site_packages
    __all__.append("_candidate_site_packages")
if hasattr(_stages, "_installed_packages"):
    _installed_packages = _stages._installed_packages
    __all__.append("_installed_packages")
if hasattr(_stages, "_missing_requirements"):
    _missing_requirements = _stages._missing_requirements
    __all__.append("_missing_requirements")
if hasattr(_stages, "_parse_requirements"):
    _parse_requirements = _stages._parse_requirements
    __all__.append("_parse_requirements")

__all__ = tuple(dict.fromkeys(__all__))

del _stages

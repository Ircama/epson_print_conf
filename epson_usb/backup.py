"""Bank-0 backups, in the same JSON format the standalone tool has always used.

Keeping the format identical is not cosmetic: a backup taken by
``epson_l3251_usb_reset.py`` before it grew a library must still restore with
the library, and vice versa. The file is::

    {"time": "20260904_100412", "bank0": {"00": 12, "01": null, ..., "FF": 94}}

Addresses are two *upper-case* hex digits as strings, values are integers or
``null`` for "could not read". Nothing else is added: no serial number, no
device path, nothing machine specific.
"""

from __future__ import annotations

import json
import os
import time
from typing import Dict, Iterable, Mapping, Optional, Sequence, Union

__all__ = [
    "BACKUP_PREFIX",
    "default_filename",
    "save_backup",
    "load_backup",
    "cells_from_backup",
    "resolve_backup_path",
    "backup_addrs",
]

BACKUP_PREFIX = "epson_backup_bank0_"


def default_filename(when: Optional[str] = None) -> str:
    """``epson_backup_bank0_<YYYYmmdd_HHMMSS>.json`` (the ``time`` field format)."""
    return BACKUP_PREFIX + (when or time.strftime("%Y%m%d_%H%M%S")) + ".json"


def save_backup(
    cells: Mapping[Union[int, str], Optional[int]],
    directory: Optional[str] = None,
    when: Optional[str] = None,
    filename: Optional[str] = None,
) -> str:
    """Write ``cells`` and return the **absolute** path actually used.

    The caller decides where: a backup describes one printer's state and
    should land somewhere the user chose, not in whatever directory the
    process happens to be in.
    """
    timestamp = when or time.strftime("%Y%m%d_%H%M%S")
    name = filename or default_filename(timestamp)
    path = os.path.abspath(os.path.join(directory, name) if directory else name)
    payload = {"time": timestamp, "bank0": {_addr_key(k): v for k, v in cells.items()}}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return path


def load_backup(path: str) -> dict:
    """Read a backup file and return its raw JSON content."""
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def cells_from_backup(data: Union[str, bytes, bytearray, dict]) -> Dict[int, Optional[int]]:
    """Normalise a backup (path, JSON text, or already-parsed dict) to cells.

    Accepts bare hex keys as well as ``0x``-prefixed ones and ints, and an
    absent ``bank0`` wrapper, so a hand-written file works too.
    """
    if isinstance(data, (str, bytes, bytearray)):
        text = data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else data
        stripped = text.lstrip()
        if stripped.startswith("{"):
            parsed = json.loads(text)
        else:
            parsed = load_backup(text)
    else:
        parsed = data or {}
    bank = parsed.get("bank0", parsed) if isinstance(parsed, dict) else {}
    cells: Dict[int, Optional[int]] = {}
    for key, value in (bank or {}).items():
        # Int keys are real addresses; string keys are hex.
        address = key if isinstance(key, int) else int(str(key), 16)
        cells[address] = None if value is None else int(value)
    return cells


def resolve_backup_path(path: str, search_dirs: Optional[Sequence[str]] = None) -> str:
    """Resolve a backup path, looking in ``search_dirs`` for a bare filename.

    A bare filename is looked for in the current directory first, then in each
    of ``search_dirs`` (the standalone tool passes the directory it lives in,
    so backups taken next to the script keep being found).
    """
    if os.path.isfile(path):
        return path
    if not os.path.dirname(path):
        for directory in search_dirs or ():
            if not directory:
                continue
            candidate = os.path.join(directory, path)
            if os.path.isfile(candidate):
                return candidate
    return path


def backup_addrs(cells: Mapping[Union[int, str], object]) -> Iterable[int]:
    """Address list of a backup, sorted (helper for report-style diffs)."""
    return sorted(int(str(k), 16) for k in cells)


def _addr_key(address: Union[int, str]) -> str:
    return "%02X" % (int(str(address), 16) if isinstance(address, str) else int(address))

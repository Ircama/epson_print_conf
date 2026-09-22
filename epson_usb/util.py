"""Small helpers with no dependencies and no side effects."""

from __future__ import annotations

from typing import Iterable, Optional, Union

__all__ = ["hexdump", "mask_serial", "to_int", "parse_int_list"]

HEX_ALPHABET = "0123456789abcdefABCDEF"


def hexdump(data: Optional[bytes], indent: str = "") -> str:
    """``b'\\x41'`` -> ``"41   |A|"``; ``None`` -> ``"(none/timeout)"``.

    This is the format the historical probe printed for every packet, and it
    is kept byte-for-byte so that old issue reports can still be read.
    """
    if data is None:
        return "(none/timeout)"
    if isinstance(data, str):
        return data
    if not data:
        return "(empty)"
    text = "".join(chr(c) if 32 <= c < 127 else "." for c in data)
    return indent + " ".join("%02x" % c for c in data) + "   |" + text + "|"


def mask_serial(serial: Optional[str], keep: int = 4) -> str:
    """Hide all but the last ``keep`` characters of a serial number.

    Empty and unreadable values pass through unchanged, so this can be applied
    to anything without changing the meaning of the output.
    """
    if not serial or serial == "(unreadable)":
        return serial or ""
    if len(serial) <= keep:
        return "*" * len(serial)
    return "*" * (len(serial) - keep) + serial[-keep:]


def to_int(value: Union[int, str, bytes]) -> int:
    """Accept ``12``, ``"12"``, ``"0x0c"``, ``b"\\x0c"`` and hex strings."""
    if isinstance(value, int):
        return value
    if isinstance(value, (bytes, bytearray)):
        if len(value) == 1:
            return value[0]
        return int.from_bytes(value, "big")
    text = value.strip()
    if text.lower().startswith("0x"):
        return int(text, 16)
    return int(text, 0)


def parse_int_list(values: Union[str, Iterable[Union[int, str]]]) -> list:
    """Parse ``"0x30:0,0x31:0"`` or a list of ints into a list of lists.

    Two shapes are accepted, because both are convenient at a command line:

    * ``"30:0,31:0"``                  -> ``[[48, 0], [49, 0]]``
    * ``"30,31"``                      -> ``[[48], [49]]``
    """
    if isinstance(values, str):
        items = [i for i in values.replace(" ", "").split(",") if i]
        pairs = []
        for item in items:
            if ":" in item:
                left, right = item.split(":", 1)
                pairs.append([to_int(left), to_int(right)])
            else:
                pairs.append([to_int(item)])
        return pairs
    out = []
    for item in values:
        if isinstance(item, (list, tuple)):
            out.append([to_int(v) for v in item])
        else:
            out.append([to_int(item)])
    return out


def chunked(iterable: Iterable, size: int) -> Iterable[list]:
    """Yield lists of at most ``size`` items (used to batch EEPROM reads)."""
    if size <= 0:
        raise ValueError("size must be positive")
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch

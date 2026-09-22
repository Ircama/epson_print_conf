r"""The ``@BDC ST2`` status block.

The printer answers the EPSON-CTRL ``st`` command with a proprietary block::

    00 '@' 'B' 'D' 'C' ' ' 'S' 'T' '2' CR LF   <len: little endian uint16>   <elements...>
    element := <type: 1 byte> <length: 1 byte> <item: length bytes>

``epson_print_conf`` decodes that block in full -- dozens of element types,
decoded into names, ink levels, error codes. Reimplementing all of it here
would be a second, drifting copy of somebody else's work. So this module does
two things and no more:

* it splits the block into elements faithfully (same grammar, same length
  check), and understands the handful of elements *this* package needs -- the
  serial number (``0x40``, ``0x1f``) and the maintenance box counters
  (``0x37``),
* :func:`full_status` hands the raw bytes to ``epson_print_conf``'s own
  ``status_parser`` when that package is importable, so USB users get the
  complete decode without a line of it being duplicated here. That parser
  touches no instance state (it is effectively a static method), which is why
  calling it on the class is safe.

The mock printer in :mod:`epson_usb.backends.mock` builds its status block with
:func:`build_st2`, so the same bytes travel the USB path and the SNMP path in
the compatibility tests.
"""

from __future__ import annotations

import struct
from typing import Dict, List, Optional, Sequence, Tuple, Union

__all__ = [
    "ST2_HEADER",
    "ELEMENT_SERIAL_NO_INFO",
    "ELEMENT_SERIAL",
    "ELEMENT_STATUS",
    "ELEMENT_MAINTENANCE_BOX",
    "build_st2",
    "parse_st2",
    "serial_from_status",
    "full_status",
]

ST2_HEADER = b"\x00@BDC ST2\r\n"
_HEADER_LEN = len(ST2_HEADER)

ELEMENT_STATUS = 0x01
ELEMENT_SERIAL = 0x1F
ELEMENT_MAINTENANCE_BOX = 0x37
ELEMENT_SERIAL_NO_INFO = 0x40
ELEMENT_INK_REPLACEMENT_COUNTER = 0x45


def build_st2(elements: Sequence[Tuple[int, bytes]]) -> bytes:
    """Assemble a status block from ``(type, item)`` pairs.

    Used by the fake printer and by the tests. The same function makes it
    possible to write a *minimal* status block for a model that does not
    report every element a real one does.
    """
    body = bytearray()
    for ftype, item in elements:
        if not 0 <= ftype <= 0xFF:
            raise ValueError("element type out of range: %r" % (ftype,))
        if len(item) > 0xFF:
            raise ValueError("element longer than 255 bytes")
        body += bytes([ftype, len(item)]) + bytes(item)
    return ST2_HEADER + struct.pack("<H", len(body)) + bytes(body)


def parse_st2(data: Union[bytes, bytearray, str]) -> Dict[str, object]:
    """Split a status block into elements and extract the fields we use.

    Returns a dict with ``raw``, ``elements`` (``type -> item``, last wins),
    ``element_list`` (in order), ``serial_number_info`` (element 0x40 decoded
    as text when it is printable), ``serial`` (element 0x1f) and
    ``maintenance_box`` (a few element-0x37 quantities, left as bytes: their
    meaning depends on the model, and guessing it would be worse than saying
    nothing).

    Anything that does not look like a status block comes back as
    ``{"error": ...}`` rather than raising, because a printer that answers
    nonsense is a diagnosable condition, not an exception in the middle of a
    read.
    """
    if isinstance(data, str):
        data = data.encode("latin-1", "replace")
    data = bytes(data or b"")
    if len(data) < _HEADER_LEN + 3:
        return {"error": "status block too short (%d bytes)" % len(data), "raw": data}
    if data[:_HEADER_LEN] != ST2_HEADER:
        start = data.find(ST2_HEADER[1:])
        if start < 0:
            return {"error": "not an @BDC ST2 block", "raw": data}
        # Keep the lead byte that precedes the '@' (a well-formed block has
        # 0x00 there -- upstream's status_parser validates exactly that byte);
        # supply one if the block was found at offset 0.
        data = (data[start - 1:start] or b"\x00") + data[start:]
    declared = struct.unpack("<H", data[_HEADER_LEN : _HEADER_LEN + 2])[0]
    body = data[_HEADER_LEN + 2 :]
    truncated = len(body) != declared
    out: Dict[str, object] = {"raw": data}
    elements: Dict[int, bytes] = {}
    element_list: List[Tuple[int, bytes]] = []
    pos = 0
    while pos < len(body):
        if pos + 2 > len(body):
            out["error"] = "invalid element header"
            break
        ftype, length = body[pos], body[pos + 1]
        pos += 2
        item = body[pos : pos + length]
        if len(item) != length:
            out["error"] = "invalid element length"
            break
        pos += length
        elements[ftype] = item
        element_list.append((ftype, item))
    if truncated:
        out["error"] = (
            "declared length %d does not match %d bytes received"
            % (declared, len(body))
        )
    out["elements"] = elements
    out["element_list"] = element_list

    serial_info = elements.get(ELEMENT_SERIAL_NO_INFO)
    if serial_info:
        try:
            out["serial_number_info"] = serial_info.decode()
        except Exception:
            out["serial_number_info"] = str(serial_info)
    serial = elements.get(ELEMENT_SERIAL)
    if serial:
        try:
            out["serial"] = serial.decode()
        except Exception:
            out["serial"] = str(serial)
    box = elements.get(ELEMENT_MAINTENANCE_BOX)
    if box:
        out["maintenance_box"] = {"raw": box, "length": len(box)}
    status = elements.get(ELEMENT_STATUS)
    if status and len(status) == 1:
        out["status"] = status[0]
    return out


def serial_from_status(data) -> Optional[str]:
    """Best-effort plaintext serial number from a status block.

    This is what makes the ``rw`` service command usable on firmware that
    locks EEPROM access: the status block reports the serial in plaintext even
    when the EEPROM cannot be read.
    """
    parsed = parse_st2(data) if not isinstance(data, dict) else data
    for key in ("serial_number_info", "serial"):
        value = parsed.get(key)
        if value and "?" not in value:
            return value
    return None


def full_status(data, prefer_upstream: bool = True) -> object:
    """Decode a status block, using ``epson_print_conf`` when available.

    Falls back to :func:`parse_st2` (a documented subset) when the upstream
    package is not installed. The returned type therefore differs: upstream
    returns its own dict, the fallback returns ours. Callers that need
    stability should use :func:`parse_st2` directly.
    """
    if prefer_upstream:
        parser = _upstream_status_parser()
        if parser is not None:
            try:
                return parser(data)
            except Exception:
                pass
    return parse_st2(data)


def _upstream_status_parser():
    """Return ``epson_print_conf.EpsonPrinter.status_parser`` unbound, or None."""
    try:
        from epson_print_conf import EpsonPrinter
    except Exception:
        return None
    parser = getattr(EpsonPrinter, "status_parser", None)
    if parser is None:
        return None
    # It reads no instance attribute, so calling it on the class is safe;
    # verify that assumption rather than trusting it.
    try:
        parser(None, b"\x00@BDC ST2\r\n\x00\x00")
    except AttributeError:
        return None
    except Exception:
        return parser
    return parser

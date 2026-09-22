r"""EPSON-CTRL: the command language that carries EEPROM access and service calls.

Every message has the same shape::

    "||" or "rw"    2-byte ASCII name
    <len>           2-byte little endian payload length
    <payload>       len bytes

Two transports carry these messages, and this module knows both, which is the
whole trick behind the ``epson_print_conf`` integration:

* **D4** -- the message goes straight into a packet on the ``EPSON-CTRL``
  socket (:mod:`epson_usb.d4`).
* **SNMP** -- the message bytes become the tail of an OID under
  ``1.3.6.1.4.1.1248.1.2.2.44.1.1.2.1`` (:func:`snmp_oid`).

Because the two directions are a bijection, a program written against the
SNMP transport can keep building OIDs untouched, and this package can parse
the OID back into the exact bytes the USB link has to carry:
:func:`parse_snmp_oid` is the inverse of :func:`snmp_oid`, and
``testler/test_uyumluluk.py`` checks that against the real
``epson_print_conf.EpsonPrinter.epctrl_snmp_oid`` whenever that package is
importable.

The EEPROM access frame (``||``) is documented in the Epson LX-300+II /
LX-1170II service manuals (single-byte form) and reproduced, in the two-byte
form used by recent printers, by ``epson_print_conf``::

    read : 7C 7C 07 00 <r1> <r2> 41 BE A0 <lo> <hi>
    write: 7C 7C 10 00 <r1> <r2> 42 BD 21 <lo> <hi> <value> <wkey x8>

where ``41`` is ``'A'``, ``BE`` is ``~'A' & 0xFF``, ``A0`` is
``('A' >> 1 & 0x7F) | ('A' << 7 & 0x80)``, and the same derivation applies to
``42/BD/21`` for ``'B'``. The reply is an ``@BDC PS`` block ending with
``0x0C``::

    00 @BDC PS 0D 0A EE:0032AC; 0C        read  (address 0x0032, value 0xAC)
    00 @BDC PS 0D 0A ||:OK; 0C            write accepted
    00 @BDC PS 0D 0A ||:NA; 0C            write refused (wrong key, locked)
"""

from __future__ import annotations

import hashlib
import re
import struct
from typing import Optional, Tuple, Union

__all__ = [
    "SNMP_OID_PREFIX",
    "READ_LETTER",
    "WRITE_LETTER",
    "packet_command",
    "parse_frame",
    "opcode_triplet",
    "eeprom_read_payload",
    "eeprom_write_payload",
    "eeprom_read_frame",
    "eeprom_write_frame",
    "rw_payload",
    "rw_frame",
    "status_frame",
    "device_id_frame",
    "version_frame",
    "cartridges_frame",
    "parse_eeprom_reply",
    "write_confirmed",
    "write_rejected",
    "is_terminated",
    "snmp_oid",
    "is_epson_ctrl_oid",
    "parse_snmp_oid",
]

#: OID prefix ``epson_print_conf`` prepends to an EPSON-CTRL message.
SNMP_OID_PREFIX = "1.3.6.1.4.1.1248.1.2.2.44.1.1.2.1"

READ_LETTER = ord("A")
WRITE_LETTER = ord("B")

# EEPROM access keys are *not* here, and deliberately so: they differ per
# printer family, which makes them data rather than protocol. Every function
# below takes them as parameters, so a caller supplies them from its own tables
# (in this repository: epson_l3250.py).

_EEPROM_REPLY_RE = re.compile(rb"EE:([0-9A-Fa-f]{6})")
_TERMINATOR = 0x0C


# --------------------------------------------------------------------------- #
#  Framing
# --------------------------------------------------------------------------- #
def packet_command(name: Union[bytes, str], payload: bytes = b"") -> bytes:
    """Wrap ``payload`` in the generic ``name + le16 length + payload`` frame."""
    if isinstance(name, str):
        name = name.encode("ascii")
    if len(name) != 2:
        raise ValueError("an EPSON-CTRL command name is exactly 2 bytes, got %r" % name)
    return name + struct.pack("<H", len(payload)) + payload


def parse_frame(frame: bytes) -> Tuple[bytes, bytes]:
    """Split a frame back into ``(name, payload)``. Raises ``ValueError``."""
    if len(frame) < 4:
        raise ValueError("frame too short: %r" % (frame,))
    name = frame[:2]
    length = struct.unpack("<H", frame[2:4])[0]
    payload = frame[4 : 4 + length]
    if len(payload) != length:
        raise ValueError(
            "frame declares %d payload bytes but carries %d" % (length, len(payload))
        )
    return name, payload


def opcode_triplet(letter: int) -> bytes:
    """Derive the three opcode bytes Epson uses for a one-letter opcode.

    ``'A'`` -> ``41 BE A0``, ``'B'`` -> ``42 BD 21``. Kept as a function, and
    not as three literals, because the derivation is what the service manuals
    document; the byte layout tests pin the result.
    """
    return bytes(
        [
            letter & 0xFF,
            ~letter & 0xFF,
            ((letter >> 1) & 0x7F) | ((letter << 7) & 0x80),
        ]
    )


# --------------------------------------------------------------------------- #
#  EEPROM access
# --------------------------------------------------------------------------- #
def eeprom_read_payload(read_key, addr: int) -> bytes:
    """``<r1> <r2> 41 BE A0 <lo> <hi>`` (7 bytes) for address ``addr``."""
    if not 0 <= addr <= 0xFFFF:
        raise ValueError("EEPROM address out of range: %r" % (addr,))
    lo, hi = addr & 0xFF, (addr >> 8) & 0xFF
    return bytes([read_key[0], read_key[1]]) + opcode_triplet(READ_LETTER) + bytes([lo, hi])


def eeprom_write_payload(read_key, write_key, addr: int, value: int) -> bytes:
    """``<r1> <r2> 42 BD 21 <lo> <hi> <value> <wkey x8>`` (16 bytes)."""
    if not 0 <= addr <= 0xFFFF:
        raise ValueError("EEPROM address out of range: %r" % (addr,))
    if not 0 <= int(value) <= 0xFF:
        raise ValueError("EEPROM value must be one byte, got %r" % (value,))
    lo, hi = addr & 0xFF, (addr >> 8) & 0xFF
    return (
        bytes([read_key[0], read_key[1]])
        + opcode_triplet(WRITE_LETTER)
        + bytes([lo, hi, int(value)])
        + bytes(write_key)
    )


def eeprom_read_frame(read_key, addr: int) -> bytes:
    return packet_command(b"||", eeprom_read_payload(read_key, addr))


def eeprom_write_frame(read_key, write_key, addr: int, value: int) -> bytes:
    return packet_command(b"||", eeprom_write_payload(read_key, write_key, addr, value))


# --------------------------------------------------------------------------- #
#  Service commands
# --------------------------------------------------------------------------- #
def rw_payload(serial: str, mode: Optional[int] = None) -> bytes:
    r"""Payload of the ``rw`` ("reset waste") service command.

    ``mode=None`` -> ``00 || sha1(serial)`` -- 21 bytes, the form the
    historical standalone tool sends (reinkpy's ``Device.do_rw``).

    ``mode=1`` -> ``01 00 || sha1(serial)`` -- 22 bytes, the form
    ``epson_print_conf`` sends (``struct.pack('<H', mode)``). Both are
    reported to work; the difference is preserved here rather than guessed
    away, and which one to use is a parameter.
    """
    digest = hashlib.sha1(serial.encode("ascii")).digest()
    if mode is None:
        return b"\x00" + digest
    return struct.pack("<H", int(mode) & 0xFFFF) + digest


def rw_frame(serial: str, mode: Optional[int] = None) -> bytes:
    r"""The complete ``rw`` frame: ``rw <le16 length> <payload>``."""
    return packet_command(b"rw", rw_payload(serial, mode=mode))


def status_frame() -> bytes:
    """``st 01 00 01`` -- request the @BDC ST2 status block (as upstream sends)."""
    return packet_command(b"st", b"\x01")


def device_id_frame() -> bytes:
    """``di 01 00 01`` -- device identification (IEEE 1284 device id string)."""
    return packet_command(b"di", b"\x01")


def version_frame() -> bytes:
    """``vi 01 00 00`` -- firmware version."""
    return packet_command(b"vi", b"\x00")


def cartridges_frame() -> bytes:
    """``ia 01 00 00`` -- cartridge types."""
    return packet_command(b"ia", b"\x00")


# --------------------------------------------------------------------------- #
#  Reply parsing
# --------------------------------------------------------------------------- #
def parse_eeprom_reply(reply: bytes) -> Optional[Tuple[int, int]]:
    """Extract ``(address, value)`` from an ``@BDC PS ... EE:xxxxxx;`` reply.

    ``None`` when the block is absent or malformed. The address is *not*
    validated against the requested one here: that is the caller's job,
    because only the caller knows what it asked for.
    """
    if not reply:
        return None
    match = _EEPROM_REPLY_RE.search(reply)
    if not match:
        return None
    text = match.group(1).decode("ascii")
    return int(text[0:4], 16), int(text[4:6], 16)


def write_confirmed(reply: Optional[bytes]) -> bool:
    """True when a write reply says ``:OK;``."""
    return bool(reply) and b":OK;" in bytes(reply)


def write_rejected(reply: Optional[bytes]) -> bool:
    """True when a write reply says ``:NA;`` (refused, e.g. wrong key)."""
    return bool(reply) and b":NA;" in bytes(reply)


def is_terminated(reply: bytes) -> bool:
    """True when the reply carries the EPSON-CTRL terminator (0x0C)."""
    return bool(reply) and reply[-1] == _TERMINATOR


# --------------------------------------------------------------------------- #
#  SNMP OID bridge (the epson_print_conf door)
# --------------------------------------------------------------------------- #
def snmp_oid(command: Union[str, bytes], payload: Union[int, bytes, list]) -> str:
    """Encode an EPSON-CTRL message as the OID ``epson_print_conf`` uses.

    Byte-for-byte identical to ``EpsonPrinter.epctrl_snmp_oid``::

        >>> snmp_oid("st", 1)
        '1.3.6.1.4.1.1248.1.2.2.44.1.1.2.1.115.116.1.0.1'
        >>> snmp_oid("||", bytes.fromhex("4a 36 41 be a0 30 00"))
        '1.3.6.1.4.1.1248.1.2.2.44.1.1.2.1.124.124.7.0.74.54.65.190.160.48.0'
    """
    if isinstance(command, bytes):
        command = command.decode("ascii")
    if isinstance(payload, int):
        payload = bytes([payload])
    elif isinstance(payload, (list, tuple)):
        payload = bytes(payload)
    frame = packet_command(command, bytes(payload))
    return SNMP_OID_PREFIX + "." + ".".join(str(int(b)) for b in frame)


def is_epson_ctrl_oid(oid: str) -> bool:
    return isinstance(oid, str) and oid.startswith(SNMP_OID_PREFIX + ".")


def parse_snmp_oid(oid: str) -> Tuple[str, bytes]:
    """Inverse of :func:`snmp_oid`: ``OID -> (command, payload)``.

    Raises :class:`ValueError` for anything that is not an EPSON-CTRL OID,
    including the plain MIB OIDs ``epson_print_conf`` also queries (those
    cannot exist over USB and must be answered as "unavailable").
    """
    if not is_epson_ctrl_oid(oid):
        raise ValueError("not an EPSON-CTRL OID: %r" % (oid,))
    tail = oid[len(SNMP_OID_PREFIX) + 1 :]
    try:
        raw = bytes(int(part) for part in tail.split(".") if part != "")
    except ValueError as exc:
        raise ValueError("malformed EPSON-CTRL OID: %r" % (oid,)) from exc
    name, payload = parse_frame(raw)
    return name.decode("ascii"), payload

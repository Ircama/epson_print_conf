r"""An in-memory Epson printer that speaks D4 + EPSON-CTRL.

This is the backend the whole test suite rests on. It is not a stub that
returns canned answers: it is a state machine that consumes the *same* bytes a
printer would receive and produces the *same* framing a printer sends back --
packet-aligned D4 headers, the credit handshake, ``@BDC`` reply blocks,
``EE:xxxxxx;`` payloads, ``:OK;``/``:NA;``, an ``@BDC ST2`` status block.

Two consequences worth stating, because they are what makes the tests
meaningful:

* the protocol code under test never learns that it is talking to a fake, so a
  framing bug cannot be hidden by a permissive mock;
* the *historical* implementation (``epson_l3251_usb_reset.py`` before it grew
  a library) can be pointed at the same fake by patching its two I/O
  functions, which is how ``tests/test_fidelity.py`` proves the library is a
  faithful port rather than a rewrite.

Only behaviours that are documented (or measured) are implemented. Corners
nobody has measured are deliberately answered with ``:NA;`` instead of a
plausible invention, and the docstrings say so.

**No model data here either.** The fake printer has to know *something* about
the printer it imitates -- the serial number's address range, the access keys
it should enforce, the cells a fresh EEPROM contains -- but those are the
caller's facts, not this module's: :meth:`MockConfig.from_model` reads them off
whatever object the caller's model database provides (duck-typed: ``read_key``,
``write_key``, ``serial_range``, ``full_reset_cells``, ``mirror_cells``), and
the defaults enforce nothing at all.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Sequence, Tuple

from ..d4 import D4_ENTER_SEQUENCE, build_packet, parse_packet
from ..epson_ctrl import (
    cartridges_frame,
    device_id_frame,
    packet_command,
    parse_frame,
    status_frame,
    version_frame,
)
from ..status import (
    ELEMENT_MAINTENANCE_BOX,
    ELEMENT_SERIAL_NO_INFO,
    ELEMENT_STATUS,
    build_st2,
)
from .base import EPSON_VID, DeviceInfo, Transport

__all__ = ["MockConfig", "MockPrinter", "MockTransport", "mock_eeprom", "MOCK_SERIAL"]

#: Serial number stored in the fake EEPROM and reported by the status block.
#: Deliberately not a real one.
MOCK_SERIAL = "MOCKSERIAL"

#: Main waste counter of the fake printer: the *measured* value of the
#: reference L3251 on 2026-09-04 (little endian 0x183B = 6203 = 97.72%). Read
#: big endian the same bytes are 15128 = 238%, so a decoding mistake shows up
#: immediately instead of looking merely pessimistic.
MOCK_COUNTER = 6203

#: Datasheet-ish device id string (the `di` command). Deliberately model-free:
#: a caller that wants the fake to imitate one family overrides
#: :attr:`MockConfig.device_id`, because this library knows no model names.
MOCK_DEVICE_ID = (
    b"MFG:EPSON;CMD:ESCPL2,BDC,D4;MDL:Epson in-memory printer;"
    b"CLS:PRINTER;DES:Epson in-memory printer;"
)

#: `vi` reply: 6 characters, interpreted by upstream as
#: day = fw[2:4], year = ord(fw[4:5]) + 1945, month = int(fw[5:], 16).
MOCK_FIRMWARE = b"AB11I5"


def _address_group(group: Sequence) -> Sequence:
    """Addresses out of a mirror group that may carry a label.

    Model tables often write mirrors as ``((0x30, 0x31), "ECC")`` -- addresses
    plus a label for a human. Only the addresses matter here, so both shapes
    are accepted; no label is ever invented.
    """
    if group and isinstance(group[0], (list, tuple, range)):
        return group[0]
    return group


def mock_eeprom(serial: str = MOCK_SERIAL,
                counter: Optional[int] = None,
                serial_range: Optional[Sequence[int]] = None,
                reset_cells: Sequence[Tuple[int, int]] = (),
                mirror_cells: Sequence[Sequence[int]] = (),
                values: Optional[Dict[int, int]] = None) -> Dict[int, int]:
    """A plausible EEPROM, from explicit facts about the printer to imitate.

    * ``serial_range`` -- where the serial number is stored, if at all;
    * ``reset_cells`` -- ``(address, value)`` pairs a fresh EEPROM contains;
    * ``mirror_cells`` -- address groups that all hold the same counter;
    * ``counter`` -- the counter value, little-endian, split across each group
      (default: the *measured* state of the reference printer on 2026-09-04,
      6203 = 97.72%, which is more useful than zeros: it is a printer that is
      nearly due for service, and the value makes a big-endian decode obviously
      wrong, since the same bytes then read 15128 = 238%);
    * ``values`` -- applied last, so a test can override anything.
    """
    if counter is None:
        counter = MOCK_COUNTER
    cells: Dict[int, int] = {}
    if serial_range is not None:
        addresses = list(serial_range)
        for index, char in enumerate(serial[: len(addresses)]):
            cells[addresses[index]] = ord(char)
    for addr, value in reset_cells:
        cells.setdefault(int(addr), int(value))
    for group in mirror_cells:
        for offset, addr in enumerate(_address_group(group)):
            cells[int(addr)] = (counter >> (8 * offset)) & 0xFF
    if values:
        cells.update(values)
    return cells


@dataclass
class MockConfig:
    """Behaviour switches of the fake printer.

    Only ``serial``, ``reply_prefix``, the device ids and the failure switches
    have defaults; everything model-shaped defaults to "enforce nothing", so a
    test that cares about a key or an address says so explicitly.
    """

    #: Name reported by ``describe()`` (a label, not a database entry).
    model_name: str = "in-memory printer"
    serial: str = MOCK_SERIAL
    vendor_id: int = EPSON_VID
    product_id: int = 0x118A
    #: Revision the device actually speaks. 0x10 (the L3250 family value)
    #: makes the host take the "retry with the printer's revision" path, so
    #: that branch is exercised by every test.
    revision: int = 0x10
    #: Firmware that locks EEPROM access (the L3250/ET-28xx situation).
    #: Reads and writes then answer ``:NA;``, like the real thing.
    eeprom_locked: bool = False
    #: Refuse writes only (reads keep working).
    read_only: bool = False
    #: Leading byte of an ``@BDC PS`` reply block. Real replies (per
    #: ``epson_print_conf.invalid_response``) begin with 0x00; a test flips
    #: this to 0x01 to prove the tolerant framing check.
    reply_prefix: bytes = b"\x00"
    eeprom: Dict[int, int] = field(default_factory=dict)
    #: Bytes the fake printer sends before the D4 reply to "enter D4"
    #: (a zero-length packet, which is what the host consumes and ignores).
    enter_reply: bytes = build_packet(0, 0, b"", credit=0, control=0)
    #: When True, `read()` always returns b"" -- a printer that went away.
    silent: bool = False
    #: The `di` answer, so a caller can have the fake report its own family.
    device_id: bytes = MOCK_DEVICE_ID
    #: Extra ST2 elements, appended to the generated status block.
    status_extras: Tuple[Tuple[int, bytes], ...] = ()
    #: Fake a device whose D4 handshake never succeeds.
    refuse_d4: bool = False

    # -- the caller's facts ------------------------------------------------
    #: The read key this fake enforces, as two bytes. ``None`` accepts any,
    #: which is the honest default for a library that knows no keys.
    read_key: Optional[Tuple[int, int]] = None
    #: The write key this fake enforces. ``None`` accepts any.
    write_key: Optional[bytes] = None
    #: Where the serial number lives, and the cells a fresh EEPROM holds.
    #: Used only to build the default EEPROM; set ``eeprom`` to bypass both.
    serial_range: Optional[range] = None
    reset_cells: Sequence[Tuple[int, int]] = ()
    mirror_cells: Sequence[Sequence[int]] = ()

    @classmethod
    def from_model(cls, model, **overrides) -> "MockConfig":
        """Build a config from any object carrying the caller's model facts.

        Duck-typed on purpose -- no model class is imported, so this module
        stays free of a printer database::

            MockConfig.from_model(epson_l3250.MODELS["L3251"], eeprom_locked=True)

        Recognised attributes (all optional): ``key``/``name`` (label),
        ``read_key``, ``write_key``, ``serial_range``, ``full_reset_cells``,
        ``mirror_cells``.
        """
        label = getattr(model, "key", None) or getattr(model, "name", None)
        read_key = getattr(model, "read_key", None)
        kwargs = dict(
            model_name=label or "in-memory printer",
            read_key=tuple(read_key) if read_key else None,
            write_key=bytes(getattr(model, "write_key", b"") or b"") or None,
            serial_range=getattr(model, "serial_range", None),
            reset_cells=tuple(getattr(model, "full_reset_cells", ()) or ()),
            mirror_cells=tuple(getattr(model, "mirror_cells", ()) or ()),
        )
        kwargs.update(overrides)
        return cls(**kwargs)

    def with_eeprom(self, cells: Optional[Dict[int, int]] = None,
                    **extra: int) -> "MockConfig":
        """A copy of this config with those EEPROM cells set.

        ``config.with_eeprom({0x30: 0x3B, 0x31: 0x18})`` -- a dict, because
        EEPROM addresses are integers and Python keywords cannot be.
        """
        merged = dict(self.eeprom)
        for key, value in list((cells or {}).items()) + list(extra.items()):
            merged[int(key)] = int(value)
        return replace(self, eeprom=merged)

    def default_eeprom(self) -> Dict[int, int]:
        """The EEPROM a fresh fake printer has, per the fields above."""
        return mock_eeprom(
            serial=self.serial,
            serial_range=self.serial_range,
            reset_cells=self.reset_cells,
            mirror_cells=self.mirror_cells,
        )

    def accepts_read_key(self, key: Sequence[int]) -> bool:
        """Is this read key acceptable? Anything is, unless one is enforced."""
        return self.read_key is None or tuple(key) == tuple(self.read_key)

    def accepts_write_key(self, key: bytes) -> bool:
        """Is this write key acceptable? Anything is, unless one is enforced."""
        return self.write_key is None or bytes(key) == bytes(self.write_key)


class MockPrinter:
    """The fake printer itself: feed it bytes, collect the bytes it answers."""

    def __init__(self, config: Optional[MockConfig] = None) -> None:
        self.config = config or MockConfig()
        if not self.config.eeprom:
            self.config = replace(self.config, eeprom=self.config.default_eeprom())
        self.in_d4 = False
        self.revision: Optional[int] = None
        self._inbuf = b""
        # -- observable state, for assertions ---------------------------------
        self.out = bytearray()
        self.wire_log = bytearray()
        self.frames: List[bytes] = []
        self.eeprom_writes: List[Tuple[int, int]] = []
        self.d4_packets: List[object] = []
        self.connect_seen = False

    # -- transport-facing --------------------------------------------------
    def feed(self, data: bytes) -> None:
        """Consume bytes written by the host."""
        self.wire_log += data
        if not self.in_d4:
            index = data.find(D4_ENTER_SEQUENCE)
            if index >= 0:
                self.in_d4 = True
                self.connect_seen = True
                self.out += self.config.enter_reply
            return
        buffer = self._inbuf + data
        while True:
            decoded = parse_packet(buffer)
            if decoded is None:
                break
            packet, buffer = decoded
            self.d4_packets.append(packet)
            self._handle_packet(packet)
        self._inbuf = buffer

    def read(self, maxlen: int = 1024) -> bytes:
        if self.config.silent:
            return b""
        chunk = bytes(self.out[:maxlen])
        del self.out[: len(chunk)]
        return chunk

    # -- protocol ----------------------------------------------------------
    def _reply(self, payload: bytes, psid: int = 0x02, credit: int = 0) -> None:
        """Queue one D4 packet on the control socket."""
        self.out += build_packet(psid, 0x02 if psid else 0, payload, credit=credit)

    def _control_reply(self, payload: bytes) -> None:
        self._reply(payload, psid=0x00, credit=1)

    def _handle_packet(self, packet) -> None:
        payload = packet.payload
        if not payload:
            return
        if packet.psid != 0:
            # Data on a logical socket: the payload *is* the EPSON-CTRL frame.
            self._handle_frame(payload)
            return
        opcode = payload[0]
        if opcode == 0x00:  # Init
            requested = payload[1] if len(payload) > 1 else 0
            if self.config.refuse_d4:
                return
            self.revision = self.config.revision
            if requested == self.config.revision:
                self._control_reply(bytes([0x80, 0x00, self.config.revision]))
            else:
                # result 0x02 = "not this revision", plus the one we speak.
                self._control_reply(bytes([0x80, 0x02, self.config.revision]))
        elif opcode == 0x01:  # OpenChannel
            self._control_reply(
                bytes([0x81, 0x00, 0x02, self.config.revision or 0x10])
                + struct.pack(">HHHH", 0x0100, 0x0100, 0x0000, 0x0080)
            )
        elif opcode == 0x03:  # host grants the printer reply credit
            self._control_reply(
                bytes([0x83, 0x02, 0x02, 0x00]) + struct.pack(">H", 0x0008)
            )
        elif opcode == 0x04:  # host takes send credit
            granted = 0xFFFF if b"\xff\xff" in payload else 0x0080
            self._control_reply(
                bytes([0x84, 0x02, 0x02, 0x00]) + struct.pack(">H", granted)
            )

    def execute(self, frame: bytes) -> bytes:
        """Run one EPSON-CTRL frame and return its reply payload.

        This is what a real printer's **SNMP agent** does with the payload of
        an ``EPSON_CTRL_TO_OID`` query: no D4 framing at all, just the command
        and its answer. It is what makes the compatibility test possible -
        the same fake printer answers both envelopes, and the frames each
        envelope delivers can then be compared byte for byte.
        """
        self.frames.append(frame)
        return self._frame_reply(frame)

    def _handle_frame(self, payload: bytes) -> None:
        self._reply(self.execute(payload))

    def _frame_reply(self, payload: bytes) -> bytes:
        try:
            name, data = parse_frame(payload)
        except ValueError:
            return b"||:;" + b"\x0c"
        if name == b"||":
            return self._eeprom_reply(data)
        if name == b"rw":
            return self._rw_reply(data)
        if name == b"st":
            return build_st2(self._status_elements())
        if name == b"di":
            return self._block(self.config.device_id)
        if name == b"vi":
            # Unlike every other command, the firmware version comes back *bare*
            # -- `vi:00:<6 chars>;` + 0x0C, with no `@BDC PS` header. That is what
            # the host's parser needs: its regex only yields the six characters
            # unchanged when the token starts the reply (the project README
            # records the measured result, 'RF11I5 11 May 2018').
            return b"vi:00:" + MOCK_FIRMWARE + b";" + b"\x0c"
        if name == b"ia":
            return self._block(b"IA:00;18XL,18XL,18XL,18XL;")
        # Documented answer for an unsupported command, quoted from the
        # protocol notes: the command name, ":;", terminator, no @BDC.
        return name + b":;" + b"\x0c"

    # -- replies -----------------------------------------------------------
    def _block(self, text: bytes) -> bytes:
        """An ``@BDC PS`` reply block: prefix + header + text + terminator."""
        return self.config.reply_prefix + b"@BDC PS\r\n" + text + b"\x0c"

    def _status_elements(self) -> List[Tuple[int, bytes]]:
        elements: List[Tuple[int, bytes]] = [
            (ELEMENT_STATUS, b"\x04"),  # Idle (ready to print)
            (ELEMENT_SERIAL_NO_INFO, self.config.serial.encode("ascii")),
            (ELEMENT_MAINTENANCE_BOX, b"\x01\x00\x00\x00"),
        ]
        elements.extend(self.config.status_extras)
        return elements

    def _eeprom_reply(self, data: bytes) -> bytes:
        if len(data) < 5:
            return self._block(b"||:NA;")
        read_key = (data[0], data[1])
        opcode = data[2]
        if not self.config.accepts_read_key(read_key):
            return self._block(b"||:NA;")
        if opcode == 0x41:  # read
            if len(data) < 7:
                return self._block(b"||:NA;")
            addr = data[5] | (data[6] << 8)
            if self.config.eeprom_locked:
                return self._block(b"||:NA;")
            value = self.config.eeprom.get(addr, 0) & 0xFF
            return self._block(b"EE:%04X%02X;" % (addr, value))
        if opcode == 0x42:  # write
            if len(data) < 8 + 8:
                return self._block(b"||:NA;")
            addr = data[5] | (data[6] << 8)
            value = data[7]
            write_key = bytes(data[8:16])
            if (
                self.config.eeprom_locked
                or self.config.read_only
                or not self.config.accepts_write_key(write_key)
            ):
                return self._block(b"||:NA;")
            self.config.eeprom[addr] = value
            self.eeprom_writes.append((addr, value))
            return self._block(b"||:OK;")
        return self._block(b"||:NA;")

    def _rw_reply(self, data: bytes) -> bytes:
        digest = hashlib.sha1(self.config.serial.encode("ascii")).digest()
        if data.endswith(digest):
            mode = data[0] if len(data) == len(digest) + 1 else None
            if mode is None and len(data) == len(digest) + 2:
                mode = data[0] | (data[1] << 8)
            return self._block(b"rw:%02X:OK;" % (mode or 0))
        return self._block(b"rw:00:NA;")


class MockTransport(Transport):
    """A :class:`~epson_usb.backends.base.Transport` over a :class:`MockPrinter`."""

    name = "mock"

    def __init__(self, config: Optional[MockConfig] = None,
                 printer: Optional[MockPrinter] = None) -> None:
        super().__init__()
        self.printer = printer or MockPrinter(config)
        self.config = self.printer.config
        self._info = DeviceInfo(
            backend=self.name,
            path="mock://%04x:%04x" % (self.config.vendor_id, self.config.product_id),
            vendor_id=self.config.vendor_id,
            product_id=self.config.product_id,
            serial=self.config.serial,
            description="in-memory fake printer (%s)" % self.config.model_name,
        )

    # -- Transport ---------------------------------------------------------
    def open(self) -> None:
        self._opened = True

    def close(self) -> None:
        self._opened = False

    def write(self, data: bytes, timeout_ms: int = 3000) -> int:
        self.printer.feed(bytes(data))
        return len(data)

    def read(self, maxlen: int = 1024, timeout_ms: int = 2000) -> bytes:
        return self.printer.read(maxlen)

    @classmethod
    def available(cls) -> bool:
        return True

    @classmethod
    def find(cls, vendor_id: Optional[int] = EPSON_VID, **kwargs) -> List[DeviceInfo]:
        config = kwargs.get("config") or MockConfig()
        if vendor_id is not None and config.vendor_id != vendor_id:
            return []
        return [
            DeviceInfo(
                backend="mock",
                path="mock://%04x:%04x" % (config.vendor_id, config.product_id),
                vendor_id=config.vendor_id,
                product_id=config.product_id,
                serial=config.serial,
                description="in-memory fake printer (%s)" % config.model_name,
            )
        ]


# Keep the default frames around so callers can inspect what the fake expects.
DEFAULT_STATUS_FRAME = status_frame()
DEFAULT_DEVICE_ID_FRAME = device_id_frame()
DEFAULT_VERSION_FRAME = version_frame()
DEFAULT_CARTRIDGES_FRAME = cartridges_frame()
DEFAULT_PACKET = packet_command

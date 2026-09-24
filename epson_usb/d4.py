"""IEEE 1284.4 ("D4") session over any :class:`~epson_usb.backends.base.Transport`.

This module is a direct port of the D4 code that was verified on hardware
(an Epson L3251 over USB on Windows, 2026-08-28 / 2026-09-04). Every byte
written, every timeout and the order of the handshake steps are preserved on
purpose: :mod:`epson_usb.tests.test_fidelity` replays the *historical*
implementation (frozen in ``epson_usb/tests/referans/``) against the
*historical* mock printer and asserts that this port produces an identical byte
stream -- the same key agreement, handshake packets, frame builders and golden
hex.

The protocol, in the order a session performs it:

1. **Enter D4** -- the printer is in "packet mode"; ``@EJL 1284.4`` announces
   D4 and the printer answers, leaving packet mode.
2. **Init** -- the host offers a revision (0x20). If the printer answers
   "not that revision" with its own revision (0x10 on the L3250 family), the
   host retries with the printer's. All later structures depend on the
   revision that ends up active.
3. **OpenChannel** -- opens socket 2, ``EPSON-CTRL``, where control commands
   travel (EEPROM access, ``st``, ``di``, ``rw`` ...). The reply format
   differs between revisions: on 0x10 an ``initCredit`` field is present.
4. **CreditRequest / Credit** -- D4 is credit based. The host must take send
   credit for the channel and grant the printer reply credit, otherwise the
   command is refused with error 0x81 ("no credit granted").
5. **Data** -- a packet on socket 2 carries the EPSON-CTRL frame; the reply
   is a packet on socket 2 whose payload is the command's answer, terminated
   by ``0x0C``.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from typing import Callable, NamedTuple, Optional, Sequence

from .backends.base import Transport
from .errors import D4Error, EepromError, NoReplyError

__all__ = [
    "D4_ENTER_SEQUENCE",
    "EPSON_CTRL_SOCKET",
    "Timeouts",
    "D4Packet",
    "build_packet",
    "parse_packet",
    "D4Session",
    "EpsonCtrlSession",
]

#: "Leave packet mode / enter D4" (EJL). Note the leading four bytes: the
#: length header the Windows print channel expects.
D4_ENTER_SEQUENCE = b"\x00\x00\x00\x1b\x01@EJL 1284.4\n@EJL\n@EJL\n"

#: Logical socket used for printer control (EEPROM, status, service commands).
EPSON_CTRL_SOCKET = 0x02

#: Revision the host offers first; the printer may answer with its own.
INITIAL_REVISION = 0x20

#: Revisions seen in the field. 0x10 is what the L3250 family negotiates.
REVISION_0X10 = 0x10


@dataclass
class Timeouts:
    """All timeouts of one session, in milliseconds.

    The defaults are the values the hardware-verified implementation used.
    They are collected here (instead of being spread as literals) so that a
    test, or a user with an unusually slow device, can scale them all at
    once: ``D4Session(t, timeouts=Timeouts.scaled(3))``.
    """

    drain_ms: int = 300
    enter_ms: int = 2500
    init_ms: int = 2500
    open_ms: int = 2500
    credit_ms: int = 1500
    credit_ack_ms: int = 1200
    reply_ms: int = 2000
    write_ms: int = 3000
    read_max: int = 1024
    tries: int = 14
    service_tries: int = 20
    enter_pause_s: float = 0.2

    @classmethod
    def scaled(cls, factor: float, **overrides) -> "Timeouts":
        """Return a copy with every timeout multiplied by ``factor``.

        ``Timeouts.scaled(0.02)`` turns the whole handshake into a few tens of
        milliseconds, which is what the hardware-free tests use.
        """
        if factor <= 0:
            raise ValueError("factor must be positive")
        base = cls()
        scaled = {
            f: max(1, int(getattr(base, f) * factor))
            for f in (
                "drain_ms",
                "enter_ms",
                "init_ms",
                "open_ms",
                "credit_ms",
                "credit_ack_ms",
                "reply_ms",
                "write_ms",
            )
        }
        scaled["enter_pause_s"] = base.enter_pause_s * factor
        scaled.update(overrides)
        return cls(**scaled)


class D4Packet(NamedTuple):
    """One decoded D4 packet: a 6-byte header plus its payload."""

    psid: int
    ssid: int
    length: int
    credit: int
    control: int
    payload: bytes

    def __str__(self) -> str:  # pragma: no cover - formatting only
        from .util import hexdump

        return "sock=%d/%d len=%d credit=%d ctrl=0x%02x payload=%s" % (
            self.psid,
            self.ssid,
            self.length,
            self.credit,
            self.control,
            hexdump(self.payload) if self.payload else "(empty)",
        )


def build_packet(
    psid: int, ssid: int, payload: bytes, credit: int = 0, control: int = 0
) -> bytes:
    """Encode one D4 packet: ``psid ssid len(2, big endian) credit ctrl payload``."""
    return struct.pack(">BBHBB", psid, ssid, 6 + len(payload), credit, control) + payload


def parse_packet(buf: bytes) -> Optional[tuple]:
    """Decode the first packet of ``buf``; return ``(packet, rest)`` or ``None``.

    ``None`` means "not enough bytes yet". A packet whose declared length is
    smaller than the 6-byte header is treated as malformed and consumed, which
    is what the historical implementation did.
    """
    if len(buf) < 6:
        return None
    psid, ssid, length, credit, control = struct.unpack(">BBHBB", buf[:6])
    if length < 6:
        return D4Packet(psid, ssid, length, credit, control, b""), buf[6:]
    if len(buf) < length:
        return None
    return D4Packet(psid, ssid, length, credit, control, buf[6:length]), buf[length:]


class D4Session:
    """A D4 conversation over a transport: connect, then send EPSON-CTRL frames."""

    def __init__(
        self,
        transport: Transport,
        timeouts: Optional[Timeouts] = None,
        trace: Optional[Callable[[str, object], None]] = None,
        auto_open: bool = True,
    ) -> None:
        self.transport = transport
        self.timeouts = timeouts or Timeouts()
        self.trace = trace
        self._buf = b""
        self.rev = INITIAL_REVISION
        self.connected = False
        if auto_open and not transport.opened:
            transport.open()

    # -- plumbing ----------------------------------------------------------
    def _trace(self, direction: str, event) -> None:
        if self.trace is not None:
            try:
                self.trace(direction, event)
            except Exception:  # a tracing callback must never break a session
                pass

    def _fill(self, timeout_ms: int) -> bool:
        chunk = self.transport.read(self.timeouts.read_max, timeout_ms)
        if chunk:
            self._trace("<raw", chunk)
            self._buf += chunk
            return True
        return False

    def drain(self, ms: Optional[int] = None) -> None:
        """Throw away anything the printer sent before we started talking."""
        ms = self.timeouts.drain_ms if ms is None else ms
        while self.transport.read(self.timeouts.read_max, ms):
            pass
        self._buf = b""

    def send(self, psid: int, ssid: int, payload: bytes, credit: int = 0,
             control: int = 0) -> bytes:
        packet = build_packet(psid, ssid, payload, credit, control)
        self._trace(">", packet)
        self.transport.write(packet, self.timeouts.write_ms)
        return packet

    def recv(self, timeout_ms: Optional[int] = None) -> Optional[D4Packet]:
        """Read one packet, packet-aligned, or ``None`` on timeout."""
        timeout_ms = self.timeouts.reply_ms if timeout_ms is None else timeout_ms
        while len(self._buf) < 6:
            if not self._fill(timeout_ms):
                return None
        decoded = parse_packet(self._buf)
        while decoded is None:  # header says "more payload"; get it
            if not self._fill(timeout_ms):
                # Truncated packet: drop the header so the stream can resync.
                self._buf = self._buf[6:]
                return None
            decoded = parse_packet(self._buf)
        packet, self._buf = decoded
        self._trace("<", packet)
        return packet

    # -- handshake ---------------------------------------------------------
    def connect(self) -> int:
        """Run the full handshake. Returns the negotiated revision.

        Raises :class:`~epson_usb.errors.D4Error` when the printer does not
        answer D4 at all, and :class:`~epson_usb.errors.TransportError` when
        the underlying pipe fails.
        """
        self.drain()
        self.transport.write(D4_ENTER_SEQUENCE, self.timeouts.write_ms)
        self._trace(">", D4_ENTER_SEQUENCE)
        if self.timeouts.enter_pause_s:
            time.sleep(self.timeouts.enter_pause_s)
        enter_reply = self.recv(self.timeouts.enter_ms)
        self._trace("enter", enter_reply)

        rev, ok = INITIAL_REVISION, False
        for _ in range(3):
            self.send(0, 0, bytes([0x00, rev]), credit=1)
            reply = self.recv(self.timeouts.init_ms)
            payload = reply.payload if reply else b""
            self._trace("init", (rev, payload))
            if len(payload) >= 3 and payload[0] == 0x80:
                if payload[1] == 0x00:
                    ok = True
                    break
                if payload[2] and payload[2] != rev:
                    # The printer told us which revision it speaks: retry.
                    rev = payload[2]
                    continue
            break
        if not ok:
            raise D4Error(
                "D4 Init failed (the printer did not answer D4). Tried revision "
                "0x%02x." % rev
            )
        self.rev = rev

        self._open_channel()
        self.connected = True
        return rev

    def _open_channel(self) -> None:
        if self.rev == REVISION_0X10:
            # Revision 0x10 adds an initCredit field (8 fields, not 7).
            payload = struct.pack(
                ">BBBHHHH", 0x01, 0x02, EPSON_CTRL_SOCKET, 0x0100, 0x0100, 0x0000, 0x0000
            )
        else:
            payload = struct.pack(
                ">BBBHHH", 0x01, 0x02, EPSON_CTRL_SOCKET, 0x0100, 0x0100, 0x0000
            )
        self.send(0, 0, payload, credit=1)
        reply = self.recv(self.timeouts.open_ms)
        payload = reply.payload if reply else b""
        self._trace("open", payload)
        if not (len(payload) >= 2 and payload[0] == 0x81 and payload[1] == 0x00):
            raise D4Error("D4 OpenChannel failed on socket %d: %r"
                          % (EPSON_CTRL_SOCKET, payload))

    def _credit_request(self) -> None:
        """Take send credit for EPSON-CTRL FROM the printer."""
        if self.rev == REVISION_0X10:
            payload = struct.pack(">BBBHH", 0x04, 0x02, EPSON_CTRL_SOCKET, 0x0080, 0xFFFF)
        else:
            payload = struct.pack(">BBBH", 0x04, 0x02, EPSON_CTRL_SOCKET, 0x0008)
        self.send(0, 0, payload, credit=1)
        for _ in range(4):
            reply = self.recv(self.timeouts.credit_ms)
            self._trace("creditreq", reply)
            if reply is None:
                break
            if reply.payload and reply.payload[0] == 0x84:
                break

    # -- commands ----------------------------------------------------------
    def request(self, frame: bytes, tries: Optional[int] = None) -> Optional[bytes]:
        """Send one EPSON-CTRL frame on the control channel and return the reply.

        ``frame`` is a complete EPSON-CTRL message (two-letter name + little
        endian length + payload), exactly as
        :func:`epson_usb.epson_ctrl.packet_command` builds it.

        Returns ``None`` when no data reply arrived; the caller decides whether
        that is an error (the historical code treated it as one everywhere).
        """
        tries = self.timeouts.tries if tries is None else tries
        self._credit_request()
        # Grant the printer reply credit, otherwise it stays quiet.
        self.send(0, 0, struct.pack(">BBBH", 0x03, 0x02, EPSON_CTRL_SOCKET, 0x0008),
                  credit=1)
        self.recv(self.timeouts.credit_ack_ms)  # CreditReply, ignored
        self.send(EPSON_CTRL_SOCKET, EPSON_CTRL_SOCKET, frame, credit=8)
        for _ in range(tries):
            packet = self.recv(self.timeouts.reply_ms)
            if packet is None:
                continue
            if packet.psid == EPSON_CTRL_SOCKET and packet.payload:
                return packet.payload
        return None

    def request_or_raise(self, frame: bytes, tries: Optional[int] = None) -> bytes:
        reply = self.request(frame, tries=tries)
        if reply is None:
            raise NoReplyError("no reply to EPSON-CTRL command %r" % (frame[:2],))
        return reply

    def close(self) -> None:
        try:
            self.transport.close()
        except Exception:
            pass
        self.connected = False

    def __enter__(self) -> "D4Session":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


class EpsonCtrlSession(D4Session):
    """A connected session with EPSON-CTRL helpers that speak *plain numbers*.

    This is the surface the historical standalone tool used::

        session.read_eeprom(0x30)   ->  26            (or None)
        session.write_eeprom(0x30, 0) ->  True/False
        session.service_rw("SERIAL")  ->  raw reply   (or None)

    It is intentionally the *low level* API: it returns the value of one cell,
    not a formatted string. The higher level, upstream-compatible API lives in
    :class:`epson_usb.printer.EpsonUsbPrinter`.

    The EEPROM access keys are **parameters**, not knowledge held here: they
    differ per printer family, and a library that hard-codes them has to be
    re-released whenever a new family appears. Callers take them from whatever
    database they keep (a host program has one already; see
    ``epson_print_conf``'s ``read_key`` for the model in use).
    """

    def __init__(
        self,
        transport: Transport,
        read_key: Optional[Sequence[int]] = None,
        write_key: Optional[bytes] = None,
        **kwargs,
    ) -> None:
        super().__init__(transport, **kwargs)
        self.read_key = tuple(read_key) if read_key else None
        self.write_key = bytes(write_key) if write_key else None

    def _read_key(self):
        """The read key, or a message that says exactly what is missing."""
        if self.read_key is None:
            raise EepromError(
                "this session has no EEPROM read key: it was created without "
                "read_key. The key is per-model data and belongs to the caller "
                "(see epson_print_conf's read_key for the model in use)."
            )
        return self.read_key

    def _write_key(self):
        """The write key, or a message that says exactly what is missing."""
        if self.write_key is None:
            raise EepromError(
                "this session has no EEPROM write key: it was created without "
                "write_key. The key is per-model data and belongs to the caller "
                "(see epson_print_conf's write_key for the model in use)."
            )
        return self.write_key

    # -- EEPROM ------------------------------------------------------------
    def read_eeprom(self, addr: int) -> Optional[int]:
        """Read one EEPROM cell. ``None`` means "no usable answer"."""
        from .epson_ctrl import eeprom_read_frame, parse_eeprom_reply

        reply = self.request(eeprom_read_frame(self._read_key(), addr))
        if not reply:
            return None
        parsed = parse_eeprom_reply(reply)
        if parsed is None:
            return None
        got_addr, value = parsed
        if got_addr != addr:
            # The printer answered about a different address: unusable.
            return None
        return value

    def write_eeprom(self, addr: int, value: int) -> bool:
        """Write one EEPROM cell. True only when the printer confirmed ``:OK;``."""
        from .epson_ctrl import eeprom_write_frame, write_confirmed

        reply = self.request(
            eeprom_write_frame(self._read_key(), self._write_key(), addr, value)
        )
        return write_confirmed(reply)

    # -- service -----------------------------------------------------------
    def service_rw(self, serial: str, mode: Optional[int] = None) -> Optional[bytes]:
        """Run the Epson ``rw`` ("reset waste") service command.

        ``mode=None`` sends the 21-byte payload the historical tool used (one
        zero byte + the SHA-1 of the serial). ``mode=1`` reproduces
        ``epson_print_conf``, which sends a 2-byte little endian mode instead
        (22 bytes). Both are offered because both have been reported to work;
        see the README for which is which.
        """
        from .epson_ctrl import rw_frame

        return self.request(
            rw_frame(serial, mode=mode), tries=self.timeouts.service_tries
        )

    def command(self, name: bytes, payload: bytes = b"",
                tries: Optional[int] = None) -> Optional[bytes]:
        """Send any EPSON-CTRL packet command (``st``, ``di``, ``vi``, ...)."""
        from .epson_ctrl import packet_command

        return self.request(packet_command(name, payload), tries=tries)

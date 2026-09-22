r"""The printer object: EEPROM access, service commands, status, backups.

**No model data lives here.** Read and write keys, address ranges and cell
tables are per-model facts, and per-model facts belong to the caller — its own
model database, or the configuration of the host program (``epson_print_conf``
passes the parameters of the selected printer). This module only knows *how* to
talk to a printer over USB: the D4 session, the EPSON-CTRL frames, the reply
grammar, the status block, the backup format.

That is why every method that needs a key or an address range takes it as a
parameter, and why there is no ``model=`` argument: a library that carries a
printer database is a library that has to be updated every time a new printer
appears, and that disagrees with the host about the same machine.

Two audiences use this object:

* **Standalone callers** pass the keys and the ranges they know::

      from epson_usb import EpsonUsbPrinter

      with EpsonUsbPrinter(read_key=(0x4A, 0x36),
                           write_key=b"Nbsjcbzb") as printer:
          print(printer.read_eeprom(0x30))       # '3B'  (2 hex digits)
          print(printer.read_cell(0x30))         # 59    (int)
          print(printer.read_serial(range(0x644, 0x64E)))
          printer.write_cells([(0x30, 0), (0x31, 0)])   # WRITES

* **Host programs** (see :mod:`epson_usb.compat`) do not need keys at all:
  they send EPSON-CTRL messages as OIDs, and their own configuration already
  built them, so the library only unwraps and transports them.

Safety model, unchanged from the tool this grew out of:

* nothing here writes unless a write method is called;
* ``dry_run=True`` turns every write into a read and reports what it would do;
* every write is read back, and a write that is not confirmed by ``:OK;`` is
  reported as failure — never as success.
"""

from __future__ import annotations

import datetime
import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import backup as backup_module
from .backends import open_transport
from .backends.base import Transport
from .d4 import Timeouts, EpsonCtrlSession
from .epson_ctrl import (
    cartridges_frame,
    device_id_frame,
    eeprom_read_frame,
    eeprom_read_payload,
    eeprom_write_frame,
    eeprom_write_payload,
    parse_snmp_oid,
    snmp_oid,
    status_frame,
    version_frame,
    write_confirmed,
)
from .errors import EepromError, ProtocolError
from .status import full_status

__all__ = ["EpsonUsbPrinter", "RestoreReport", "read_oid_values_from_transport"]

log = logging.getLogger(__name__)

_EEPROM_REPLY_RE = re.compile(rb"EE:([0-9A-Fa-f]{6})")


class CellReader:
    """Adapts the printer to the ``read_eeprom(addr) -> int | None`` contract.

    Callers that read *cells* (a counter spread over consecutive addresses, a
    serial number) want numbers, while :meth:`EpsonUsbPrinter.read_eeprom`
    returns the two-hex-digit string the host programs expect. This adapts one
    to the other, so such a caller can be written once::

        reader = printer.cell_reader()
        values = [reader.read_eeprom(a) for a in (0x30, 0x31)]
    """

    def __init__(self, printer: "EpsonUsbPrinter") -> None:
        self._printer = printer

    def read_eeprom(self, addr: int) -> Optional[int]:
        return self._printer.read_cell(addr)


@dataclass
class RestoreReport:
    """What :meth:`EpsonUsbPrinter.restore_backup` managed to do."""

    written: int = 0
    failed: List[int] = field(default_factory=list)
    missing: List[int] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed and not self.missing

    def __str__(self) -> str:
        return "%d written, %d failed, %d missing from the backup" % (
            self.written,
            len(self.failed),
            len(self.missing),
        )


class EpsonUsbPrinter:
    """An Epson printer reached over USB, speaking D4 + EPSON-CTRL."""

    def __init__(
        self,
        read_key: Optional[Sequence[int]] = None,
        write_key: Optional[bytes] = None,
        device=None,
        backend: Optional[str] = None,
        instance_id: Optional[str] = None,
        transport: Optional[Transport] = None,
        timeouts: Optional[Timeouts] = None,
        dry_run: bool = False,
        auto_open: bool = True,
        lazy_open: bool = False,
        trace: Optional[Callable[[str, object], None]] = None,
        logger: Optional[logging.Logger] = None,
        **transport_kwargs,
    ) -> None:
        #: EEPROM access keys, supplied by the caller. ``None`` is a valid
        #: state: a host that answers OIDs (epson_print_conf) never needs them
        #: here, because it built the frame itself.
        self.read_key = tuple(read_key) if read_key else None
        self.write_key = bytes(write_key) if write_key else None
        self.dry_run = dry_run
        self.log = logger or log
        self._transport_kwargs = transport_kwargs
        self._transport_arg = transport
        self._device = device
        self._backend = backend
        self._instance_id = instance_id
        self._timeouts = timeouts
        self._trace = trace
        self._lazy_open = lazy_open
        self.session: Optional[EpsonCtrlSession] = None
        self.revision: Optional[int] = None
        if auto_open:
            self.open()

    # ------------------------------------------------------------------ #
    #  Lifecycle
    # ------------------------------------------------------------------ #
    def open(self) -> "EpsonUsbPrinter":
        """Open the device and run the D4 handshake. Idempotent."""
        if self.session is not None and self.session.connected:
            return self
        kwargs = dict(self._transport_kwargs)
        if self._transport_arg is not None:
            transport = (
                self._transport_arg
                if isinstance(self._transport_arg, Transport)
                else open_transport(self._transport_arg, backend=self._backend, **kwargs)
            )
        else:
            transport = open_transport(
                self._device,
                backend=self._backend,
                instance_id=self._instance_id,
                **kwargs,
            )
        self.session = EpsonCtrlSession(
            transport,
            read_key=self.read_key,
            write_key=self.write_key,
            timeouts=self._timeouts,
            trace=self._trace,
        )
        try:
            self.revision = self.session.connect()
        except Exception:
            self.session.close()
            self.session = None
            raise
        self.log.debug("connected: %s (D4 revision 0x%02x)",
                       transport.describe(), self.revision)
        return self

    def close(self) -> None:
        if self.session is not None:
            self.session.close()
            self.session = None

    def __enter__(self) -> "EpsonUsbPrinter":
        return self.open()

    def __exit__(self, *exc_info) -> None:
        self.close()

    @property
    def connected(self) -> bool:
        return self.session is not None and self.session.connected

    @property
    def transport(self) -> Optional[Transport]:
        return self.session.transport if self.session else None

    @property
    def device_info(self):
        transport = self.transport
        return transport.info if transport else None

    def describe(self) -> str:
        transport = self.transport
        if transport is None:
            # A normal state with lazy opening: the object exists, the device
            # has not been touched yet.
            return "not connected"
        return "%s (D4 revision 0x%02x)" % (transport.describe(), self.revision or 0)

    def cell_reader(self) -> CellReader:
        """A ``read_eeprom(addr) -> int | None`` view of this printer."""
        return CellReader(self)

    def _require_session(self) -> EpsonCtrlSession:
        if self.session is None or not self.session.connected:
            if self._lazy_open:
                # Open on first use. This is what a host program needs: it
                # builds printer objects freely (to list models, to read a
                # configuration) and only expects a device to be touched when a
                # command is actually sent.
                self.open()
            else:
                raise ProtocolError("the printer is not connected: call open() first")
        return self.session

    def _require_keys(self) -> Tuple[tuple, bytes]:
        if self.read_key is None:
            raise EepromError(
                "no EEPROM access key: this printer object was created without "
                "read_key/write_key. Access keys are per-model data: supply them "
                "from your model database or configuration."
            )
        return self.read_key, self.write_key

    # ------------------------------------------------------------------ #
    #  Raw EPSON-CTRL
    # ------------------------------------------------------------------ #
    def request(self, frame: bytes, tries: Optional[int] = None) -> Optional[bytes]:
        """Send one EPSON-CTRL frame; return the reply payload (or ``None``)."""
        return self._require_session().request(frame, tries=tries)

    def command(self, name: bytes, payload: bytes = b"",
                tries: Optional[int] = None) -> Optional[bytes]:
        """Send a named EPSON-CTRL command (``st``, ``di``, ``vi``, ...)."""
        return self._require_session().command(name, payload, tries=tries)

    # ------------------------------------------------------------------ #
    #  EEPROM -- the OID surface a host program uses
    # ------------------------------------------------------------------ #
    def eeprom_oid_read_address(self, oid: int, msb: int = 0,
                                label: str = "unknown method") -> str:
        """The SNMP OID a host would use to *read* ``oid``.

        Producing the OID (instead of hiding it) is what lets the same program
        run over SNMP and over USB:
        :func:`~epson_usb.epson_ctrl.parse_snmp_oid` turns it back into exactly
        the bytes this class sends.
        """
        read_key, _ = self._require_keys()
        addr = _split_address(oid, msb)
        if addr is None:
            raise EepromError("invalid EEPROM address %r" % (oid,))
        return snmp_oid("||", eeprom_read_payload(read_key, addr))

    def eeprom_oid_write_address(self, oid: int, value, msb: int = 0,
                                 label: str = "unknown method") -> Optional[str]:
        """The SNMP OID to *write* ``value`` to ``oid``.

        In dry-run mode it returns the **read** OID, exactly like
        ``epson_print_conf``: a dry run must not be able to write even if some
        caller ignores the flag.
        """
        read_key, write_key = self._require_keys()
        if write_key is None:
            raise EepromError("no write key: cannot build a write frame")
        addr = _split_address(oid, msb)
        if addr is None:
            raise EepromError("invalid EEPROM address %r" % (oid,))
        if self.dry_run:
            self.log.warning("WRITE_DRY_RUN: address 0x%04X <- %s", addr, value)
            return snmp_oid("||", eeprom_read_payload(read_key, addr))
        return snmp_oid(
            "||", eeprom_write_payload(read_key, write_key, addr, int(value))
        )

    def fetch_oid_values(self, oid, label: str = "unknown"):
        """Answer an OID by talking to the printer over USB.

        Return shape mirrors ``epson_print_conf.fetch_oid_values``: a list of
        ``(type_name, value)``, where ``type_name`` is ``"OctetString"`` for a
        real answer and the pair is ``(None, False)`` when nothing usable came
        back. Lists (and lists of lists, i.e. grouped PDUs) are accepted and
        answered in order; over a serial link the "parallel PDU" concept has no
        meaning, so groups are sent one after another, preserving order.

        Plain MIB OIDs -- anything that is not an EPSON-CTRL message -- cannot
        travel over USB: they are answered ``(None, False)`` and logged.
        """
        if isinstance(oid, (list, tuple)):
            out = []
            for element in oid:
                if isinstance(element, (list, tuple)):
                    out.extend(self.fetch_oid_values(list(element), label=label))
                else:
                    out.extend(self.fetch_oid_values(element, label=label))
            return out

        try:
            name, payload = parse_snmp_oid(oid)
        except ValueError:
            self.log.info(
                "OID %s (%s) is not an EPSON-CTRL message: it needs SNMP, not USB",
                oid, label,
            )
            return [(None, False)]
        frame = name.encode("ascii") + len(payload).to_bytes(2, "little") + payload
        reply = self.request(frame)
        if reply is None:
            self.log.info("no reply to %s (%s)", name, label)
            return [(None, False)]
        return [("OctetString", reply)]

    def invalid_response(self, response) -> bool:
        """Is this reply unusable? Same contract as ``epson_print_conf``.

        The rule is ``response[0] == 0`` and ``response[-1] == 0x0C`` (the
        ``@BDC`` block terminator), which is what a real SNMP tunnel returns. A
        D4 reply may legitimately carry a different leading byte, so a reply
        that ends with the terminator and contains a well-formed ``name:...;``
        element is accepted too. Being tolerant here can only turn "unusable"
        into "usable"; it never accepts a truncated frame, because the
        terminator is still required.
        """
        if response is False or response is None:
            return True
        if isinstance(response, str):
            response = response.encode("latin-1", "replace")
        if not isinstance(response, (bytes, bytearray)):
            return True
        if len(response) < 2:
            return True
        if response[0] == 0 and response[-1] == 0x0C:
            return False
        if response[-1] == 0x0C and re.search(rb"[A-Za-z|]{2}:[^:]*;", response[1:]):
            return False
        return True

    def _process_response(self, response, addr: int, label: str) -> Optional[str]:
        if not response or self.invalid_response(response):
            self.log.error("invalid response for address 0x%04X (%s): %r",
                           addr, label, response)
            return None
        match = _EEPROM_REPLY_RE.search(response)
        if not match:
            self.log.info("no EEPROM payload for address 0x%04X (%s)", addr, label)
            return None
        text = match.group(1).decode("ascii")
        if int(text[0:4], 16) != addr:
            self.log.critical(
                "EEPROM address mismatch: expected 0x%04X, printer said %s (%s)",
                addr, text[0:4], label,
            )
            return None
        return text[4:6].upper()

    # ------------------------------------------------------------------ #
    #  EEPROM -- reading and writing
    # ------------------------------------------------------------------ #
    def read_eeprom(self, oid, label: str = "unknown method"):
        """Read one cell (or a list of cells).

        Returns the value as **two upper-case hex digits** (``"A3"``), or
        ``None`` -- byte-identical in type and format to
        ``epson_print_conf.read_eeprom``, because callers do
        ``int(value, 16)`` on the result.
        """
        if isinstance(oid, (list, tuple)):
            return [self.read_eeprom(element, label=label) for element in oid]
        read_key, _ = self._require_keys()
        addr = _split_address(oid, 0)
        if addr is None:
            raise EepromError("invalid EEPROM address %r" % (oid,))
        reply = self.request(eeprom_read_frame(read_key, addr))
        return self._process_response(reply, addr, label)

    def read_eeprom_many(self, oids, label: str = "unknown method") -> List:
        """Read many cells; ``[None]`` when any of them failed.

        The all-or-nothing shape is upstream's, and it is a deliberate choice:
        a partially read EEPROM range is almost always a sign of a link
        problem, and silently returning holes would let a bad backup look good.
        """
        if isinstance(oids, range):
            oids = list(oids)
        results = self.read_eeprom(list(oids), label=label)
        if not isinstance(results, list):
            results = [results]
        if any(item is None for item in results):
            return [None]
        return results

    def write_eeprom(self, oid: int, value: int, label: str = "unknown method") -> bool:
        """Write one cell. True only when the printer answered ``:OK;``.

        The previous value is read first and logged (upstream does the same):
        it validates the read path before a write, and it is the only record of
        what was there if something goes wrong.
        """
        if int(value) < 0 or int(value) > 0xFF:
            raise ValueError("EEPROM values are one byte: %r" % (value,))
        read_key, write_key = self._require_keys()
        if write_key is None:
            raise EepromError("no write key: cannot write")
        addr = _split_address(oid, 0)
        if addr is None:
            raise EepromError("invalid EEPROM address %r" % (oid,))
        if not self.dry_run:
            self.log.debug("previous value of 0x%04X (%s): %s",
                           addr, label, self.read_eeprom(addr, label=label))
        if self.dry_run:
            self.log.warning("WRITE_DRY_RUN: 0x%04X <- %s (%s)", addr, value, label)
            # A dry run still puts the *read* form of the command on the wire
            # (upstream's dry run does the same), so the link is exercised while
            # nothing can be written: it proves the address is reachable, not
            # merely that a flag was set.
            self.request(eeprom_read_frame(read_key, addr))
            return True
        reply = self.request(eeprom_write_frame(read_key, write_key, addr, int(value)))
        if not write_confirmed(reply):
            self.log.info("write to 0x%04X did not return :OK; (%r)", addr, reply)
            return False
        return True

    def write_cells(self, cells, verify: bool = True, label: str = "write_cells") -> bool:
        """Write a set of ``(address, value)`` pairs and verify every write.

        The *set* is the caller's: which cells make a "reset" is model
        knowledge (one family resets cells to zero, another to ``0x5E``), and
        this library does not carry it.
        """
        ok = True
        for addr, value in cells:
            if not self.write_eeprom(addr, value, label=label):
                self.log.error("write failed at 0x%04X", addr)
                ok = False
                continue
            if verify and not self.dry_run:
                after = self.read_cell(addr)
                if after != value:
                    self.log.error("0x%04X read back as %r after writing %d",
                                   addr, after, value)
                    ok = False
        return ok

    def read_cell(self, addr: int) -> Optional[int]:
        """Read one cell as an **int** (``None`` when unreadable)."""
        text = self.read_eeprom(addr, label="read_cell")
        return None if text is None else int(text, 16)

    def dump_eeprom(self, start: int = 0, end: int = 0xFF,
                    progress: Optional[Callable[[int, int], None]] = None
                    ) -> Dict[int, Optional[int]]:
        """Read an inclusive address range into ``{address: value}``.

        Upstream sends this as one parallel SNMP batch, which a serial USB link
        cannot do: each cell is one exchange. ``progress`` is called with
        ``(done, total)`` so a caller can show a long dump.
        """
        addrs = list(range(start, end + 1))
        out: Dict[int, Optional[int]] = {}
        for index, addr in enumerate(addrs, 1):
            out[addr] = self.read_cell(addr)
            if progress is not None:
                progress(index, len(addrs))
        return out

    def dump_bank0(self, progress: Optional[Callable[[int, int], None]] = None
                   ) -> Dict[int, Optional[int]]:
        """Read the whole of bank 0 (0x00-0xFF), the backup unit of this tool."""
        return self.dump_eeprom(0x00, 0xFF, progress=progress)

    # ------------------------------------------------------------------ #
    #  Serial number and device information
    # ------------------------------------------------------------------ #
    def read_serial(self, serial_range=None) -> str:
        """Serial number from the EEPROM, printable characters only.

        ``serial_range`` is required (or supplied as ``read_serial``'s
        argument): where a model keeps its serial is model knowledge. The
        host's configuration passes it; see ``epson_print_conf``'s
        ``parm['serial_number']``.
        """
        if serial_range is None:
            raise EepromError(
                "read_serial() needs the serial number's address range: it is "
                "model data and comes from the caller"
            )
        chars = []
        for addr in serial_range:
            value = self.read_cell(addr)
            if value is not None and 32 <= value < 127:
                chars.append(chr(value))
        return "".join(chars).strip()

    def get_serial_number(self, serial_range=None) -> Optional[str]:
        """Serial number in ``epson_print_conf``'s format.

        That format is "every address becomes a character, and a cell that
        cannot be read becomes ``?``" -- not a tidied string. Use
        :meth:`read_serial` for the tidied one.
        """
        if serial_range is None:
            raise EepromError("get_serial_number() needs the serial range")
        text = []
        for addr in serial_range:
            value = self.read_eeprom(addr, label="serial_number")
            text.append(chr(int(value or "0x3f", 16)))
        return "".join(text)

    def get_firmware_version(self) -> Optional[str]:
        """``'<code> DD Mon YYYY'``, decoded exactly as upstream decodes it."""
        reply = self.request(version_frame())
        if not reply:
            return None
        try:
            match = re.search(r"vi:00:(.{6})", reply.decode("latin-1"))
        except Exception:
            return None
        if not match:
            return None
        firmware = match.group(1)
        try:
            year = ord(firmware[4:5]) + 1945
            month = int(firmware[5:], 16)
            day = int(firmware[2:4])
            return firmware + " " + datetime.datetime(year, month, day).strftime(
                "%d %b %Y"
            )
        except Exception:
            return firmware

    def get_device_identification(self) -> Dict[str, List[str]]:
        """The IEEE 1284 device id string, split into fields."""
        reply = self.request(device_id_frame())
        if not reply:
            return {}
        # Drop the 10-byte @BDC header (upstream does the same) and any frame
        # terminator, so the last field is not polluted by it.
        text = reply.decode("latin-1", "replace")[10:].replace("\x0c", "")
        key_map = {
            "MFG": "Manufacturer",
            "CMD": "Commands",
            "MDL": "Model",
            "CLS": "Class",
            "DES": "Description",
        }
        out: Dict[str, List[str]] = {}
        for field_ in text.split(";"):
            if not field_:
                continue
            key, _, values = field_.partition(":")
            out[key_map.get(key, key)] = [v for v in values.split(",") if v]
        return out

    def get_cartridges(self) -> List[str]:
        """Cartridge type strings reported by the ``ia`` command."""
        reply = self.request(cartridges_frame())
        if not reply:
            return []
        match = re.search(rb"IA:00;(.*);", reply, re.S)
        if not match:
            return []
        return [item.strip().decode("latin-1") for item in match.group(1).split(b",")]

    def get_printer_status(self):
        """Decode the ``@BDC ST2`` status block.

        Uses ``epson_print_conf.status_parser`` when that package is
        installed -- the block is the same one SNMP delivers, so the full decode
        is available rather than a second implementation that could drift.
        Otherwise :func:`epson_usb.status.parse_st2` is used, which extracts
        only a documented subset.
        """
        reply = self.request(status_frame())
        if not reply:
            return None
        return self.status_parser(reply)

    @staticmethod
    def status_parser(data):
        """Decode a status block (delegates upstream when possible)."""
        return full_status(data)

    # ------------------------------------------------------------------ #
    #  Service commands
    # ------------------------------------------------------------------ #
    def service_rw(self, serial: str, mode: Optional[int] = None) -> Optional[bytes]:
        """Send the ``rw`` command for ``serial``; return the raw reply.

        ``rw`` is a *temporary* waste reset: per reports on ``epson_print_conf``
        issue #35 it does not survive a power cycle. It is the fallback for
        firmware that locks EEPROM access, where it still works because it needs
        only the serial number. Which serial string to hash is the caller's
        decision (the EEPROM serial and the USB descriptor serial do not agree).
        """
        return self._require_session().service_rw(serial, mode=mode)

    # ------------------------------------------------------------------ #
    #  Backups
    # ------------------------------------------------------------------ #
    def save_backup(self, directory: Optional[str] = None,
                    progress: Optional[Callable[[int, int], None]] = None) -> str:
        """Dump bank 0 and write it to a JSON file; return the absolute path."""
        cells = self.dump_bank0(progress=progress)
        path = backup_module.save_backup(cells, directory=directory)
        self.log.info("backup written: %s", path)
        return path

    def restore_backup(self, path: str, addresses: Sequence[int],
                       safety_backup: bool = True,
                       directory: Optional[str] = None) -> RestoreReport:
        """Write back the ``addresses`` listed in a backup file.

        ``addresses`` is the caller's set -- every cell any of *its* write paths
        can touch, so that a full reset is undoable -- because which cells those
        are is model knowledge. A safety backup of the current state is taken
        first unless told otherwise: restoring from a stale file would otherwise
        cost the current values silently.
        """
        resolved = backup_module.resolve_backup_path(path, (directory,))
        cells = backup_module.cells_from_backup(resolved)
        if safety_backup:
            self.save_backup(directory=directory)
        report = RestoreReport()
        for addr in addresses:
            value = cells.get(addr)
            if value is None:
                report.missing.append(addr)
                continue
            if self.write_eeprom(addr, value, label="restore_backup"):
                report.written += 1
            else:
                report.failed.append(addr)
        return report

    def __repr__(self) -> str:  # pragma: no cover - formatting only
        return "EpsonUsbPrinter(%s)" % self.describe()


# --------------------------------------------------------------------------- #
#  Module-level helpers
# --------------------------------------------------------------------------- #
def read_oid_values_from_transport(transport: Transport, oid: str,
                                   timeouts: Optional[Timeouts] = None
                                   ) -> List[Tuple[Optional[str], object]]:
    """One-shot helper: open a session, answer one OID, close.

    Handy for a one-line check, and the only place where a session is created
    without a printer object. MIB OIDs (not EPSON-CTRL) answer ``(None, False)``,
    as over USB they cannot exist.
    """
    session = EpsonCtrlSession(transport, timeouts=timeouts)
    try:
        session.connect()
        try:
            name, payload = parse_snmp_oid(oid)
        except ValueError:
            return [(None, False)]
        frame = name.encode("ascii") + len(payload).to_bytes(2, "little") + payload
        reply = session.request(frame)
        if reply is None:
            return [(None, False)]
        return [("OctetString", reply)]
    finally:
        session.close()


def _split_address(oid, msb: int) -> Optional[int]:
    """Resolve ``oid``/``msb`` into one 16-bit address, as upstream does."""
    try:
        value = int(oid)
    except (TypeError, ValueError):
        return None
    if value > 0xFF and msb == 0:
        msb = value // 256
        value = value % 256
    if msb > 0xFF or value > 0xFF or value < 0 or msb < 0:
        return None
    return (msb << 8) | value

"""USB access to Epson printers: D4 session, EPSON-CTRL, EEPROM, status.

This package is the *transport* half of a tool that talks to Epson
printers over USB. It knows the protocol and the framing, and nothing about
which printer family is on the other end of the cable: read/write keys,
address ranges and counter divisors are supplied by the caller, because they
are per-model facts and a library that carries them is a library that goes
stale and disagrees with its host.

What it does provide, in one import:

* **transports** -- USBPRINT on Windows, libusb (own ``ctypes`` binding, no
  dependency), PyUSB when installed, a raw ``/dev/usb/lp*`` device, and an
  in-memory fake printer that is a full protocol implementation
  (:class:`~epson_usb.backends.mock.MockPrinter`), so every layer above the
  wire can be tested without hardware;
* **protocol** -- the D4 session (:class:`~epson_usb.d4.D4Session`), the
  EPSON-CTRL frame grammar and the SNMP-OID bridge
  (:func:`~epson_usb.epson_ctrl.parse_snmp_oid`), so the same program can run
  over SNMP and over USB;
* **printer** -- :class:`~epson_usb.printer.EpsonUsbPrinter`, EEPROM read and
  write, backups, status, serial numbers, the ``rw`` service command;
* **host integration** -- :func:`~epson_usb.compat.usb_printer`, which makes an
  existing ``epson_print_conf`` install work over USB through its own
  single entry point (``fetch_oid_values``).

The data-driven half -- which key belongs to which model, what a full counter
is, which cells a reset touches -- lives with the client. In this repository
that is ``epson_l3250.py`` (the L3250/ET-28xx tables, including the conversion
into ``epson_print_conf``'s parameter format) and ``epson_l3250_cli.py`` (the
command line interface built on them).
"""

from __future__ import annotations

from .__version__ import __version__
from .backends import (
    available_backends,
    backend_names,
    describe_environment,
    find_devices,
    open_mock,
    open_transport,
)
from .compat import (
    UsbEpsonPrinterMixin,
    load_epson_print_conf,
    patch_epson_print_conf,
    upstream_knows_model,
    usb_printer,
)
from .d4 import D4Session, EpsonCtrlSession, Timeouts
from .eeprom import decode_counter, percentage
from .epson_ctrl import (
    eeprom_read_frame,
    eeprom_read_payload,
    eeprom_write_frame,
    eeprom_write_payload,
    is_epson_ctrl_oid,
    packet_command,
    parse_snmp_oid,
    rw_frame,
    snmp_oid,
)
from .errors import (
    AccessDeniedError,
    BackendNotAvailableError,
    DeviceBusyError,
    DeviceNotFoundError,
    D4Error,
    EepromError,
    EpsonUsbError,
    NoReplyError,
    ProtocolError,
    TransportError,
    WriteNotConfirmedError,
)
from .printer import CellReader, EpsonUsbPrinter, RestoreReport

__all__ = [
    "__version__",
    # high level
    "EpsonUsbPrinter",
    "CellReader",
    "RestoreReport",
    "open_printer",
    # transports
    "open_transport",
    "open_mock",
    "find_devices",
    "backend_names",
    "available_backends",
    "describe_environment",
    "D4Session",
    "EpsonCtrlSession",
    "Timeouts",
    # protocol
    "packet_command",
    "snmp_oid",
    "parse_snmp_oid",
    "is_epson_ctrl_oid",
    "eeprom_read_payload",
    "eeprom_write_payload",
    "eeprom_read_frame",
    "eeprom_write_frame",
    "rw_frame",
    # EEPROM value conventions (no model data: see the module docstring)
    "decode_counter",
    "percentage",
    # upstream integration
    "usb_printer",
    "patch_epson_print_conf",
    "load_epson_print_conf",
    "upstream_knows_model",
    "UsbEpsonPrinterMixin",
    # errors
    "EpsonUsbError",
    "TransportError",
    "BackendNotAvailableError",
    "DeviceNotFoundError",
    "DeviceBusyError",
    "AccessDeniedError",
    "ProtocolError",
    "NoReplyError",
    "D4Error",
    "EepromError",
    "WriteNotConfirmedError",
]


def open_printer(**kwargs) -> EpsonUsbPrinter:
    """Open a printer and return it, already connected.

    ``EpsonUsbPrinter(auto_open=True)`` does the same thing; this is the
    function form, for call sites that prefer ``with open_printer() as p:``.

    Keys are not implied: a caller that wants EEPROM access passes
    ``read_key=``/``write_key=``, or uses one of its own model tables to supply
    them, as the client modules in this repository do.
    """
    return EpsonUsbPrinter(**kwargs)

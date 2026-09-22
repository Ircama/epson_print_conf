"""The byte-pipe contract every backend implements.

A *transport* is deliberately dumb: it opens a device, moves bytes both ways
with a timeout, and closes. Everything printer-specific (IEEE 1284.4 framing,
EPSON-CTRL commands, EEPROM addresses) lives above it in
:mod:`epson_usb.d4` and :mod:`epson_usb.epson_ctrl`. That split is what lets
the same, hardware-verified protocol code run over

* the Windows ``USBPRINT`` device interface (no driver replacement),
* ``libusb`` (Linux and macOS), through ``ctypes`` or ``pyusb``,
* a POSIX character device such as ``/dev/usb/lp0``,
* an in-memory fake printer (:mod:`epson_usb.backends.mock`) for tests.

Timeout policy is part of the contract: :meth:`Transport.read` returns
``b""`` -- never ``None`` and never an exception -- when nothing arrived in
time. Callers above interpret silence themselves.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Optional

__all__ = ["DeviceInfo", "Transport"]

#: Epson's USB vendor id. Used as the default filter when discovering devices.
EPSON_VID = 0x04B8

#: USB interface class meaning "vendor specific" (Epson uses it for D4).
VENDOR_SPECIFIC_CLASS = 0xFF


@dataclass(frozen=True)
class DeviceInfo:
    """What a backend knows about a candidate device before opening it.

    ``path`` is backend-specific: a Windows device interface path, a
    ``bus:address`` pair, ``/dev/usb/lp0``, or ``"mock"``.
    """

    backend: str
    path: str
    vendor_id: int = 0
    product_id: int = 0
    serial: Optional[str] = None
    interface: Optional[int] = None
    endpoint_in: Optional[int] = None
    endpoint_out: Optional[int] = None
    description: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def vid_pid(self) -> str:
        return "%04x:%04x" % (self.vendor_id, self.product_id)

    def __str__(self) -> str:  # pragma: no cover - formatting only
        bits = [self.backend, self.path]
        if self.vendor_id or self.product_id:
            bits.append(self.vid_pid)
        if self.interface is not None:
            bits.append("if=%s" % self.interface)
        if self.serial:
            bits.append("serial=%s" % self.serial)
        return " ".join(str(b) for b in bits if b)


class Transport(abc.ABC):
    """A bidirectional byte pipe to one printer."""

    #: Short backend id, also the value of ``--backend``.
    name = "abstract"

    def __init__(self) -> None:
        self._info = DeviceInfo(backend=self.name, path="")
        self._opened = False

    # -- lifecycle ---------------------------------------------------------
    @property
    def info(self) -> DeviceInfo:
        return self._info

    @property
    def opened(self) -> bool:
        return self._opened

    @abc.abstractmethod
    def open(self) -> None:
        """Claim the device. Must be idempotent and raise a subclass of
        :class:`~epson_usb.errors.TransportError` on failure."""

    def close(self) -> None:
        """Release the device. Must never raise."""
        self._opened = False

    def __enter__(self) -> "Transport":
        self.open()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- I/O ---------------------------------------------------------------
    @abc.abstractmethod
    def write(self, data: bytes, timeout_ms: int = 3000) -> int:
        """Write ``data``, returning the number of bytes accepted."""

    @abc.abstractmethod
    def read(self, maxlen: int = 1024, timeout_ms: int = 2000) -> bytes:
        """Read up to ``maxlen`` bytes. ``b""`` means "nothing arrived"."""

    def drain(self, timeout_ms: int = 300) -> int:
        """Read and discard whatever is pending; return the byte count."""
        total = 0
        while True:
            chunk = self.read(1024, timeout_ms)
            if not chunk:
                return total
            total += len(chunk)

    def describe(self) -> str:
        return str(self.info)

    # -- helpers -----------------------------------------------------------
    @classmethod
    def available(cls) -> bool:
        """True when this backend can work at all on this machine.

        Cheap and side-effect free where possible: it may load a shared
        library, but never opens a device.
        """
        return True

    @classmethod
    def find(cls, vendor_id: Optional[int] = EPSON_VID, **kwargs) -> list:
        """Return ``list[DeviceInfo]`` of candidate devices."""
        return []

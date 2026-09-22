"""Exception hierarchy.

Every error raised by this package derives from :class:`EpsonUsbError`, so a
caller can wrap a whole exchange in one ``except``. Transport errors also
derive from :class:`OSError` because that is what the underlying operating
system calls raise; code that already catches ``OSError`` keeps working.

The names are chosen so that a caller can tell apart the three situations that
need different advice:

* :class:`DeviceNotFoundError` -- nothing on the USB tree looks like the
  printer (or the backend is not available on this machine).
* :class:`DeviceBusyError` -- the printer is there, but something else holds
  it (a print job, the vendor driver, or another copy of this program).
* :class:`ProtocolError` -- we reached the device, but the conversation did
  not make sense (wrong key, wrong revision, no answer).
"""

from __future__ import annotations

__all__ = [
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


class EpsonUsbError(Exception):
    """Base class for every error raised by :mod:`epson_usb`."""


class TransportError(EpsonUsbError, OSError):
    """The byte pipe to the printer could not be used."""


class BackendNotAvailableError(TransportError):
    """The requested backend cannot work on this machine.

    Raised, for example, when ``backend="libusb"`` is asked for but the
    ``libusb-1.0`` shared library is not installed. The message always names
    the platform-specific package that provides it.
    """


class DeviceNotFoundError(TransportError):
    """No candidate device was found (or it disappeared)."""


class DeviceBusyError(TransportError):
    """The device exists but is already claimed by someone else."""


class AccessDeniedError(TransportError):
    """Permission denied (typically a missing udev rule or driver claim)."""


class ProtocolError(EpsonUsbError):
    """The printer answered something we could not interpret."""


class NoReplyError(ProtocolError):
    """The printer did not answer within the timeout."""


class D4Error(ProtocolError):
    """The IEEE 1284.4 (D4) handshake failed."""


class EepromError(ProtocolError):
    """An EEPROM read or write did not return a usable answer."""


class WriteNotConfirmedError(EepromError):
    """A write returned neither ``:OK;`` nor an error -- state unknown.

    Kept separate from :class:`EepromError` on purpose: a write that is not
    confirmed must never be reported as a plain failure, because the printer
    may well have accepted it.
    """

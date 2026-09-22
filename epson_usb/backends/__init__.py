"""Backend registry: which byte pipes exist, and which one to use here.

Five transports are registered. Three talk to real hardware, one is a fake for
tests, and they are selected by platform so that the common case needs no
options at all:

=================  ==========================================  =====================
backend            what it uses                                available on
=================  ==========================================  =====================
``usbprint``       Windows ``USBPRINT`` device interface,      Windows
                   ``ctypes`` only -- **no driver change**
``libusb``         ``libusb-1.0`` through ``ctypes``           Linux, macOS, Windows
                   (the package's own binding, no PyUSB)
``pyusb``          PyUSB (optional extra ``[pyusb]``)          anywhere PyUSB runs
``raw``            a POSIX character device (``/dev/usb/lp0``) Linux/macOS
``mock``           the in-memory fake printer                  everywhere
=================  ==========================================  =====================

Default order is platform specific: on Windows the driver-provided interface
first (it needs nothing installed and is what was verified on hardware), then
libusb; on Linux and macOS libusb first, then a character device. ``mock`` is
never chosen automatically -- it has to be asked for by name, so a test can
never be mistaken for a printer.
"""

from __future__ import annotations

import inspect
import sys
from typing import Dict, Iterable, List, Optional, Tuple

from ..errors import BackendNotAvailableError, DeviceNotFoundError, TransportError
from .base import EPSON_VID, DeviceInfo, Transport

__all__ = [
    "BACKEND_PATHS",
    "DEFAULT_ORDER",
    "backend_names",
    "available_backends",
    "backend_class",
    "find_devices",
    "open_transport",
    "open_mock",
    "describe_environment",
]

#: Backend name -> (module, class). Imported lazily, so a broken platform
#: specific module can never stop the package from importing.
BACKEND_PATHS: Dict[str, Tuple[str, str]] = {
    "usbprint": ("epson_usb.backends.usbprint_win", "WindowsUsbPrintTransport"),
    "libusb": ("epson_usb.backends.libusb", "LibusbTransport"),
    "pyusb": ("epson_usb.backends.pyusb_backend", "PyusbTransport"),
    "raw": ("epson_usb.backends.rawdevice", "RawDeviceTransport"),
    "mock": ("epson_usb.backends.mock", "MockTransport"),
}

#: Backends tried, in order, when the caller does not choose one.
DEFAULT_ORDER: Dict[str, Tuple[str, ...]] = {
    "win32": ("usbprint", "libusb", "pyusb", "raw"),
    "darwin": ("libusb", "pyusb", "raw"),
    "linux": ("libusb", "pyusb", "raw"),
}
FALLBACK_ORDER = ("libusb", "pyusb", "raw", "usbprint")


def backend_names() -> Tuple[str, ...]:
    return tuple(BACKEND_PATHS)


def backend_class(name: str):
    """Import and return a backend class by name."""
    if name not in BACKEND_PATHS:
        raise ValueError(
            "unknown backend %r; known: %s" % (name, ", ".join(backend_names()))
        )
    module_name, class_name = BACKEND_PATHS[name]
    module = __import__(module_name, fromlist=[class_name])
    return getattr(module, class_name)


def available_backends() -> List[str]:
    """Names of the backends that can work on this machine, in default order."""
    out: List[str] = []
    for name in DEFAULT_ORDER.get(sys.platform, FALLBACK_ORDER) + ("mock",):
        if name in out:
            continue
        try:
            if backend_class(name).available():
                out.append(name)
        except Exception:
            continue
    return out


def _call_find(cls, vendor_id: Optional[int], instance_id: Optional[str], **kwargs):
    """Call ``cls.find`` with only the arguments it actually accepts."""
    find = cls.find
    try:
        parameters = inspect.signature(find).parameters
    except (TypeError, ValueError):  # pragma: no cover - builtins
        parameters = {}
    accepts_kwargs = any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()
    )
    call_kwargs = {}
    if accepts_kwargs or "vendor_id" in parameters:
        call_kwargs["vendor_id"] = vendor_id
    if instance_id is not None and (accepts_kwargs or "instance_id" in parameters):
        call_kwargs["instance_id"] = instance_id
    call_kwargs.update(kwargs)
    return find(**call_kwargs)


def find_devices(
    backends: Optional[Iterable[str]] = None,
    vendor_id: Optional[int] = EPSON_VID,
    instance_id: Optional[str] = None,
    **kwargs,
) -> List[DeviceInfo]:
    """Enumerate candidate devices across backends, in default order.

    A backend that cannot work here is skipped silently (its absence is not an
    error); a backend that *is* available but throws is reported in
    ``DeviceInfo.extra['error']``... rather, its exception message is collected
    and raised only if nothing at all was found -- enumeration of a machine
    without a printer should return an empty list, not explode.
    """
    names = tuple(backends) if backends else tuple(
        n for n in DEFAULT_ORDER.get(sys.platform, FALLBACK_ORDER) if n != "mock"
    )
    found: List[DeviceInfo] = []
    for name in names:
        try:
            cls = backend_class(name)
            if not cls.available():
                continue
            found.extend(_call_find(cls, vendor_id, instance_id, **kwargs))
        except Exception:
            continue
    return found


def open_transport(
    device=None,
    backend: Optional[str] = None,
    instance_id: Optional[str] = None,
    vendor_id: Optional[int] = EPSON_VID,
    **kwargs,
) -> Transport:
    """Return an **open** transport, trying backends in order.

    ``device`` may be

    * ``None`` -- auto-detect (the normal case),
    * a backend name (``"mock"``, ``"libusb"``, ...), which is also what
      ``backend=`` accepts,
    * a device path (``'/dev/usb/lp0'``, ``'1:4'``, a Windows interface path),
      which is handed to whichever backend claims it,
    * an already-built :class:`~epson_usb.backends.base.Transport`.

    Raises :class:`~epson_usb.errors.DeviceNotFoundError` with everything that
    was tried when no device could be opened -- never a bare ``None``.
    """
    if isinstance(device, Transport):
        if not device.opened:
            device.open()
        return device
    if isinstance(device, str) and device in BACKEND_PATHS:
        backend = backend or device
        device = None

    if backend == "mock" or device == "mock":
        return open_mock(**kwargs)

    errors: List[str] = []
    candidates: List[Tuple[str, DeviceInfo]] = []
    names = (backend,) if backend else tuple(
        n for n in DEFAULT_ORDER.get(sys.platform, FALLBACK_ORDER) if n != "mock"
    )

    if isinstance(device, str) and device:
        for name in names:
            candidates.append((name, DeviceInfo(backend=name, path=device)))
    else:
        for name in names:
            try:
                cls = backend_class(name)
                if not cls.available():
                    errors.append("%s: not available on this system" % name)
                    continue
                for info in _call_find(cls, vendor_id, instance_id, **kwargs):
                    candidates.append((name, info))
            except Exception as exc:
                errors.append("%s: %s" % (name, exc))

    for name, info in candidates:
        if info.backend == "mock":
            continue
        try:
            cls = backend_class(name)
            transport = cls(info.path, info=info, **kwargs)
            transport.open()
            return transport
        except Exception as exc:
            errors.append("%s %s: %s" % (name, info.path, exc))

    raise DeviceNotFoundError(_no_device_message(errors))


def open_mock(config=None, **kwargs) -> Transport:
    """Open the in-memory fake printer (tests, documentation, offline demos)."""
    from .mock import MockConfig, MockTransport

    transport = MockTransport(config if config is not None else MockConfig(), **kwargs)
    transport.open()
    return transport


def describe_environment() -> str:
    """A short human-readable report, used by a device-listing command."""
    lines = ["platform: %s (%s)" % (sys.platform, sys.version.split()[0])]
    lines.append("available backends: %s" % ", ".join(available_backends()))
    for name in backend_names():
        if name == "mock":
            continue
        try:
            cls = backend_class(name)
            state = "available" if cls.available() else "unavailable here"
        except Exception as exc:
            state = "unavailable (%s)" % exc
        lines.append("  - %-9s %s" % (name, state))
    return "\n".join(lines)


def _no_device_message(errors: List[str]) -> str:
    hint = {
        "win32": "Is the printer connected over USB, powered on and not in an "
        "error state? Another program (or a stale print job) may be holding "
        "the port.",
        "darwin": "Is the printer connected over USB and powered on? On macOS "
        "the libusb backend needs the printer not to be busy printing. Install "
        "libusb with 'brew install libusb' if it is missing.",
        "linux": "Is the printer connected over USB and powered on? Check "
        "'lsusb' for a 04b8 device, install libusb-1.0-0, and make sure your "
        "user may write the device (udev rule for idVendor 04b8).",
    }.get(sys.platform, "Check the cable, the power and the permissions.")
    details = "\n".join("  - %s" % e for e in errors) or "  - nothing found"
    return "no Epson printer could be opened.\n%s\nWhat was tried:\n%s" % (hint, details)


_ = DeviceInfo, BackendNotAvailableError, TransportError  # re-exported for callers

r"""POSIX character-device transport (``/dev/usb/lp0`` and friends).

Where the Windows path uses the ``USBPRINT`` device interface and libusb
claims a vendor-specific interface, this backend is the oldest and simplest
route: open the kernel's USB printer character device and read/write it.

* It works only where such a node exists: Linux with ``usblp`` loaded
  (``/dev/usb/lp0``) is the usual case.
* Interface 0 of the printer must be the one that carries the D4 channel,
  because a character device exposes exactly one interface -- on the measured
  L3251 that was interface 1, so this backend may not reach D4 at all there.
  It is offered for the models and kernels where it does, and for any other
  bidirectional character device (a pty, a FIFO pair, an emulator): pass its
  path and this backend will happily carry D4 over it.
* No kernel driver is detached and no udev rule is needed beyond read/write
  permission on the node (``usblp`` gives ``lp`` group access).

This is also the transport used by ``abrasive/epson-reversing``
(``os.open``/``os.read``/``os.write``), which is where the approach comes from.
"""

from __future__ import annotations

import glob
import os
import select
import sys
from typing import Iterable, List, Optional

from ..errors import (
    AccessDeniedError,
    BackendNotAvailableError,
    DeviceBusyError,
    DeviceNotFoundError,
    TransportError,
)
from .base import DeviceInfo, Transport

__all__ = ["RawDeviceTransport", "default_device_globs"]

#: Places a Linux USB printer node usually appears.
_LINUX_GLOBS = ("/dev/usb/lp*", "/dev/usblp*", "/dev/printers/*")
_DARWIN_GLOBS = ("/dev/usb/lp*", "/dev/ulpt*")


def default_device_globs() -> Iterable[str]:
    if sys.platform == "linux":
        return _LINUX_GLOBS
    if sys.platform == "darwin":
        return _DARWIN_GLOBS
    return ()


class RawDeviceTransport(Transport):
    """Read/write a character device directly, with ``select`` for timeouts."""

    name = "raw"

    def __init__(self, path: str, info: Optional[DeviceInfo] = None,
                 exclusive: bool = False) -> None:
        super().__init__()
        self.path = path
        self.exclusive = exclusive
        self._fd: Optional[int] = None
        self._info = info or DeviceInfo(backend=self.name, path=path,
                                        description="character device")

    # -- discovery ---------------------------------------------------------
    @classmethod
    def available(cls) -> bool:
        return os.name == "posix"

    @classmethod
    def find(cls, vendor_id: Optional[int] = None, **_kwargs) -> List[DeviceInfo]:
        if os.name != "posix":
            raise BackendNotAvailableError(
                "the 'raw' backend needs a POSIX character device (this is %s)"
                % sys.platform
            )
        out: List[DeviceInfo] = []
        for pattern in default_device_globs():
            for path in sorted(glob.glob(pattern)):
                if not os.path.exists(path):
                    continue
                out.append(
                    DeviceInfo(
                        backend=cls.name,
                        path=path,
                        description="unix character device",
                    )
                )
        override = os.environ.get("EPSON_USB_RAW_DEVICE")
        if override and override not in [item.path for item in out]:
            out.append(
                DeviceInfo(
                    backend=cls.name,
                    path=override,
                    description="character device (from EPSON_USB_RAW_DEVICE)",
                )
            )
        return out

    # -- lifecycle ---------------------------------------------------------
    def open(self) -> None:
        if self._opened:
            return
        flags = os.O_RDWR | getattr(os, "O_NOCTTY", 0)
        if not self.exclusive:
            flags |= getattr(os, "O_NONBLOCK", 0)
        try:
            self._fd = os.open(self.path, flags)
        except FileNotFoundError as exc:
            raise DeviceNotFoundError("no such device: %s" % self.path) from exc
        except PermissionError as exc:
            raise AccessDeniedError(
                "%s: permission denied (add your user to the 'lp' group, or fix "
                "the device permissions)" % self.path
            ) from exc
        except OSError as exc:
            if exc.errno in (16,):  # EBUSY
                raise DeviceBusyError("%s is busy: %s" % (self.path, exc)) from exc
            raise TransportError("%s: %s" % (self.path, exc)) from exc
        self._opened = True

    def close(self) -> None:
        fd, self._fd = self._fd, None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        self._opened = False

    # -- I/O ---------------------------------------------------------------
    def write(self, data: bytes, timeout_ms: int = 3000) -> int:
        if self._fd is None:
            raise TransportError("transport is not open")
        payload = memoryview(bytes(data))
        total = 0
        while total < len(payload):
            try:
                written = os.write(self._fd, payload[total:])
            except BlockingIOError:
                _, ready, _ = select.select([], [self._fd], [], timeout_ms / 1000.0)
                if not ready:
                    raise TransportError(
                        "write timed out after %d ms" % timeout_ms
                    )
                continue
            except InterruptedError:
                continue
            except OSError as exc:
                raise TransportError("write failed: %s" % exc) from exc
            if written <= 0:
                raise TransportError("write returned %r" % written)
            total += written
        return total

    def read(self, maxlen: int = 1024, timeout_ms: int = 2000) -> bytes:
        if self._fd is None:
            raise TransportError("transport is not open")
        deadline_ready, _, _ = select.select([self._fd], [], [], timeout_ms / 1000.0)
        if not deadline_ready:
            return b""
        try:
            return os.read(self._fd, maxlen)
        except BlockingIOError:
            return b""
        except OSError as exc:
            raise TransportError("read failed: %s" % exc) from exc

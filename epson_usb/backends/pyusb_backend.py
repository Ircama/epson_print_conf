"""Optional ``pyusb`` transport (alternative to the built-in ``libusb`` one).

The package never requires PyUSB: :mod:`epson_usb.backends.libusb` binds
``libusb-1.0`` directly through ``ctypes`` and needs nothing installed beyond
the shared library. This module exists because writing raw ``ctypes`` code is
not what most users want to debug, and because PyUSB already handles a few
platform quirks (notably on Windows, where it can pick the right backend).

Install with ``pip install "epson_usb[pyusb]"`` and select it with
``--backend pyusb``. Behaviour is otherwise identical: claim the
vendor-specific interface, use its two bulk endpoints, same timeouts.
"""

from __future__ import annotations

import errno
from typing import List, Optional

from ..errors import (
    AccessDeniedError,
    BackendNotAvailableError,
    DeviceBusyError,
    DeviceNotFoundError,
    TransportError,
)
from .base import EPSON_VID, VENDOR_SPECIFIC_CLASS, DeviceInfo, Transport

__all__ = ["PyusbTransport", "pyusb_available"]


def _import_usb():
    try:
        import usb.core  # noqa: F401
        import usb.util  # noqa: F401
    except Exception as exc:  # pragma: no cover - depends on the environment
        raise BackendNotAvailableError(
            "the 'pyusb' backend needs PyUSB: pip install pyusb "
            "(and libusb-1.0 on Linux/macOS). Original error: %s" % exc
        ) from exc
    import usb.core
    import usb.util

    return usb.core, usb.util


def pyusb_available() -> bool:
    try:
        _import_usb()
    except BackendNotAvailableError:
        return False
    return True


class PyusbTransport(Transport):
    """Transport over a PyUSB ``Device`` object."""

    name = "pyusb"

    def __init__(self, path: Optional[str] = None, info: Optional[DeviceInfo] = None,
                 interface: Optional[int] = None, detach_kernel_driver: bool = True):
        super().__init__()
        self.path = path
        self._info = info or DeviceInfo(backend=self.name, path=path or "")
        self.interface_override = interface
        self.detach_kernel_driver = detach_kernel_driver
        self._device = None
        self._interface = None
        self._endpoint_in = None
        self._endpoint_out = None
        self._detached = False

    # -- discovery ---------------------------------------------------------
    @classmethod
    def available(cls) -> bool:
        return pyusb_available()

    @classmethod
    def find(cls, vendor_id: Optional[int] = EPSON_VID, **_kwargs) -> List[DeviceInfo]:
        usb_core, usb_util = _import_usb()
        try:
            devices = list(usb_core.find(find_all=True, idVendor=vendor_id))
        except Exception as exc:
            raise BackendNotAvailableError("PyUSB could not enumerate: %s" % exc) from exc
        out = []
        for device in devices:
            interface_number = None
            try:
                configuration = device.get_active_configuration()
            except Exception:
                configuration = None
            if configuration is not None:
                for interface in configuration:
                    if int(interface.bInterfaceClass) == VENDOR_SPECIFIC_CLASS:
                        interface_number = int(interface.bInterfaceNumber)
                        break
            out.append(
                DeviceInfo(
                    backend=cls.name,
                    path="%s:%s" % (device.bus, device.address),
                    vendor_id=device.idVendor,
                    product_id=device.idProduct,
                    interface=interface_number,
                    serial=_safe_serial(device),
                    description="pyusb device %s:%s" % (device.bus, device.address),
                    extra={"bus": device.bus, "address": device.address},
                )
            )
        return out

    # -- lifecycle ---------------------------------------------------------
    def open(self) -> None:
        if self._opened:
            return
        usb_core, usb_util = _import_usb()
        device = self._match_device(usb_core)
        try:
            device.set_configuration()
        except Exception:
            # Already configured, or the configuration is not settable: the
            # interfaces may still be claimable, so this is not fatal.
            pass
        interface = self._pick_interface(device, usb_util)
        try:
            if self.detach_kernel_driver:
                try:
                    if device.is_kernel_driver_active(interface.bInterfaceNumber):
                        device.detach_kernel_driver(interface.bInterfaceNumber)
                        self._detached = True
                except NotImplementedError:
                    pass
                except Exception:
                    pass
            usb_util.claim_interface(device, interface.bInterfaceNumber)
        except Exception as exc:
            self._raise_usb_error(exc, "claim_interface")
        endpoint_in = endpoint_out = None
        for endpoint in interface:
            attributes = endpoint.bmAttributes & 0x03
            if attributes != 2:  # bulk
                continue
            if endpoint.bEndpointAddress & 0x80:
                endpoint_in = endpoint
            else:
                endpoint_out = endpoint
        if endpoint_in is None or endpoint_out is None:
            usb_util.dispose_resources(device)
            raise DeviceNotFoundError(
                "interface %d has no bulk endpoints" % interface.bInterfaceNumber
            )
        self._device = device
        self._interface = int(interface.bInterfaceNumber)
        self._endpoint_in = endpoint_in
        self._endpoint_out = endpoint_out
        self._opened = True

    def _match_device(self, usb_core):
        vendor_id = self._info.vendor_id or EPSON_VID
        product_id = self._info.product_id
        try:
            if self.path and ":" in self.path and self.path.isprintable():
                bus, _, address = self.path.partition(":")
                if bus.isdigit() and address.isdigit():
                    device = usb_core.find(
                        find_all=False, idVendor=vendor_id,
                        bus=int(bus), address=int(address),
                    )
                    if device is not None:
                        return device
            devices = list(
                usb_core.find(
                    find_all=True, idVendor=vendor_id, idProduct=product_id
                )
            )
        except Exception as exc:
            raise TransportError("PyUSB enumeration failed: %s" % exc) from exc
        if not devices:
            raise DeviceNotFoundError(
                "no Epson (0x%04x) device found by PyUSB" % vendor_id
            )
        if len(devices) > 1:
            raise DeviceNotFoundError(
                "several Epson devices found (%d); pass bus:address explicitly"
                % len(devices)
            )
        return devices[0]

    def _pick_interface(self, device, usb_util):
        selected = None
        for configuration in device:
            for interface in configuration:
                if self.interface_override is not None:
                    if int(interface.bInterfaceNumber) != self.interface_override:
                        continue
                elif int(interface.bInterfaceClass) != VENDOR_SPECIFIC_CLASS:
                    continue
                endpoints = {ep.bEndpointAddress & 0x80 for ep in interface}
                if endpoints == {0x00, 0x80}:
                    return interface
                if selected is None:
                    selected = interface
        if selected is None:
            raise DeviceNotFoundError(
                "no vendor-specific interface found (interfaces: %s). On Windows "
                "the Epson driver must be replaced by WinUSB for pyusb to work; "
                "use the 'usbprint' backend instead."
                % [
                    int(i.bInterfaceNumber)
                    for configuration in device
                    for i in configuration
                ]
            )
        return selected

    def close(self) -> None:
        device, self._device = self._device, None
        if device is None:
            self._opened = False
            return
        try:
            _, usb_util = _import_usb()
            if self._interface is not None:
                usb_util.release_interface(device, self._interface)
                if self._detached:
                    try:
                        device.attach_kernel_driver(self._interface)
                    except Exception:
                        pass
            usb_util.dispose_resources(device)
        except Exception:
            pass
        self._interface = None
        self._detached = False
        self._opened = False

    # -- I/O ---------------------------------------------------------------
    def write(self, data: bytes, timeout_ms: int = 3000) -> int:
        if self._device is None:
            raise TransportError("transport is not open")
        try:
            return int(self._device.write(self._endpoint_out, data, int(timeout_ms)))
        except Exception as exc:
            self._raise_usb_error(exc, "write")

    def read(self, maxlen: int = 1024, timeout_ms: int = 2000) -> bytes:
        if self._device is None:
            raise TransportError("transport is not open")
        try:
            return bytes(self._device.read(self._endpoint_in, maxlen, int(timeout_ms)))
        except Exception as exc:
            message = str(exc).lower()
            if "timeout" in message or "timed out" in message:
                return b""
            self._raise_usb_error(exc, "read")

    def _raise_usb_error(self, exc: Exception, action: str) -> None:
        message = "%s failed: %s" % (action, exc)
        code = getattr(exc, "errno", None)
        if code == errno.EACCES:
            raise AccessDeniedError(message + " (permissions: add a udev rule)") from exc
        if code == errno.EBUSY:
            raise DeviceBusyError(message) from exc
        if "timeout" in str(exc).lower():
            return
        raise TransportError(message) from exc


def _safe_serial(device) -> Optional[str]:
    try:
        return str(device.serial_number)
    except Exception:
        return None

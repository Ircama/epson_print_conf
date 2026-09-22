r"""Windows transport: the ``USBPRINT`` device interface, ``ctypes`` only.

This is the transport the project was verified with on hardware (L3251 over
USB, Windows, 2026-08-28 and 2026-09-04). It talks to the printer channel the
Epson driver already exposes, so **no driver replacement is needed** (no
Zadig, no WinUSB, no libusb) and there is no build step: ``ctypes`` and the
Python standard library are the whole dependency list.

Why it works: the Epson USB printer driver publishes, for each of the
printer's USB interfaces, a device interface whose path looks like ::

    \\?\usb#vid_04b8&pid_118a#...&mi_00#{28d78fad-5a12-11d1-ae5b-0000f803a8c2}

``28d78fad-5a12-11d1-ae5b-0000f803a8c2`` is the ``USBPRINT`` interface class
GUID. Opening that path with ``CreateFileW`` yields a pipe that carries the
D4/EJL byte stream of one interface. On the L3251 only interface ``MI_01``
answered D4, so candidates are ordered with ``MI_01`` first.

The interface GUID list contains every USB printer, not only Epson's, so
discovery filters on vendor id ``04B8``.

Two devices descriptors matter: the printer's *device* serial (the USB
``iSerialNumber`` string descriptor) may be needed by the ``rw`` service
command, and it is read by walking up the device tree with ``cfgmgr32``. That
string is **not** the EEPROM serial: on the measured printer the EEPROM holds
ten plain text characters while the USB descriptor reports the ASCII-hex of
the first eight of them plus a trailing ``00``.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import re
import struct
import sys
from typing import List, Optional

from ..errors import (
    AccessDeniedError,
    BackendNotAvailableError,
    DeviceBusyError,
    DeviceNotFoundError,
    TransportError,
)
from .base import EPSON_VID, DeviceInfo, Transport

__all__ = [
    "IS_WINDOWS",
    "USBPRINT_GUID_STRING",
    "WindowsUsbPrintTransport",
    "device_paths",
    "usb_serial_candidates",
]

IS_WINDOWS = sys.platform == "win32"

USBPRINT_GUID_STRING = "28d78fad-5a12-11d1-ae5b-0000f803a8c2"

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
ERROR_IO_PENDING = 997
ERROR_ACCESS_DENIED = 5
ERROR_SHARING_VIOLATION = 32
ERROR_BUSY = 170
WAIT_TIMEOUT = 0x102
DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
CR_SUCCESS = 0

_WINERR_NAMES = {
    2: "FILE_NOT_FOUND",
    5: "ACCESS_DENIED",
    6: "INVALID_HANDLE",
    31: "GEN_FAILURE",
    32: "SHARING_VIOLATION",
    87: "INVALID_PARAMETER",
    170: "BUSY",
    1117: "IO_DEVICE",
}


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("InterfaceClassGuid", GUID),
        ("Flags", wt.DWORD),
        ("Reserved", ctypes.POINTER(ctypes.c_ulong)),
    ]


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("ClassGuid", GUID),
        ("DevInst", wt.DWORD),
        ("Reserved", ctypes.POINTER(ctypes.c_ulong)),
    ]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_void_p),
        ("InternalHigh", ctypes.c_void_p),
        ("Offset", wt.DWORD),
        ("OffsetHigh", wt.DWORD),
        ("hEvent", wt.HANDLE),
    ]


#: The USBPRINT interface class GUID, as a ctypes structure.
USBPRINT_GUID = GUID(
    0x28d78FAD, 0x5A12, 0x11D1, (ctypes.c_ubyte * 8)(0xAE, 0x5B, 0x00, 0x00, 0xF8, 0x03, 0xA8, 0xC2)
)


class _WindowsApi:
    """Lazily bound ``setupapi`` / ``kernel32`` / ``cfgmgr32`` entry points.

    Binding is deferred so that importing this module on Linux or macOS is
    free and safe -- ``ctypes.WinDLL`` does not even exist there, so touching
    it at import time would break the import.
    """

    def __init__(self) -> None:
        if not IS_WINDOWS:
            raise BackendNotAvailableError(
                "the 'usbprint' backend is Windows only (this is %s). Use "
                "'libusb' on Linux/macOS, or 'raw' with a character device."
                % sys.platform
            )
        self.setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        try:
            self.cfgmgr32 = ctypes.WinDLL("cfgmgr32", use_last_error=True)
        except OSError:  # pragma: no cover - cfgmgr32 ships with Windows
            self.cfgmgr32 = None
        self._declare()

    def _declare(self) -> None:
        k = self.kernel32
        s = self.setupapi
        k.CreateFileW.restype = wt.HANDLE
        k.CreateFileW.argtypes = [
            wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID, wt.DWORD, wt.DWORD, wt.HANDLE
        ]
        k.CreateEventW.restype = wt.HANDLE
        k.CreateEventW.argtypes = [wt.LPVOID, wt.BOOL, wt.BOOL, wt.LPCWSTR]
        k.WriteFile.restype = wt.BOOL
        k.WriteFile.argtypes = [wt.HANDLE, wt.LPCVOID, wt.DWORD,
                                ctypes.POINTER(wt.DWORD), ctypes.POINTER(OVERLAPPED)]
        k.ReadFile.restype = wt.BOOL
        k.ReadFile.argtypes = [wt.HANDLE, wt.LPVOID, wt.DWORD,
                               ctypes.POINTER(wt.DWORD), ctypes.POINTER(OVERLAPPED)]
        k.WaitForSingleObject.restype = wt.DWORD
        k.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
        k.GetOverlappedResult.restype = wt.BOOL
        k.GetOverlappedResult.argtypes = [wt.HANDLE, ctypes.POINTER(OVERLAPPED),
                                          ctypes.POINTER(wt.DWORD), wt.BOOL]
        k.CancelIo.restype = wt.BOOL
        k.CancelIo.argtypes = [wt.HANDLE]
        k.CloseHandle.restype = wt.BOOL
        k.CloseHandle.argtypes = [wt.HANDLE]
        s.SetupDiGetClassDevsW.restype = wt.HANDLE
        s.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wt.LPCWSTR, wt.HWND, wt.DWORD]
        s.SetupDiEnumDeviceInterfaces.restype = wt.BOOL
        s.SetupDiEnumDeviceInterfaces.argtypes = [
            wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p
        ]
        s.SetupDiGetDeviceInterfaceDetailW.restype = wt.BOOL
        s.SetupDiGetDeviceInterfaceDetailW.argtypes = [
            wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD,
            ctypes.POINTER(wt.DWORD), ctypes.POINTER(SP_DEVINFO_DATA)
        ]
        s.SetupDiDestroyDeviceInfoList.restype = wt.BOOL
        s.SetupDiDestroyDeviceInfoList.argtypes = [wt.HANDLE]
        if self.cfgmgr32 is not None:
            self.cfgmgr32.CM_Get_Parent.restype = ctypes.c_ulong
            self.cfgmgr32.CM_Get_Parent.argtypes = [
                ctypes.POINTER(wt.DWORD), wt.DWORD, ctypes.c_ulong
            ]
            self.cfgmgr32.CM_Get_Device_IDW.restype = ctypes.c_ulong
            self.cfgmgr32.CM_Get_Device_IDW.argtypes = [
                wt.DWORD, wt.LPWSTR, ctypes.c_ulong, ctypes.c_ulong
            ]

    # -- helpers -----------------------------------------------------------
    def winerr(self, code: int) -> str:
        return "%s (%s)" % (code, _WINERR_NAMES.get(code, "?"))

    def raise_for_winerr(self, code: int, action: str) -> None:
        message = "%s failed: WinErr %s" % (action, self.winerr(code))
        if code == ERROR_ACCESS_DENIED:
            raise AccessDeniedError(message)
        if code in (ERROR_SHARING_VIOLATION, ERROR_BUSY):
            raise DeviceBusyError(message)
        raise TransportError(message)


_API: Optional[_WindowsApi] = None


def _api() -> _WindowsApi:
    """Return the cached Windows API binding (built on first use)."""
    global _API
    if _API is None:
        _API = _WindowsApi()
    return _API


def _device_interface_path(hdev, ifdata) -> Optional[str]:
    """Resolve one enumerated interface to its device path."""
    api = _api()
    required = wt.DWORD(0)
    api.setupapi.SetupDiGetDeviceInterfaceDetailW(
        hdev, ctypes.byref(ifdata), None, 0, ctypes.byref(required), None
    )
    if not required.value:
        return None
    buffer = ctypes.create_string_buffer(required.value)
    # SP_DEVICE_INTERFACE_DETAIL_DATA_W.cbSize: 8 on 64-bit, 6 on 32-bit.
    cb_size = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
    ctypes.memmove(buffer, struct.pack("I", cb_size), 4)
    if not api.setupapi.SetupDiGetDeviceInterfaceDetailW(
        hdev, ctypes.byref(ifdata), buffer, required.value, None, None
    ):
        return None
    return ctypes.wstring_at(ctypes.addressof(buffer) + 4)


def device_paths(instance_id: Optional[str] = None) -> List[str]:
    """Every USBPRINT device path for an Epson printer, ``MI_01`` first.

    ``instance_id`` (a Windows device instance id such as
    ``USB\\VID_04B8&PID_118A&MI_00\\7&...``) is turned into the equivalent
    device interface path; that is the escape hatch when automatic discovery
    does not find the printer.
    """
    api = _api()
    paths: List[str] = []
    hdev = api.setupapi.SetupDiGetClassDevsW(
        ctypes.byref(USBPRINT_GUID), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
    )
    if hdev and hdev != INVALID_HANDLE_VALUE:
        try:
            index = 0
            while True:
                ifdata = SP_DEVICE_INTERFACE_DATA()
                ifdata.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
                if not api.setupapi.SetupDiEnumDeviceInterfaces(
                    hdev, None, ctypes.byref(USBPRINT_GUID), index, ctypes.byref(ifdata)
                ):
                    break
                index += 1
                path = _device_interface_path(hdev, ifdata)
                if path:
                    paths.append(path)
        finally:
            api.setupapi.SetupDiDestroyDeviceInfoList(hdev)

    candidates = list(paths)
    if instance_id:
        candidates.append(
            r"\\?\%s#{%s}" % (instance_id.replace("\\", "#"), USBPRINT_GUID_STRING)
        )
    # The same interface can be addressed with any MI_0x suffix; try them all.
    expanded: List[str] = []
    for path in candidates:
        expanded.append(path)
        for mi in ("mi_00", "mi_01", "mi_02"):
            expanded.append(re.sub(r"mi_0\d", mi, path, flags=re.IGNORECASE))

    seen, out = set(), []
    for path in expanded:
        if "VID_%04X" % EPSON_VID not in path.upper():
            continue
        key = path.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    # MI_01 was the only interface that answered D4 on the measured printer.
    out.sort(key=lambda p: (0 if "MI_01" in p.upper() else 1))
    return out


def _looks_like_serial(segment: str) -> bool:
    segment = (segment or "").strip()
    if not segment or "&" in segment or not (4 <= len(segment) <= 32):
        return False
    return all(c.isalnum() or c in "-_" for c in segment)


def _device_id(devinst) -> Optional[str]:
    api = _api()
    if api.cfgmgr32 is None:
        return None
    buffer = ctypes.create_unicode_buffer(512)
    if api.cfgmgr32.CM_Get_Device_IDW(devinst, buffer, 512, 0) != CR_SUCCESS:
        return None
    return buffer.value


def usb_serial_candidates() -> List[str]:
    """Strings the Windows USB stack reports as the printer's device serial.

    These are candidates for the string the firmware hashes in the ``rw``
    command. Windows does not preserve the descriptor's letter case (symbolic
    links come back lower case, SetupAPI ids upper case), which is why more
    than one form is returned and the caller tries them in order.
    """
    api = _api()
    out: List[str] = []

    def add(value: Optional[str]) -> None:
        if value and value not in out:
            out.append(value)

    hdev = api.setupapi.SetupDiGetClassDevsW(
        ctypes.byref(USBPRINT_GUID), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
    )
    if not hdev or hdev == INVALID_HANDLE_VALUE:
        return out
    try:
        index = 0
        while True:
            ifdata = SP_DEVICE_INTERFACE_DATA()
            ifdata.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not api.setupapi.SetupDiEnumDeviceInterfaces(
                hdev, None, ctypes.byref(USBPRINT_GUID), index, ctypes.byref(ifdata)
            ):
                break
            index += 1
            required = wt.DWORD(0)
            api.setupapi.SetupDiGetDeviceInterfaceDetailW(
                hdev, ctypes.byref(ifdata), None, 0, ctypes.byref(required), None
            )
            if not required.value:
                continue
            buffer = ctypes.create_string_buffer(required.value)
            cb_size = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            ctypes.memmove(buffer, struct.pack("I", cb_size), 4)
            info = SP_DEVINFO_DATA()
            info.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
            if not api.setupapi.SetupDiGetDeviceInterfaceDetailW(
                hdev, ctypes.byref(ifdata), buffer, required.value, None,
                ctypes.byref(info)
            ):
                continue
            path = ctypes.wstring_at(ctypes.addressof(buffer) + 4)
            if "VID_%04X" % EPSON_VID not in path.upper():
                continue
            parts = path.split("#")
            if len(parts) > 2 and _looks_like_serial(parts[2]):
                add(parts[2])
            devinst = info.DevInst
            for _ in range(3):  # interface -> device -> (grand)parent
                parent = wt.DWORD(0)
                if api.cfgmgr32 is None or api.cfgmgr32.CM_Get_Parent(
                    ctypes.byref(parent), devinst, 0
                ) != CR_SUCCESS:
                    break
                devinst = parent.value
                device_id = _device_id(devinst) or ""
                if not device_id.upper().startswith("USB\\"):
                    break
                segment = device_id.split("\\")[-1]
                if _looks_like_serial(segment):
                    add(segment)
                    break
    finally:
        api.setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return out


class WindowsUsbPrintTransport(Transport):
    """Overlapped-I/O transport over one ``USBPRINT`` device path."""

    name = "usbprint"

    def __init__(self, path: str, info: Optional[DeviceInfo] = None) -> None:
        super().__init__()
        self.path = path
        self._handle = None
        self._info = info or DeviceInfo(backend=self.name, path=path)

    # -- lifecycle ---------------------------------------------------------
    def open(self) -> None:
        if self._opened:
            return
        api = _api()
        handle = api.kernel32.CreateFileW(
            self.path,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_OVERLAPPED,
            None,
        )
        if not handle or handle == INVALID_HANDLE_VALUE:
            api.raise_for_winerr(ctypes.get_last_error(), "CreateFile(%s)" % self.path)
        self._handle = handle
        self._opened = True

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle:
            try:
                _api().kernel32.CloseHandle(handle)
            except Exception:
                pass
        self._opened = False

    # -- I/O ---------------------------------------------------------------
    def _overlapped_io(self, func, data_or_len, timeout_ms: int, reading: bool):
        api = _api()
        overlapped = OVERLAPPED()
        overlapped.hEvent = api.kernel32.CreateEventW(None, True, False, None)
        try:
            transferred = wt.DWORD(0)
            if reading:
                buffer = ctypes.create_string_buffer(data_or_len)
                ok = func(self._handle, buffer, data_or_len,
                          ctypes.byref(transferred), ctypes.byref(overlapped))
            else:
                buffer = ctypes.create_string_buffer(data_or_len, len(data_or_len))
                ok = func(self._handle, buffer, len(data_or_len),
                          ctypes.byref(transferred), ctypes.byref(overlapped))
            if not ok:
                error = ctypes.get_last_error()
                if error == ERROR_IO_PENDING:
                    if api.kernel32.WaitForSingleObject(
                        overlapped.hEvent, timeout_ms
                    ) == WAIT_TIMEOUT:
                        api.kernel32.CancelIo(self._handle)
                        return None
                    got = wt.DWORD(0)
                    if not api.kernel32.GetOverlappedResult(
                        self._handle, ctypes.byref(overlapped), ctypes.byref(got), True
                    ):
                        return None
                    transferred = got
                else:
                    api.raise_for_winerr(error, "device I/O")
            return buffer.raw[: transferred.value] if reading else transferred.value
        finally:
            api.kernel32.CloseHandle(overlapped.hEvent)

    def write(self, data: bytes, timeout_ms: int = 3000) -> int:
        written = self._overlapped_io(
            _api().kernel32.WriteFile, data, timeout_ms, reading=False
        )
        if written is None:
            raise TransportError("write timed out after %d ms" % timeout_ms)
        return written

    def read(self, maxlen: int = 1024, timeout_ms: int = 2000) -> bytes:
        data = self._overlapped_io(
            _api().kernel32.ReadFile, maxlen, timeout_ms, reading=True
        )
        return data or b""

    # -- discovery ---------------------------------------------------------
    @classmethod
    def available(cls) -> bool:
        return IS_WINDOWS

    @classmethod
    def find(cls, vendor_id: Optional[int] = EPSON_VID, instance_id: Optional[str] = None,
             **_kwargs) -> List[DeviceInfo]:
        if vendor_id not in (None, EPSON_VID):
            return []
        instance_id = instance_id or os.environ.get("EPSON_INSTANCE_ID")
        return [
            DeviceInfo(
                backend=cls.name,
                path=path,
                vendor_id=EPSON_VID,
                description="Windows USBPRINT interface path",
                extra={"instance_id": instance_id} if instance_id else {},
            )
            for path in device_paths(instance_id)
        ]


def open_transport(path: str) -> WindowsUsbPrintTransport:
    transport = WindowsUsbPrintTransport(path)
    transport.open()
    return transport


#: Raised by :meth:`WindowsUsbPrintTransport.find` when nothing was found and
#: an explicit instance id would help.
HINT = (
    "No Epson USBPRINT interface found. Check that the printer is on and "
    "connected over USB; you can also pass its device instance id "
    r"(--instance-id 'USB\VID_04B8&...', from Device Manager > Details)."
)

_ = DeviceNotFoundError, HINT  # kept importable for callers that format it

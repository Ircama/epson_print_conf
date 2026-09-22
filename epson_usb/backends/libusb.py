r"""``libusb`` transport for Linux and macOS (and Windows with WinUSB).

This is a *self-contained* ``ctypes`` binding to ``libusb-1.0``: no PyPI
dependency, no compile step, the same trick the Windows backend uses. PyUSB,
if installed, is offered as an alternative in
:mod:`epson_usb.backends.pyusb_backend` -- the two are deliberately
independent, so the package works with either one present or neither.

Why libusb at all, when the Windows path does not need it? Because there is no
Windows-style ``USBPRINT`` interface on Linux and macOS. There the printer's
vendor-specific interface must be claimed directly, which needs the kernel
driver to let go of it first:

* **Linux** -- ``usblp`` (the ``/dev/usb/lp*`` driver) usually owns interface
  0. The code calls ``libusb_detach_kernel_driver`` (and re-attaches it on
  close), and needs write permission on the device: with ``libusb`` this is a
  udev rule (``SUBSYSTEM=="usb", ATTR{idVendor}=="04b8", MODE="0666"``), not a
  driver swap.
* **macOS** -- no device nodes are involved at all; ``libusb`` talks to the
  IOKit layer, and the parent kernel driver is detached automatically where
  the library supports it.

Only the *vendor-specific* interface answers D4 (``bInterfaceClass == 0xFF``).
For the L3250 that was interface 2: a report on ``epson_print_conf`` issue #35
found interfaces 0 and 1 could not be claimed while interface 2 could, and the
Epson driver kept working. :func:`select_interface_and_endpoints` encodes that
preference and is a pure function, so it is unit-tested with synthetic
descriptors rather than needing hardware.

Install the shared library with:

* Debian/Ubuntu: ``sudo apt install libusb-1.0-0``
* Fedora: ``sudo dnf install libusb1``
* macOS (Homebrew): ``brew install libusb``
* Windows: ``libusb-1.0.dll`` (shipped with Zadig/WinUSB tooling)

Set ``EPSON_USB_LIBUSB`` to point at a specific library file if discovery
fails.
"""

from __future__ import annotations

import contextlib
import ctypes
import ctypes.util
import os
import sys
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from ..errors import (
    AccessDeniedError,
    BackendNotAvailableError,
    DeviceBusyError,
    DeviceNotFoundError,
    TransportError,
)
from .base import EPSON_VID, VENDOR_SPECIFIC_CLASS, DeviceInfo, Transport

__all__ = [
    "LibusbTransport",
    "InterfaceDescriptor",
    "EndpointDescriptor",
    "select_interface_and_endpoints",
    "libusb_library_path",
    "libusb_available",
]

LIBUSB_SUCCESS = 0
LIBUSB_ERROR_IO = -1
LIBUSB_ERROR_INVALID_PARAM = -2
LIBUSB_ERROR_ACCESS = -3
LIBUSB_ERROR_NO_DEVICE = -4
LIBUSB_ERROR_NOT_FOUND = -5
LIBUSB_ERROR_BUSY = -6
LIBUSB_ERROR_TIMEOUT = -7
LIBUSB_ERROR_OVERFLOW = -8
LIBUSB_ERROR_PIPE = -9
LIBUSB_ERROR_INTERRUPTED = -10
LIBUSB_ERROR_NO_MEM = -11
LIBUSB_ERROR_NOT_SUPPORTED = -12
LIBUSB_ERROR_NOT_FOUND_OTHER = -99

TRANSFER_TYPE_MASK = 0x03
TRANSFER_TYPE_BULK = 0x02
ENDPOINT_DIRECTION_MASK = 0x80

#: Candidate library file names, per platform, after ``find_library``.
_LIBRARY_NAMES = {
    "darwin": ("libusb-1.0.dylib", "libusb-1.0.0.dylib"),
    "linux": ("libusb-1.0.so.0", "libusb-1.0.so"),
    "win32": ("libusb-1.0.dll", "libusb-1.0.x64.dll"),
}
_DARWIN_SEARCH_DIRS = (
    "/opt/homebrew/lib",
    "/usr/local/lib",
    "/opt/local/lib",
    "/Library/Developer/CommandLineTools/usr/lib",
)


# --------------------------------------------------------------------------- #
#  Descriptors
# --------------------------------------------------------------------------- #
class LibusbDeviceDescriptor(ctypes.Structure):
    _fields_ = [
        ("bLength", ctypes.c_uint8),
        ("bDescriptorType", ctypes.c_uint8),
        ("bcdUSB", ctypes.c_uint16),
        ("bDeviceClass", ctypes.c_uint8),
        ("bDeviceSubClass", ctypes.c_uint8),
        ("bDeviceProtocol", ctypes.c_uint8),
        ("bMaxPacketSize0", ctypes.c_uint8),
        ("idVendor", ctypes.c_uint16),
        ("idProduct", ctypes.c_uint16),
        ("bcdDevice", ctypes.c_uint16),
        ("iManufacturer", ctypes.c_uint8),
        ("iProduct", ctypes.c_uint8),
        ("iSerialNumber", ctypes.c_uint8),
        ("bNumConfigurations", ctypes.c_uint8),
    ]


class LibusbEndpointDescriptor(ctypes.Structure):
    _fields_ = [
        ("bLength", ctypes.c_uint8),
        ("bDescriptorType", ctypes.c_uint8),
        ("bEndpointAddress", ctypes.c_uint8),
        ("bmAttributes", ctypes.c_uint8),
        ("wMaxPacketSize", ctypes.c_uint16),
        ("bInterval", ctypes.c_uint8),
        ("bRefresh", ctypes.c_uint8),
        ("bSynchAddress", ctypes.c_uint8),
        ("extra", ctypes.c_void_p),
        ("extra_length", ctypes.c_int),
    ]


class LibusbInterfaceDescriptor(ctypes.Structure):
    pass


LibusbInterfaceDescriptor._fields_ = [
    ("bLength", ctypes.c_uint8),
    ("bDescriptorType", ctypes.c_uint8),
    ("bInterfaceNumber", ctypes.c_uint8),
    ("bAlternateSetting", ctypes.c_uint8),
    ("bNumEndpoints", ctypes.c_uint8),
    ("bInterfaceClass", ctypes.c_uint8),
    ("bInterfaceSubClass", ctypes.c_uint8),
    ("bInterfaceProtocol", ctypes.c_uint8),
    ("iInterface", ctypes.c_uint8),
    ("endpoint", ctypes.POINTER(LibusbEndpointDescriptor)),
    ("extra", ctypes.c_void_p),
    ("extra_length", ctypes.c_int),
]


class LibusbInterface(ctypes.Structure):
    pass


LibusbInterface._fields_ = [
    ("altsetting", ctypes.POINTER(LibusbInterfaceDescriptor)),
    ("num_altsetting", ctypes.c_int),
]


class LibusbConfigDescriptor(ctypes.Structure):
    pass


LibusbConfigDescriptor._fields_ = [
    ("bLength", ctypes.c_uint8),
    ("bDescriptorType", ctypes.c_uint8),
    ("wTotalLength", ctypes.c_uint16),
    ("bNumInterfaces", ctypes.c_uint8),
    ("bConfigurationValue", ctypes.c_uint8),
    ("iConfiguration", ctypes.c_uint8),
    ("bmAttributes", ctypes.c_uint8),
    ("bMaxPower", ctypes.c_uint8),
    ("interface", ctypes.POINTER(LibusbInterface)),
    ("extra", ctypes.c_void_p),
    ("extra_length", ctypes.c_int),
]


@dataclass(frozen=True)
class EndpointDescriptor:
    """Just the parts of an endpoint descriptor that matter here."""

    address: int
    attributes: int
    max_packet_size: int
    interval: int = 0

    @property
    def number(self) -> int:
        return self.address & 0x0F

    @property
    def is_in(self) -> bool:
        return bool(self.address & ENDPOINT_DIRECTION_MASK)

    @property
    def is_bulk(self) -> bool:
        return (self.attributes & TRANSFER_TYPE_MASK) == TRANSFER_TYPE_BULK


@dataclass(frozen=True)
class InterfaceDescriptor:
    """Just the parts of an interface descriptor that matter here."""

    number: int
    alternate: int = 0
    interface_class: int = 0
    interface_subclass: int = 0
    interface_protocol: int = 0
    endpoints: Tuple[EndpointDescriptor, ...] = ()

    @property
    def is_vendor_specific(self) -> bool:
        return self.interface_class == VENDOR_SPECIFIC_CLASS

    @property
    def bulk_in(self) -> Optional[EndpointDescriptor]:
        for endpoint in self.endpoints:
            if endpoint.is_bulk and endpoint.is_in:
                return endpoint
        return None

    @property
    def bulk_out(self) -> Optional[EndpointDescriptor]:
        for endpoint in self.endpoints:
            if endpoint.is_bulk and not endpoint.is_in:
                return endpoint
        return None


def select_interface_and_endpoints(
    interfaces: Sequence[InterfaceDescriptor],
) -> Optional[Tuple[InterfaceDescriptor, EndpointDescriptor, EndpointDescriptor]]:
    """Pick the interface that can carry D4, and its two bulk endpoints.

    Preference order (documented, and covered by tests with synthetic
    descriptors):

    1. vendor-specific interfaces (class 0xFF) that have both a bulk IN and a
       bulk OUT endpoint -- the D4 control channel lives there;
    2. any other interface with both bulk endpoints, lowest number first;
    3. nothing usable -> ``None``.

    Among equals the lowest interface number wins, so the choice is stable
    across runs.
    """
    usable = []
    for interface in interfaces:
        bulk_in, bulk_out = interface.bulk_in, interface.bulk_out
        if bulk_in is None or bulk_out is None:
            continue
        if interface.alternate != 0:
            continue  # alternate settings are only entered on request
        usable.append((0 if interface.is_vendor_specific else 1, interface.number, interface,
                       bulk_in, bulk_out))
    if not usable:
        return None
    usable.sort(key=lambda item: (item[0], item[1]))
    _, _, interface, bulk_in, bulk_out = usable[0]
    return interface, bulk_in, bulk_out


# --------------------------------------------------------------------------- #
#  ctypes binding
# --------------------------------------------------------------------------- #
def libusb_library_path() -> Optional[str]:
    """Locate the ``libusb-1.0`` shared library, or return ``None``."""
    override = os.environ.get("EPSON_USB_LIBUSB")
    if override:
        return override if os.path.exists(override) else None
    found = ctypes.util.find_library("usb-1.0")
    if found:
        return found
    names = _LIBRARY_NAMES.get(sys.platform, ("libusb-1.0.so.0",))
    if sys.platform == "darwin":
        for directory in _DARWIN_SEARCH_DIRS:
            for name in names:
                candidate = os.path.join(directory, name)
                if os.path.exists(candidate):
                    return candidate
    if sys.platform == "win32":
        for name in names:
            if os.path.exists(name):
                return name
        # PyUSB ships the DLL; reuse it when it is around.
        try:  # pragma: no cover - depends on the installed environment
            import usb.backend.libusb1 as _pyusb_libusb1

            candidate = _pyusb_libusb1.get_backend()
            if candidate is not None and getattr(candidate, "lib", None):
                return candidate.lib._name
        except Exception:
            pass
    return names[0] if sys.platform == "linux" else None


INSTALL_HINT = {
    "linux": "install it with: sudo apt install libusb-1.0-0 "
    "(or: sudo dnf install libusb1)",
    "darwin": "install it with: brew install libusb",
    "win32": "install libusb-1.0.dll (Zadig/WinUSB tooling provides it)",
}


def libusb_available() -> bool:
    """True when ``libusb-1.0`` can be loaded and initialised here."""
    try:
        _Libusb.get()
    except Exception:
        return False
    return True


class _Libusb:
    """A minimal, lazily created binding to ``libusb-1.0``."""

    _instance: Optional["_Libusb"] = None

    def __init__(self) -> None:
        path = libusb_library_path()
        if not path:
            raise BackendNotAvailableError(
                "libusb-1.0 was not found on this machine; %s"
                % INSTALL_HINT.get(sys.platform, "install libusb-1.0")
            )
        try:
            self.lib = ctypes.CDLL(path)
        except OSError as exc:
            raise BackendNotAvailableError(
                "could not load %s (%s); %s"
                % (path, exc, INSTALL_HINT.get(sys.platform, "install libusb-1.0"))
            ) from exc
        self.path = path
        self._declare()
        self.context = ctypes.c_void_p()
        self.init_error = self.lib.libusb_init(ctypes.byref(self.context))
        if self.init_error != LIBUSB_SUCCESS:
            raise BackendNotAvailableError(
                "libusb_init failed (%s)" % self.error_name(self.init_error)
            )

    @classmethod
    def get(cls) -> "_Libusb":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _declare(self) -> None:
        lib = self.lib
        lib.libusb_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        lib.libusb_init.restype = ctypes.c_int
        lib.libusb_exit.argtypes = [ctypes.c_void_p]
        lib.libusb_exit.restype = None
        lib.libusb_get_device_list.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))]
        lib.libusb_get_device_list.restype = ctypes.c_ssize_t
        lib.libusb_free_device_list.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_int]
        lib.libusb_free_device_list.restype = None
        lib.libusb_get_device_descriptor.argtypes = [ctypes.c_void_p, ctypes.POINTER(LibusbDeviceDescriptor)]
        lib.libusb_get_device_descriptor.restype = ctypes.c_int
        lib.libusb_get_bus_number.argtypes = [ctypes.c_void_p]
        lib.libusb_get_bus_number.restype = ctypes.c_uint8
        lib.libusb_get_device_address.argtypes = [ctypes.c_void_p]
        lib.libusb_get_device_address.restype = ctypes.c_uint8
        lib.libusb_get_active_config_descriptor.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(LibusbConfigDescriptor))
        ]
        lib.libusb_get_active_config_descriptor.restype = ctypes.c_int
        lib.libusb_get_config_descriptor.argtypes = [
            ctypes.c_void_p, ctypes.c_uint8,
            ctypes.POINTER(ctypes.POINTER(LibusbConfigDescriptor)),
        ]
        lib.libusb_get_config_descriptor.restype = ctypes.c_int
        lib.libusb_free_config_descriptor.argtypes = [ctypes.POINTER(LibusbConfigDescriptor)]
        lib.libusb_free_config_descriptor.restype = None
        lib.libusb_open.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        lib.libusb_open.restype = ctypes.c_int
        lib.libusb_close.argtypes = [ctypes.c_void_p]
        lib.libusb_close.restype = None
        lib.libusb_set_configuration.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.libusb_set_configuration.restype = ctypes.c_int
        lib.libusb_claim_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.libusb_claim_interface.restype = ctypes.c_int
        lib.libusb_release_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.libusb_release_interface.restype = ctypes.c_int
        lib.libusb_kernel_driver_active.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.libusb_kernel_driver_active.restype = ctypes.c_int
        lib.libusb_detach_kernel_driver.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.libusb_detach_kernel_driver.restype = ctypes.c_int
        lib.libusb_attach_kernel_driver.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.libusb_attach_kernel_driver.restype = ctypes.c_int
        lib.libusb_clear_halt.argtypes = [ctypes.c_void_p, ctypes.c_uint8]
        lib.libusb_clear_halt.restype = ctypes.c_int
        lib.libusb_bulk_transfer.argtypes = [
            ctypes.c_void_p, ctypes.c_uint8, ctypes.c_void_p, ctypes.c_int,
            ctypes.POINTER(ctypes.c_int), ctypes.c_uint,
        ]
        lib.libusb_bulk_transfer.restype = ctypes.c_int
        lib.libusb_get_string_descriptor_ascii.argtypes = [
            ctypes.c_void_p, ctypes.c_uint8, ctypes.c_void_p, ctypes.c_int
        ]
        lib.libusb_get_string_descriptor_ascii.restype = ctypes.c_int
        lib.libusb_error_name.argtypes = [ctypes.c_int]
        lib.libusb_error_name.restype = ctypes.c_char_p
        # Optional (libusb >= 1.0.16): macOS and Linux auto-detach.
        self.auto_detach = getattr(lib, "libusb_set_auto_detach_kernel_driver", None)
        if self.auto_detach is not None:
            self.auto_detach.argtypes = [ctypes.c_void_p, ctypes.c_int]
            self.auto_detach.restype = ctypes.c_int

    def error_name(self, code: int) -> str:
        try:
            name = self.lib.libusb_error_name(code)
            if name:
                return "%s (%d)" % (name.decode(), code)
        except Exception:  # pragma: no cover - older libusb
            pass
        return "error %d" % code

    def raise_for(self, code: int, action: str) -> None:
        """Turn a libusb error code into the right exception."""
        name = self.error_name(code)
        message = "%s failed: %s" % (action, name)
        if code == LIBUSB_ERROR_ACCESS:
            raise AccessDeniedError(message + " (check permissions / udev rules)")
        if code == LIBUSB_ERROR_BUSY:
            raise DeviceBusyError(message + " (another program holds the interface)")
        if code in (LIBUSB_ERROR_NO_DEVICE, LIBUSB_ERROR_NOT_FOUND):
            raise DeviceNotFoundError(message)
        if code == LIBUSB_ERROR_NOT_SUPPORTED:
            raise BackendNotAvailableError(message)
        raise TransportError(message)

    @contextlib.contextmanager
    def device_list(self):
        """Enumerate devices, yielding ``[(device, descriptor), ...]``.

        The devices are only valid **inside** this context:
        ``libusb_free_device_list(list, 1)`` unrefs every device as well as
        freeing the array, so holding a device pointer afterwards is a
        use-after-free. (On Windows that is an outright access violation,
        which is how this was found -- an earlier version handed the pointers
        out and crashed as soon as it read a configuration descriptor.)
        """
        pointer = ctypes.POINTER(ctypes.c_void_p)()
        count = self.lib.libusb_get_device_list(self.context, ctypes.byref(pointer))
        if count < 0:
            self.raise_for(count, "libusb_get_device_list")
        try:
            entries = []
            for index in range(count):
                handle = pointer[index]
                descriptor = LibusbDeviceDescriptor()
                if self.lib.libusb_get_device_descriptor(
                    handle, ctypes.byref(descriptor)
                ) != LIBUSB_SUCCESS:
                    continue
                entries.append((handle, descriptor))
            yield entries
        finally:
            self.lib.libusb_free_device_list(pointer, 1)

    def _devices_and_descriptors(self):
        """Deprecated accessor kept for callers that only need the descriptors."""
        with self.device_list() as entries:
            return [(descriptor, ) for _handle, descriptor in entries]

    # -- conversions -------------------------------------------------------
    def config_of(self, device) -> Optional[LibusbConfigDescriptor]:
        """The active configuration descriptor, or the first one as a fallback.

        On Windows a device whose driver has not been loaded has no *active*
        configuration, so the numbered lookup is tried before giving up.
        """
        config_ptr = ctypes.POINTER(LibusbConfigDescriptor)()
        result = self.lib.libusb_get_active_config_descriptor(
            device, ctypes.byref(config_ptr)
        )
        if result == LIBUSB_SUCCESS and config_ptr:
            return config_ptr
        config_ptr = ctypes.POINTER(LibusbConfigDescriptor)()
        result = self.lib.libusb_get_config_descriptor(
            device, 0, ctypes.byref(config_ptr)
        )
        if result == LIBUSB_SUCCESS and config_ptr:
            return config_ptr
        return None

    def interfaces_of(self, config_ptr) -> Tuple[InterfaceDescriptor, ...]:
        config = config_ptr.contents
        interfaces = []
        for index in range(config.bNumInterfaces):
            interface = config.interface[index]
            for alt_index in range(interface.num_altsetting):
                alt = interface.altsetting[alt_index]
                endpoints = tuple(
                    EndpointDescriptor(
                        address=int(alt.endpoint[ep].bEndpointAddress),
                        attributes=int(alt.endpoint[ep].bmAttributes),
                        max_packet_size=int(alt.endpoint[ep].wMaxPacketSize),
                        interval=int(alt.endpoint[ep].bInterval),
                    )
                    for ep in range(alt.bNumEndpoints)
                )
                interfaces.append(
                    InterfaceDescriptor(
                        number=int(alt.bInterfaceNumber),
                        alternate=int(alt.bAlternateSetting),
                        interface_class=int(alt.bInterfaceClass),
                        interface_subclass=int(alt.bInterfaceSubClass),
                        interface_protocol=int(alt.bInterfaceProtocol),
                        endpoints=endpoints,
                    )
                )
        return tuple(interfaces)

    def product_string(self, handle, index: int) -> Optional[str]:
        if not index:
            return None
        buffer = ctypes.create_string_buffer(256)
        length = self.lib.libusb_get_string_descriptor_ascii(
            handle, index, buffer, len(buffer)
        )
        if length <= 0:
            return None
        return buffer.value.decode("utf-8", "replace")


def _enumerate(vendor_id: Optional[int] = 0x04B8) -> List[dict]:
    """Enumerate matching devices into plain dicts (used by :meth:`find`)."""
    libusb = _Libusb.get()
    out = []
    with libusb.device_list() as entries:
        for device, descriptor in entries:
            if vendor_id is not None and descriptor.idVendor != vendor_id:
                continue
            bus = int(libusb.lib.libusb_get_bus_number(device))
            address = int(libusb.lib.libusb_get_device_address(device))
            config_ptr = libusb.config_of(device)
            interfaces: Tuple[InterfaceDescriptor, ...] = ()
            configuration_value = None
            if config_ptr:
                try:
                    configuration_value = int(config_ptr.contents.bConfigurationValue)
                    interfaces = libusb.interfaces_of(config_ptr)
                finally:
                    libusb.lib.libusb_free_config_descriptor(config_ptr)
            out.append(
                {
                    "bus": bus,
                    "address": address,
                    "path": "%d:%d" % (bus, address),
                    "vendor_id": descriptor.idVendor,
                    "product_id": descriptor.idProduct,
                    "iProduct": descriptor.iProduct,
                    "iSerialNumber": descriptor.iSerialNumber,
                    "bcdDevice": descriptor.bcdDevice,
                    "interfaces": interfaces,
                    "configuration_value": configuration_value,
                }
            )
    return out


class LibusbTransport(Transport):
    """D4 transport over a claimed vendor-specific interface via ``libusb``."""

    name = "libusb"

    def __init__(
        self,
        path: Optional[str] = None,
        info: Optional[DeviceInfo] = None,
        interface: Optional[int] = None,
        endpoint_in: Optional[int] = None,
        endpoint_out: Optional[int] = None,
        configuration: Optional[int] = None,
        detach_kernel_driver: bool = True,
        read_chunk: int = 4096,
    ) -> None:
        super().__init__()
        self.path = path
        self._info = info or DeviceInfo(backend=self.name, path=path or "")
        self.interface_override = interface
        self.endpoint_in_override = endpoint_in
        self.endpoint_out_override = endpoint_out
        self.configuration_override = configuration
        self.detach_kernel_driver = detach_kernel_driver
        self.read_chunk = read_chunk
        self._handle = None
        self._interface = None
        self._detached = False
        self._bulk_in = None
        self._bulk_out = None

    # -- discovery ---------------------------------------------------------
    @classmethod
    def available(cls) -> bool:
        try:
            _Libusb.get()
        except Exception:
            return False
        return True

    @classmethod
    def find(cls, vendor_id: Optional[int] = EPSON_VID, **_kwargs) -> List[DeviceInfo]:
        out = []
        for record in _enumerate(vendor_id):
            selected = select_interface_and_endpoints(record["interfaces"])
            interface_number = endpoint_in = endpoint_out = None
            if selected:
                selected_interface, bulk_in, bulk_out = selected
                interface_number = selected_interface.number
                endpoint_in = bulk_in.address
                endpoint_out = bulk_out.address
            out.append(
                DeviceInfo(
                    backend=cls.name,
                    path=record["path"],
                    vendor_id=record["vendor_id"],
                    product_id=record["product_id"],
                    interface=interface_number,
                    endpoint_in=endpoint_in,
                    endpoint_out=endpoint_out,
                    description="libusb device %s (%d interfaces)"
                    % (record["path"], len(record["interfaces"])),
                    extra={
                        "bus": record["bus"],
                        "address": record["address"],
                        "configuration_value": record["configuration_value"],
                        "interfaces": [
                            {
                                "number": i.number,
                                "class": i.interface_class,
                                "subclass": i.interface_subclass,
                                "protocol": i.interface_protocol,
                                "endpoints": [
                                    {
                                        "address": e.address,
                                        "attributes": e.attributes,
                                        "max_packet_size": e.max_packet_size,
                                    }
                                    for e in i.endpoints
                                ],
                            }
                            for i in record["interfaces"]
                        ],
                    },
                )
            )
        return out

    # -- lifecycle ---------------------------------------------------------
    def _find_handle(self):
        """Re-enumerate, open the device matching :attr:`path`, and copy what we need.

        Everything involving the enumerated device happens inside the
        ``device_list`` context: the handle returned by ``libusb_open`` has its
        own reference, and the interface and endpoint descriptors are copied
        into plain Python objects, so nothing outside depends on the freed
        list.
        """
        libusb = _Libusb.get()
        with libusb.device_list() as entries:
            found = None
            for device, descriptor in entries:
                bus = int(libusb.lib.libusb_get_bus_number(device))
                address = int(libusb.lib.libusb_get_device_address(device))
                candidate_path = "%d:%d" % (bus, address)
                if self.path and candidate_path != self.path:
                    continue
                if self._info.vendor_id and descriptor.idVendor != self._info.vendor_id:
                    continue
                if self._info.product_id and descriptor.idProduct != self._info.product_id:
                    continue
                found = (device, descriptor, candidate_path)
                break
            if found is None:
                raise DeviceNotFoundError(
                    "no libusb device matches %r%s"
                    % (
                        self.path or "vendor 0x%04x" % (self._info.vendor_id or 0,),
                        "" if self.path else "; pass a device path such as '1:4'",
                    )
                )
            device, _descriptor, candidate_path = found

            # Resolve the interface and its two bulk endpoints, honouring
            # explicit overrides.
            config_ptr = libusb.config_of(device)
            if config_ptr is None:
                raise TransportError(
                    "could not read the configuration descriptor of device %s"
                    % candidate_path
                )
            try:
                configuration_value = int(config_ptr.contents.bConfigurationValue)
                interfaces = libusb.interfaces_of(config_ptr)
            finally:
                libusb.lib.libusb_free_config_descriptor(config_ptr)

            if self.interface_override is not None:
                interface = next(
                    (i for i in interfaces if i.number == self.interface_override), None
                )
                if interface is None:
                    raise DeviceNotFoundError(
                        "device %s has no interface %d"
                        % (candidate_path, self.interface_override)
                    )
                bulk_in = next(
                    (
                        endpoint
                        for endpoint in interface.endpoints
                        if endpoint.is_bulk and endpoint.is_in
                        and (self.endpoint_in_override is None
                             or endpoint.address == self.endpoint_in_override)
                    ),
                    None,
                )
                bulk_out = next(
                    (
                        endpoint
                        for endpoint in interface.endpoints
                        if endpoint.is_bulk and not endpoint.is_in
                        and (self.endpoint_out_override is None
                             or endpoint.address == self.endpoint_out_override)
                    ),
                    None,
                )
            else:
                selected = select_interface_and_endpoints(interfaces)
                if selected is None:
                    raise DeviceNotFoundError(
                        "device %s exposes no interface with bulk endpoints"
                        % candidate_path
                    )
                interface, bulk_in, bulk_out = selected
            if bulk_in is None or bulk_out is None:
                raise DeviceNotFoundError(
                    "device %s interface %d has no usable bulk endpoints"
                    % (candidate_path, interface.number)
                )

            handle = ctypes.c_void_p()
            result = libusb.lib.libusb_open(device, ctypes.byref(handle))
            if result != LIBUSB_SUCCESS:
                libusb.raise_for(result, "libusb_open(%s)" % candidate_path)
            return libusb, handle, interface, bulk_in, bulk_out, configuration_value

    def open(self) -> None:
        if self._opened:
            return
        libusb, handle, interface, bulk_in, bulk_out, configuration_value = (
            self._find_handle()
        )
        try:
            if libusb.auto_detach is not None:
                libusb.auto_detach(handle, 1)
            target_configuration = (
                self.configuration_override
                if self.configuration_override is not None
                else configuration_value
            )
            if target_configuration:
                result = libusb.lib.libusb_set_configuration(handle, target_configuration)
                if result not in (LIBUSB_SUCCESS, LIBUSB_ERROR_NOT_FOUND_OTHER):
                    if result != LIBUSB_ERROR_BUSY:
                        libusb.raise_for(result, "libusb_set_configuration")

            if self.detach_kernel_driver:
                active = libusb.lib.libusb_kernel_driver_active(handle, interface.number)
                if active == 1:
                    result = libusb.lib.libusb_detach_kernel_driver(
                        handle, interface.number
                    )
                    if result == LIBUSB_SUCCESS:
                        self._detached = True
                    elif result != LIBUSB_ERROR_NOT_FOUND:
                        libusb.raise_for(
                            result,
                            "libusb_detach_kernel_driver(if %d)" % interface.number,
                        )

            result = libusb.lib.libusb_claim_interface(handle, interface.number)
            if result != LIBUSB_SUCCESS:
                libusb.raise_for(
                    result, "libusb_claim_interface(if %d)" % interface.number
                )
        except Exception:
            try:
                libusb.lib.libusb_close(handle)
            except Exception:
                pass
            raise
        self._handle = handle
        self._interface = interface.number
        self._bulk_in = bulk_in
        self._bulk_out = bulk_out
        self._opened = True
        self._info = DeviceInfo(
            backend=self.name,
            path=self.path or self._info.path,
            vendor_id=self._info.vendor_id,
            product_id=self._info.product_id,
            interface=interface.number,
            endpoint_in=bulk_in.address,
            endpoint_out=bulk_out.address,
            description=self._info.description,
            extra=self._info.extra,
        )

    def close(self) -> None:
        libusb = None
        try:
            libusb = _Libusb.get()
        except Exception:
            pass
        handle, self._handle = self._handle, None
        if handle and libusb is not None:
            try:
                if self._interface is not None:
                    libusb.lib.libusb_release_interface(handle, self._interface)
                if self._detached and self._interface is not None:
                    libusb.lib.libusb_attach_kernel_driver(handle, self._interface)
            except Exception:
                pass
            try:
                libusb.lib.libusb_close(handle)
            except Exception:
                pass
        self._detached = False
        self._interface = None
        self._opened = False

    # -- I/O ---------------------------------------------------------------
    def _bulk(self, endpoint: int, buffer, length: int, timeout_ms: int) -> int:
        """Raw bulk transfer; returns the number of bytes transferred."""
        libusb = _Libusb.get()
        transferred = ctypes.c_int(0)
        result = libusb.lib.libusb_bulk_transfer(
            self._handle,
            endpoint,
            ctypes.cast(buffer, ctypes.c_void_p),
            length,
            ctypes.byref(transferred),
            int(timeout_ms),
        )
        if result == LIBUSB_ERROR_TIMEOUT:
            return 0
        if result == LIBUSB_ERROR_PIPE:
            # A stalled endpoint: clear it and let the caller retry once.
            libusb.lib.libusb_clear_halt(self._handle, endpoint)
            raise TransportError(
                "endpoint 0x%02x stalled (halt cleared; retry)" % endpoint
            )
        if result != LIBUSB_SUCCESS:
            libusb.raise_for(result, "libusb_bulk_transfer(0x%02x)" % endpoint)
        return int(transferred.value)

    def write(self, data: bytes, timeout_ms: int = 3000) -> int:
        if self._handle is None:
            raise TransportError("transport is not open")
        buffer = ctypes.create_string_buffer(bytes(data), len(data))
        try:
            return self._bulk(self._bulk_out.address, buffer, len(data), timeout_ms)
        except TransportError:
            # One retry after a stall, which is a normal USB event.
            return self._bulk(self._bulk_out.address, buffer, len(data), timeout_ms)

    def read(self, maxlen: int = 1024, timeout_ms: int = 2000) -> bytes:
        if self._handle is None:
            raise TransportError("transport is not open")
        length = max(1, min(int(maxlen), self.read_chunk))
        buffer = ctypes.create_string_buffer(length)
        received = self._bulk(self._bulk_in.address, buffer, length, timeout_ms)
        return buffer.raw[:received] if received else b""

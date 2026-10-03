r"""Give ``EpsonPrinter`` a USB transport by subclassing it, not by patching it.

``epson_print_conf`` reaches the printer through exactly one door::

    printer.fetch_oid_values(oid)      # SNMP GET of an OID

Every feature it has -- EEPROM read and write, the ``st``/``di``/``vi``/``rw``
service commands, waste ink levels, the temporary waste reset, the full status
decode -- is built on top of that one call, with the OID produced by
``EpsonPrinter.epctrl_snmp_oid``. The message carried inside the OID is
*already* the EPSON-CTRL frame that the USB link has to carry: SNMP is only the
envelope.

The subclass overrides that single method and parses the OID back into bytes:

.. code-block:: python

    from epson_usb_bridge import usb_printer
    from epson_print_conf import EpsonPrinter

    UsbEpsonPrinter = usb_printer(EpsonPrinter)          # subclass

    printer = UsbEpsonPrinter(model="XP-205")            # no hostname: USB
    print(printer.read_eeprom(0x30))                     # '3B'
    print(printer.get_waste_ink_levels())                # {'main_waste': 6.11, ...}

Two hooks, and no data
----------------------

This module deliberately carries **no printer model data**. The host already has
its own ``PRINTER_CONFIG`` and it is the authoritative source for the printer in
use, so the normal path needs nothing from here: the keys are inside the OIDs
the host builds. The two hooks exist for the cases where a caller knows
something the host does not:

``params=``
    A mapping ``{model name: host parm dict}``. It is handed to the host as
    ``conf_dict``, so a model the host has never heard of can still be used.
    Where those parameters come from is entirely the caller's business; entries
    the host already has with a usable ``read_key`` are never replaced, because
    disagreeing with the host about the printer in use is how you write to the
    wrong cells.

``usb_factory=``
    A callable that builds the underlying
    :class:`~epson_usb.printer.EpsonUsbPrinter`. A caller that keeps its own
    EEPROM keys uses it to have ``printer.usb`` be a keyed object, so that the
    extras built on top of it (reading a cell, writing a cell set) work on the
    *same* open device instead of a second one.

Choosing the USB interface
--------------------------

A printer exposes several USB interfaces and only one of them answers D4, but
which one is not something the descriptors say reliably: the L3250 measured for
issue #35 has a vendor-specific interface 0 that never answers and interface 1
that works, while the library's automatic choice prefers vendor-specific
interfaces. The default factory here is therefore
:class:`InterfaceTryingUsbPrinter`: when the handshake fails on the first
choice, it asks the backends which interfaces the device has and tries them
(:data:`PREFERRED_USB_INTERFACES` first), so the printer is reached without
having to name the interface. ``interfaces=[...]`` gives the order; ``[]`` keeps
the library's choice and nothing else.

What cannot work over USB, and says so instead of pretending:

* plain MIB OIDs (``get_snmp_info``) -- there is no SNMP agent on a USB cable,
  so those queries answer "unavailable" and are logged;
* printing (``print_check_nozzles``, ``print_clean_nozzles``, ...) -- the host
  sends those through LPR to a network address (see the GUI: the buttons are
  disabled in USB mode with that reason);
* ``brute_force_read_key`` on a locked firmware: the EEPROM stays locked over
  USB only when the *firmware* locks it, in which case the ``rw`` service
  command (``temporary_reset_waste``) is the one that still works, because it
  needs only the serial number.
"""

from __future__ import annotations

import inspect
import logging
from typing import Callable, Mapping, Optional, Sequence, Type

from epson_usb.errors import TransportError
from epson_usb.printer import EpsonUsbPrinter

__all__ = [
    "usb_printer",
    "UsbEpsonPrinterMixin",
    "InterfaceTryingUsbPrinter",
    "upstream_knows_model",
    "factory_kwargs",
    "backend_accepts_interface",
    "device_interfaces",
    "PREFERRED_USB_INTERFACES",
]

log = logging.getLogger(__name__)


def upstream_knows_model(base, *names) -> bool:
    """Has the host usable parameters for this model already?

    "Usable" means the entry exists *and* carries a ``read_key`` -- an entry
    without one cannot reach the EEPROM, so a caller's own tables are then the
    only option rather than a replacement. This is the question a caller asks
    when deciding whether its own parameters are needed at all.
    """
    config = getattr(base, "PRINTER_CONFIG", None) or {}
    for name in names:
        if not name:
            continue
        entry = config.get(name)
        if isinstance(entry, dict) and "read_key" in entry:
            return True
    return False


def factory_kwargs(factory: Callable, available: Mapping[str, object],
                   host_identity: Sequence[str] = ("model", "printer")) -> dict:
    """The subset of ``available`` that ``factory`` is willing to receive.

    A factory is the caller's way of building the USB object with its own keys,
    so it may want to know *which model* it is serving -- something the default
    :class:`~epson_usb.printer.EpsonUsbPrinter` has no parameter for. Rather
    than passing everything (which would break on the first named parameter a
    factory does not declare) or nothing (which would make the hook useless),
    the factory receives the arguments it declares, plus -- when it takes
    ``**kwargs`` -- any other *transport* option the caller supplied (that is how
    ``usb_options={"config": ...}`` reaches a backend).

    ``host_identity`` names the arguments that are **not** transport options.
    They are passed only to a factory that declares them by name, because the
    default factory forwards unrecognised keywords to the transport: handing it
    ``model=`` sends that keyword all the way to the backend constructor and
    breaks device discovery ("__init__() got an unexpected keyword argument
    'model'") for every caller that does not pass a ready-made ``transport``.
    """
    try:
        parameters = inspect.signature(factory).parameters
    except (TypeError, ValueError):  # pragma: no cover - exotic callables
        return dict(available)
    accepts_kwargs = any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()
    )
    out = {}
    for name, value in available.items():
        if name in parameters:
            out[name] = value
        elif accepts_kwargs and name not in host_identity:
            out[name] = value
    return out


#: Interface numbers tried first when the printer has to fall back to another
#: one of its USB interfaces (see :class:`InterfaceTryingUsbPrinter`).
#: Interface 1 is what answered D4 on the printer measured for issue #35: an
#: L3250 whose vendor-specific interface 0 never answered the handshake while
#: interface 1 negotiated D4 revision 0x10. The library prefers vendor-specific
#: interfaces, so the preference is applied here, after a failure.
PREFERRED_USB_INTERFACES = (1,)


def backend_accepts_interface(backend: Optional[str]) -> bool:
    """Does this backend's transport take an ``interface=`` number?

    The library lets a caller pin the USB interface on the transports that
    claim one directly (``libusb`` and ``pyusb``). The Windows ``USBPRINT``
    transport instead receives the interface *inside* the device path, so it
    has no such argument and must not be given one.
    """
    if not backend:
        return False
    try:
        from epson_usb.backends import backend_class

        parameters = inspect.signature(backend_class(backend).__init__).parameters
    except Exception:
        return False
    return "interface" in parameters


def device_interfaces(device=None, backend=None, instance_id=None):
    """``(backend, [interface numbers])`` of the device that would be opened.

    The numbers come from the enumeration the library already performs
    (``DeviceInfo.extra['interfaces']``), so this asks a question about a
    device that has just refused to answer, without probing anything new. It
    is only ever called after a D4 failure. Backends that do not report
    interfaces -- the Windows ``USBPRINT`` paths already name the interface,
    PyUSB reports one device -- answer with an empty list, and the caller then
    keeps the library's own choice.
    """
    try:
        from epson_usb.backends import find_devices

        devices = find_devices(
            backends=[backend] if backend else None, instance_id=instance_id
        )
    except Exception:
        return None, []
    for info in devices:
        if device is None or info.path == device:
            numbers = [
                int(entry["number"])
                for entry in (info.extra or {}).get("interfaces", ())
                if isinstance(entry, dict) and entry.get("number") is not None
            ]
            return info.backend, numbers
    return (backend, []) if device is not None else (None, [])


class InterfaceTryingUsbPrinter(EpsonUsbPrinter):
    """An :class:`EpsonUsbPrinter` that tries one USB interface after another.

    A printer exposes several USB interfaces and only one of them answers D4,
    but the descriptors do not say which one reliably: the L3250 measured for
    issue #35 has a vendor-specific interface 0 that never answers and an
    interface 1 that works, while the library's automatic choice prefers
    vendor-specific interfaces. When the handshake on the first choice fails,
    this object asks the backends which interfaces the device has and tries
    them all, :data:`PREFERRED_USB_INTERFACES` first.

    ``interfaces`` controls the behaviour:

    * ``None`` (the default) -- the library's own choice, then the alternatives
      as described above, with nothing to pass;
    * a non-empty sequence -- these interface numbers first, in the order
      given, then the remaining ones (same preference);
    * ``[]`` -- no fallback at all: exactly the library's own choice.

    ``interface=N`` (the library's own transport option) is accepted too and
    promoted to a one-element list, so the alternatives are still tried after
    it.
    """

    def __init__(self, *args, interfaces=None, interface=None, **kwargs) -> None:
        if interface is not None:
            interfaces = (
                [interface] if interfaces is None else [interface, *interfaces]
            )
        #: ``None`` = library choice plus fallback; ``[]`` = library choice only;
        #: a list = these first, then the remaining ones.
        self._interface_order = (
            None if interfaces is None else [int(number) for number in interfaces]
        )
        #: The interface that answered last time, tried first by a later open
        #: (the key scan closes and re-opens the session on purpose).
        self._working_interface = None
        # ``interface`` is deliberately not forwarded: it becomes a list entry,
        # so that it never reaches a transport that does not declare it.
        super().__init__(*args, **kwargs)

    def _fallback_order(self):
        """Interface numbers to try, in order (empty when there are none)."""
        if self._interface_order == []:
            return []
        order = list(self._interface_order or [])
        backend, numbers = device_interfaces(
            self._device, self._backend, self._instance_id
        )
        backend = backend or self._backend
        if not backend_accepts_interface(backend):
            # A transport that does not take ``interface=`` names the interface
            # in its device path instead (Windows USBPRINT), or has no notion of
            # interfaces at all. Asking for a number there cannot work, so the
            # request is dropped rather than turned into a failed open.
            if order:
                log.warning(
                    "The %s backend cannot be told which USB interface to use"
                    " (its device path already names one, or it exposes none):"
                    " --interface %s ignored",
                    backend or "current", ",".join(str(n) for n in order),
                )
            return []
        if not numbers:
            return order
        if self._backend is None and backend:
            # ``interface=`` reaches a transport of one backend only, and this
            # is the backend the enumeration saw the interfaces through.
            self._backend = backend
        remaining = sorted(
            numbers,
            key=lambda number: (
                number not in PREFERRED_USB_INTERFACES, number
            ),
        )
        order.extend(number for number in remaining if number not in order)
        return order

    def open(self):
        """Open the device, trying the alternative interfaces on failure."""
        if self.session is not None and self.session.connected:
            return self
        order = self._fallback_order()
        attempts = ([None] if self._interface_order is None else []) + order
        if not attempts:
            return super().open()
        if self._working_interface is not None:
            # An interface already answered: try it first, so re-opening the
            # session does not repeat the attempts that failed.
            attempts = [self._working_interface] + [
                number for number in attempts
                if number != self._working_interface
            ]
        errors = []
        for number in attempts:
            if number is None:
                self._transport_kwargs.pop("interface", None)
            else:
                self._transport_kwargs["interface"] = number
            try:
                printer = super().open()
            except Exception as exc:
                errors.append(
                    "%s: %s"
                    % (
                        "the interface chosen by the library"
                        if number is None else "interface %s" % number,
                        exc,
                    )
                )
                self.close()
                continue
            self._working_interface = number
            if errors:
                # Say which interface was the one that worked: the handshake on
                # the others failed for a reason the user may want to know.
                log.warning(
                    "USB: D4 answered on interface %s; the earlier attempt(s)"
                    " failed (%s). To select it directly: --interface %s.",
                    number, "; ".join(errors), number,
                )
            return printer
        raise TransportError("no USB interface answered D4: %s" % "; ".join(errors))


class UsbEpsonPrinterMixin:
    """Gives an ``EpsonPrinter`` subclass a USB transport instead of SNMP.

    Only :meth:`fetch_oid_values` is overridden. Everything the host calls above
    it -- including the EEPROM write path, which builds the write frame *and*
    its key obfuscation in the host -- therefore runs the host's own code.
    """

    #: ``{model name: host parm dict}``, supplied by the caller. ``None`` means
    #: "the host's own configuration is all there is", which is the normal,
    #: data-free case.
    usb_params: Optional[Mapping[str, dict]] = None

    #: Builds the :class:`~epson_usb.printer.EpsonUsbPrinter` used for the USB
    #: link. Override (or pass ``usb_factory=``) to create an object that holds
    #: keys: see the module docstring. The default tries the printer's other
    #: USB interfaces when D4 does not answer on the first choice; pass
    #: ``interfaces=`` (or ``usb_options={'interfaces': ...}``) to order them.
    usb_factory: Callable[..., EpsonUsbPrinter] = InterfaceTryingUsbPrinter

    #: The USB side of the printer.
    usb: EpsonUsbPrinter

    def __init__(
        self,
        *args,
        usb_printer: Optional[EpsonUsbPrinter] = None,
        usb_model: Optional[str] = None,
        usb_params: Optional[Mapping[str, dict]] = None,
        usb_factory: Optional[Callable[..., EpsonUsbPrinter]] = None,
        usb_options: Optional[Mapping[str, object]] = None,
        device=None,
        backend: Optional[str] = None,
        instance_id: Optional[str] = None,
        interfaces=None,
        transport=None,
        usb_timeouts=None,
        **kwargs,
    ) -> None:
        #: The model name the caller asked for (the host's own ``model``, or the
        #: ``usb_model`` spelling for callers that keep the two apart).
        self.usb_model = kwargs.get("model") or usb_model
        # Hand the caller's parameters to the host, if any. `setdefault` is
        # deliberate: an entry the host already has stays authoritative. The
        # requested name and every alias the caller registered are tried, so it
        # does not matter which spelling the caller used -- the host's own
        # `self.parm = PRINTER_CONFIG[self.model]` will find the entry.
        params = usb_params if usb_params is not None else type(self).usb_params
        if params:
            model_name = self.usb_model
            if model_name:
                conf_dict = dict(kwargs.get("conf_dict") or {})
                entry = params.get(model_name)
                if entry is not None:
                    conf_dict.setdefault(model_name, entry)
                    kwargs["conf_dict"] = conf_dict
                    log.debug("parameters for %s taken from the caller's tables",
                              model_name)
                else:
                    log.info(
                        "no caller-supplied parameters for %r; the host's own "
                        "configuration will be used", model_name,
                    )
        # hostname is deliberately left as the caller gave it (usually None):
        # the USB override never uses it, and `get_snmp_info` failing loudly is
        # more honest than silently using a wrong address.
        super().__init__(*args, **kwargs)
        factory = usb_factory or type(self).usb_factory
        if usb_printer is not None:
            self.usb = usb_printer
            return
        self.usb = factory(
            **factory_kwargs(
                factory,
                {
                    "device": device,
                    "backend": backend,
                    "instance_id": instance_id,
                    "transport": transport,
                    "timeouts": usb_timeouts,
                    "dry_run": getattr(self, "dry_run", False),
                    # Lazy, not at construction: the host builds printer objects
                    # for reasons that have nothing to do with the hardware --
                    # ui.py constructs one just to list the models in a
                    # dropdown. Opening a USB device there would be both wrong
                    # and fatal, so the device is touched on the first command.
                    "auto_open": False,
                    "lazy_open": True,
                    # Which printer this is, for a factory that keeps its own
                    # keys; and the host object itself, for one that needs it.
                    "model": self.usb_model,
                    "printer": self,
                    # Whatever else the caller needs to reach the device, such
                    # as {"config": MockConfig(...)} for the fake printer.
                    **(dict(usb_options) if usb_options else {}),
                    # The USB interfaces to try, in order. Only passed when the
                    # caller picked an order: the default factory falls back to
                    # the alternatives on its own, and a custom factory has no
                    # reason to receive this.
                    **(
                        {"interfaces": interfaces}
                        if interfaces is not None else {}
                    ),
                },
            )
        )

    # -- the one door ------------------------------------------------------
    def fetch_oid_values(self, oid, label: str = "unknown"):
        """Answer an OID over USB (was: SNMP GET).

        Same return contract as the host: a list of ``(type_name, value)``,
        ``[(None, False)]`` when the OID is not an EPSON-CTRL message or the
        printer answered nothing usable.

        Connection failures are the one exception, and they follow the host
        rather than swallowing the error: when the printer cannot be reached at
        all -- no device, handshake refused, cable unplugged -- the host raises
        ``TimeoutError`` (its ``RequestTimedOut``), so this does too, with the
        USB detail in the message and the original exception as ``__cause__``.
        A user then learns that the printer is missing instead of seeing every
        value silently become ``None``. The library's own API
        (:class:`~epson_usb.printer.EpsonUsbPrinter`) keeps the typed errors.
        """
        if getattr(self, "mib_dict", None):
            # Config-file replay mode: the host answers from the recorded
            # dictionary, which has nothing to do with USB.
            return super().fetch_oid_values(oid, label=label)
        try:
            return self.usb.fetch_oid_values(oid, label=label)
        except TransportError as exc:
            raise TimeoutError("USB: %s" % exc) from exc
        except Exception as exc:  # pragma: no cover - defensive
            log.error("USB request failed (%s): %s", label, exc)
            return [(None, False)]

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        """Release the USB device (the host has no such method; harmless)."""
        try:
            self.usb.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def usb_describe(self) -> str:
        return self.usb.describe()

    # -- things USB cannot do ---------------------------------------------
    def _needs_network(self, what: str):
        raise NotImplementedError(
            "%s sends data through LPR to a network address, which the USB "
            "transport does not implement. Use the SNMP/LPR path, or print "
            "through the operating system's printer queue." % what
        )

    def print_check_nozzles(self, *args, **kwargs):  # pragma: no cover
        self._needs_network("print_check_nozzles")

    def print_test_color_pattern(self, *args, **kwargs):  # pragma: no cover
        self._needs_network("print_test_color_pattern")

    def print_clean_nozzles(self, *args, **kwargs):  # pragma: no cover
        self._needs_network("print_clean_nozzles")


def usb_printer(base=None, name: Optional[str] = None,
                params: Optional[Mapping[str, dict]] = None,
                factory: Optional[Callable[..., EpsonUsbPrinter]] = None,
                **class_kwargs) -> Type:
    """Build (and return) an ``EpsonPrinter`` subclass whose transport is USB.

    ::

        UsbEpsonPrinter = usb_printer(EpsonPrinter)      # the host class

    ``base`` is required: this module is reached *from* the host program, so the
    class to extend is always at hand. Passing no class is an error rather than
    an invitation to go looking for one by module name.

    ``params`` and ``factory`` are the two hooks described in the module
    docstring; both are optional and neither carries data of its own.

    The result is an ordinary class: it can be subclassed again, instantiated
    many times, and its instances are ``isinstance(..., EpsonPrinter)``, so code
    that type-checks or calls host methods keeps working.
    """
    if base is None:
        raise TypeError(
            "usb_printer() needs the class to extend: usb_printer(EpsonPrinter)"
        )
    namespace_name = name or ("Usb" + base.__name__)
    namespace = {
        "__module__": __name__,
        "__doc__": UsbEpsonPrinterMixin.__doc__,
    }
    if params is not None:
        namespace["usb_params"] = params
    if factory is not None:
        namespace["usb_factory"] = staticmethod(factory)
    namespace.update(class_kwargs)
    return type(namespace_name, (UsbEpsonPrinterMixin, base), namespace)

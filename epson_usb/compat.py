r"""Make ``epson_print_conf`` work over USB, without forking it.

``epson_print_conf`` reaches the printer through exactly one door::

    printer.fetch_oid_values(oid)      # SNMP GET of an OID

Every feature it has -- EEPROM read and write, the ``st``/``di``/``vi``/``rw``
service commands, waste ink levels, the temporary waste reset, the full status
decode -- is built on top of that one call, with the OID produced by
``EpsonPrinter.epctrl_snmp_oid``. The message carried inside the OID is
*already* the EPSON-CTRL frame that the USB link has to carry: SNMP is only the
envelope.

So the whole integration is a subclass that overrides that single method and
parses the OID back into bytes:

.. code-block:: python

    from epson_usb.compat import usb_printer
    from epson_print_conf import EpsonPrinter

    UsbEpsonPrinter = usb_printer(EpsonPrinter)          # subclass, not a copy

    printer = UsbEpsonPrinter(model="L3251")             # no hostname: USB
    print(printer.read_eeprom(0x30))                     # '18'
    print(printer.get_waste_ink_levels())                # {'main_waste': 97.68, ...}
    printer.reset_waste_ink_levels()                     # writes the full cell set

Nothing else in the upstream class is touched: the EEPROM address tables, the
status decoder, the waste-level arithmetic, the service commands and every
call site above them keep running upstream's own code. That is what
"1:1 usable" means here, and ``tests/test_epson_usb.py`` measures it -- both
transports are driven against the same fake printer and their byte streams and
results are compared (``TransportParityTests``). The same file's
``OidBridgeTests`` covers the OID side of the bridge, and
``tests/test_fidelity.py`` covers the port's byte-level fidelity.

Two hooks, and no data
----------------------

This module deliberately carries **no printer model data**. Upstream already
has its own ``PRINTER_CONFIG`` and it is the authoritative source for the
printer in use, so the normal path needs nothing from here: the keys are inside
the OIDs upstream builds. The two hooks exist for the cases where a caller
knows something upstream does not:

``params=``
    A mapping ``{model name: upstream parm dict}``. It is handed to upstream as
    ``conf_dict``, so a model that upstream has never heard of can still be
    used. Where those parameters come from, and how they are transformed into
    upstream's format, is entirely the caller's business (:mod:`epson_l3250`
    in this repository does it for the L3250 family); entries upstream already
    has with a usable ``read_key`` are never replaced, because disagreeing with
    the host about the printer in use is how you write to the wrong cells.

``usb_factory=``
    A callable that builds the underlying
    :class:`~epson_usb.printer.EpsonUsbPrinter`. A caller that keeps its own
    EEPROM keys -- again :mod:`epson_l3250` -- uses it to have ``printer.usb``
    be a keyed object, so that the extras built on top of it (reading a cell,
    writing a cell set) work on the *same* open device instead of a second one.

What cannot work over USB, and says so instead of pretending:

* plain MIB OIDs (``get_snmp_info``) -- there is no SNMP agent on a USB cable,
  so those queries answer "unavailable" and are logged;
* printing (``print_check_nozzles``, ``print_clean_nozzles``, ...) -- upstream
  sends those through LPR to a network address;
* ``brute_force_read_key`` on a locked firmware: the EEPROM stays locked over
  USB only when the *firmware* locks it (the L3250 case), in which case the
  ``rw`` service command (``temporary_reset_waste``) is the one that still
  works, because it needs only the serial number.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import os
import sys
from typing import Callable, Mapping, Optional, Sequence, Type

from .errors import TransportError
from .printer import EpsonUsbPrinter

__all__ = [
    "load_epson_print_conf",
    "usb_printer",
    "patch_epson_print_conf",
    "UsbEpsonPrinterMixin",
    "upstream_knows_model",
    "factory_kwargs",
]

log = logging.getLogger(__name__)

_PRINTING_METHODS = (
    "print_check_nozzles",
    "print_test_color_pattern",
    "print_clean_nozzles",
)


def load_epson_print_conf(module_name: str = "epson_print_conf",
                          extra_paths: Sequence[str] = ()):
    """Import ``module_name`` (by default ``epson_print_conf``).

    Tried in order: the normal import, ``EPSON_PRINT_CONF_PATH``, this
    repository's own root, a sibling ``../epson_print_conf`` directory, and
    each of ``extra_paths``. ``module_name`` is honoured everywhere, so a
    vendored copy under another name works too. Raises :class:`ImportError`
    when it cannot be found, with a message that says how to install it.
    """
    try:
        return importlib.import_module(module_name)
    except Exception:
        pass

    here = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    env = os.environ.get("EPSON_PRINT_CONF_PATH")
    if env:
        candidates.append(env)
    candidates.append(os.path.dirname(here))
    candidates.append(os.path.join(os.path.dirname(here), "..", module_name))
    candidates.extend(extra_paths)
    for candidate in candidates:
        if not candidate:
            continue
        candidate = os.path.abspath(candidate)
        if os.path.isfile(os.path.join(candidate, module_name + ".py")):
            if candidate not in sys.path:
                sys.path.insert(0, candidate)
            return importlib.import_module(module_name)
    raise ImportError(
        "epson_print_conf is not installed. Get it with: "
        "git clone https://github.com/Ircama/epson_print_conf && "
        "pip install -r epson_print_conf/requirements.txt, then either install "
        "it (pip install ./epson_print_conf) or set EPSON_PRINT_CONF_PATH to "
        "the directory containing epson_print_conf.py."
    )


def upstream_knows_model(base, *names) -> bool:
    """Does ``epson_print_conf`` already have usable parameters for this model?

    "Usable" means the entry exists *and* carries a ``read_key`` -- an entry
    without one cannot reach the EEPROM, so a caller's own tables are then the
    only option rather than a replacement.

    This is exposed because it is the question a caller asks when deciding
    whether its own parameters are needed at all: see ``epson_print_conf_usb``
    in this repository.
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


class UsbEpsonPrinterMixin:
    """Gives an ``EpsonPrinter`` subclass a USB transport instead of SNMP.

    Only :meth:`fetch_oid_values` is overridden. Everything upstream calls
    above it -- including the EEPROM write path, which builds the write frame
    *and* its key obfuscation upstream -- therefore runs upstream's own code.
    """

    #: ``{model name: upstream parm dict}``, supplied by the caller. ``None``
    #: means "upstream's own configuration is all there is", which is the
    #: normal, data-free case.
    usb_params: Optional[Mapping[str, dict]] = None

    #: Builds the :class:`~epson_usb.printer.EpsonUsbPrinter` used for the USB
    #: link. Override (or pass ``usb_factory=``) to create an object that holds
    #: keys: see the module docstring.
    usb_factory: Callable[..., EpsonUsbPrinter] = EpsonUsbPrinter

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
        transport=None,
        usb_timeouts=None,
        **kwargs,
    ) -> None:
        #: The model name the caller asked for (upstream's own ``model``, or
        #: the ``usb_model`` spelling for callers that keep the two apart).
        self.usb_model = kwargs.get("model") or usb_model
        # Hand the caller's parameters to upstream, if any. `setdefault` is
        # deliberate: an entry upstream already has stays authoritative. The
        # requested name and every alias the caller registered are tried, so it
        # does not matter which spelling the caller used -- upstream's
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
                        "no caller-supplied parameters for %r; upstream's own "
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
                    # Lazy, not at construction: upstream builds printer objects
                    # for reasons that have nothing to do with the hardware --
                    # ui.py:475 constructs one just to list the models in a
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
                },
            )
        )

    # -- the one door ------------------------------------------------------
    def fetch_oid_values(self, oid, label: str = "unknown"):
        """Answer an OID over USB (was: SNMP GET).

        Same return contract as upstream: a list of ``(type_name, value)``,
        ``[(None, False)]`` when the OID is not an EPSON-CTRL message or the
        printer answered nothing usable.

        Connection failures are the one exception, and they follow upstream
        rather than swallowing the error: when the printer cannot be reached at
        all -- no device, handshake refused, cable unplugged -- upstream raises
        ``TimeoutError`` (its ``RequestTimedOut``), so this does too, with the
        USB detail in the message and the original exception as ``__cause__``.
        A user then learns that the printer is missing instead of seeing every
        value silently become ``None``. The library's own API
        (:class:`~epson_usb.printer.EpsonUsbPrinter`) keeps the typed errors.
        """
        if getattr(self, "mib_dict", None):
            # Config-file replay mode: upstream answers from the recorded
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
        """Release the USB device (upstream has no such method; harmless)."""
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
                module_name: str = "epson_print_conf",
                params: Optional[Mapping[str, dict]] = None,
                factory: Optional[Callable[..., EpsonUsbPrinter]] = None,
                **class_kwargs) -> Type:
    """Build (and return) an ``EpsonPrinter`` subclass whose transport is USB.

    ::

        UsbEpsonPrinter = usb_printer()                  # imports upstream itself
        UsbEpsonPrinter = usb_printer(EpsonPrinter)      # explicit base class

    ``params`` and ``factory`` are the two hooks described in the module
    docstring; both are optional and neither carries data of its own.

    The result is an ordinary class: it can be subclassed again, instantiated
    many times, and its instances are ``isinstance(..., EpsonPrinter)``, so
    code that type-checks or calls upstream methods keeps working.
    """
    if base is None:
        base = load_epson_print_conf(module_name).EpsonPrinter
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


def patch_epson_print_conf(module=None, params: Optional[Mapping[str, dict]] = None,
                           factory: Optional[Callable[..., EpsonUsbPrinter]] = None,
                           **class_kwargs) -> Type:
    """Replace ``epson_print_conf.EpsonPrinter`` with the USB-capable subclass.

    For tools that import the class themselves (``ui.py``,
    ``epson_print_conf.py``'s own CLI)::

        import epson_usb.compat
        epson_usb.compat.patch_epson_print_conf()   # before creating printers

    Returns the class that is now installed. The original is kept as
    ``module.NetworkEpsonPrinter`` so nothing is lost.
    """
    if module is None:
        module = load_epson_print_conf()
    original = getattr(module, "EpsonPrinter")
    if issubclass(original, UsbEpsonPrinterMixin):  # already patched
        return original
    patched = usb_printer(original, params=params, factory=factory, **class_kwargs)
    if not hasattr(module, "NetworkEpsonPrinter"):
        module.NetworkEpsonPrinter = original
    module.EpsonPrinter = patched
    return patched

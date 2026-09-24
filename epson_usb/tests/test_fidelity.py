#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Equivalence between this library and the frozen pre-refactor implementation.

This is the test that turns "the library looks like a faithful port" into a
measurement. It loads ``tests/referans/epson_l3251_usb_reset_referans.py`` -- the
tool exactly as it was before the protocol core moved into ``epson_usb``, i.e.
the code that was verified against a real L3251 -- and drives it through the
*same* in-memory printer as this library, by replacing only its two raw I/O
functions and its device handle.

What is compared:

1. the **byte stream** each implementation writes to the device (identical to
   the byte), which covers the D4 handshake, the credit dance, the EEPROM frames
   and the ``rw`` frame;
2. the **values** each implementation obtains from the same printer;
3. the **frame builders**, against the frozen tool's own, including the two
   frames quoted in the issue reports, byte for byte;
4. the **read-only gate**: neither implementation writes to the EEPROM unless it
   was asked to.

What is deliberately *not* compared here: the model tables (waste counters,
divisors, reset cells, mirrors). Those are model knowledge, this library carries
none of it (see the README), and the equivalence of a client's tables with the
frozen tool's literals is measured in the project where those tables live.

The keys and the cells below are therefore stated *by this test file*, which is
the point: the library is given them as parameters, the frozen tool carries its
own copy, and these tests assert the two agree.

No hardware, no network, no writes to a real printer.
"""

import ctypes
import importlib.util
import os
import sys
import types
import unittest
from unittest import mock


def _repo_root(start):
    """Walk up to the directory containing the ``epson_usb`` package."""
    directory = os.path.abspath(start)
    while True:
        if os.path.isfile(os.path.join(directory, "epson_usb", "__init__.py")):
            return directory
        parent = os.path.dirname(directory)
        if parent == directory:
            return os.path.abspath(start)
        directory = parent


HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = _repo_root(HERE)
REFERENCE = os.path.join(
    HERE, "referans", "epson_l3251_usb_reset_referans.py"
)
for path in (REPO_ROOT, HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

from epson_usb.backends.mock import (          # noqa: E402
    MOCK_SERIAL,
    MockConfig,
    MockPrinter,
    MockTransport,
)
from epson_usb.d4 import EpsonCtrlSession      # noqa: E402
from epson_usb.epson_ctrl import (             # noqa: E402
    eeprom_read_frame,
    eeprom_write_frame,
    rw_frame,
)

#: The L3250 family's keys, as the frozen tool holds them and as this test hands
#: them to the library (which has no model data of its own).
READ_KEY = (0x4A, 0x36)                        # (74, 54)
WRITE_KEY = bytes.fromhex("4e62736a63627a62")  # "Nbsjcbzb", the wire form
#: The two cells the issue report measured: 0x183B = 6203 little-endian.
CELL_30, CELL_31 = 0x3B, 0x18
READ_ADDR, WRITE_ADDR = 0x30, 0x1C


def _ensure_wintypes():
    """``ctypes.wintypes`` is a Windows-only module; the reference imports it.

    The reference guards the *loading* of its Win32 libraries with
    ``sys.platform`` (nothing is called on other platforms) but not that import,
    so a minimal stand-in is installed when it is missing. That makes the frozen
    tool loadable -- and this equivalence measurable -- everywhere, without
    touching the file: the reference is a frozen copy and is never edited.
    """
    try:
        import ctypes.wintypes  # noqa: F401
        return
    except ImportError:
        pass
    stub = types.ModuleType("ctypes.wintypes")
    for name in ("BOOL", "DWORD", "HANDLE", "HWND", "LPCVOID", "LPCWSTR",
                 "LPVOID", "LPWSTR"):
        setattr(stub, name, ctypes.c_void_p)
    sys.modules["ctypes.wintypes"] = stub
    ctypes.wintypes = stub


def load_reference():
    """Load the frozen reference implementation **by path**.

    By path, and with a private module name, so that the reference can never be
    picked up accidentally by production code or by an import of the current
    tool of the same name.
    """
    _ensure_wintypes()
    spec = importlib.util.spec_from_file_location(
        "epson_l3251_usb_reset_referans", REFERENCE
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


reference = load_reference()


def fake_printer():
    """The in-memory printer both implementations are driven against."""
    return MockPrinter(
        MockConfig(eeprom={READ_ADDR: CELL_30, READ_ADDR + 1: CELL_31,
                           WRITE_ADDR: 0x00})
    )


def run_reference_against(printer, address=READ_ADDR, serial=MOCK_SERIAL,
                          write_addr=WRITE_ADDR):
    """Drive the frozen implementation with ``printer`` as the device.

    Only four things are replaced: ``open_device`` (returns a dummy handle),
    ``write_all`` and ``read_some`` (the raw byte pipe), and ``time.sleep``
    inside the frozen module (the real handshake waits 0.2 s, which would only
    make the suite slow). The D4 code, the credit handshake, the EEPROM frames
    and the reply parsing all run unchanged -- that is the point.
    """

    def fake_open_device(path):
        return "FAKE-HANDLE"

    def fake_write_all(handle, data, timeout_ms=3000):
        printer.feed(bytes(data))
        return len(data)

    def fake_read_some(handle, maxlen=1024, timeout_ms=2000):
        return printer.read(maxlen)

    results = {}
    with mock.patch.object(reference, "open_device", fake_open_device), \
            mock.patch.object(reference, "write_all", fake_write_all), \
            mock.patch.object(reference, "read_some", fake_read_some), \
            mock.patch.object(reference, "kernel32",
                              types.SimpleNamespace(CloseHandle=lambda h: True),
                              create=True), \
            mock.patch.object(reference.time, "sleep", lambda *_: None):
        session = reference.D4Session("FAKE-PATH")
        session.connect()
        results["revision"] = session.rev
        results["read"] = session.read_eeprom(address)
        results["write"] = session.write_eeprom(write_addr, 0)
        results["readback"] = session.read_eeprom(write_addr)
        results["service"] = session.service_rw(serial)
        session.close()
    return results


def run_library_against(printer, address=READ_ADDR, serial=MOCK_SERIAL,
                        write_addr=WRITE_ADDR):
    """Drive the library with ``printer`` as the device (no patching needed)."""
    session = EpsonCtrlSession(
        MockTransport(printer=printer), read_key=READ_KEY, write_key=WRITE_KEY
    )
    try:
        revision = session.connect()
        return {
            "revision": revision,
            "read": session.read_eeprom(address),
            "write": session.write_eeprom(write_addr, 0),
            "readback": session.read_eeprom(write_addr),
            "service": session.service_rw(serial, mode=None),
        }
    finally:
        session.close()


class WireEquivalenceTests(unittest.TestCase):
    """The library must put the same bytes on the wire as the frozen tool."""

    def test_the_keys_the_test_hands_over_are_the_frozen_tools_keys(self):
        # The library is parameterised; the frozen tool carries literals. If
        # this fails, the equivalence below would be comparing two different
        # printers rather than two implementations.
        self.assertEqual(reference.RKEY, list(READ_KEY))
        self.assertEqual(bytes(reference.WKEY), WRITE_KEY)

    def test_full_session_byte_stream_is_identical(self):
        old_printer = fake_printer()
        new_printer = fake_printer()

        old = run_reference_against(old_printer)
        new = run_library_against(new_printer)

        self.assertEqual(
            bytes(old_printer.wire_log),
            bytes(new_printer.wire_log),
            "the library wrote a different byte stream than the frozen tool\n"
            "old: %s\nnew: %s" % (bytes(old_printer.wire_log).hex(" "),
                                  bytes(new_printer.wire_log).hex(" ")),
        )
        self.assertEqual(old, new, "the two implementations got different answers")
        self.assertEqual(old["read"], CELL_30, "low byte of 0x183B is at 0x30")
        self.assertTrue(old["write"])
        self.assertEqual(old["readback"], 0)
        self.assertIn(b":OK;", old["service"])

    def test_frames_are_identical_for_every_operation(self):
        old_printer = fake_printer()
        new_printer = fake_printer()
        run_reference_against(old_printer)
        run_library_against(new_printer)
        self.assertEqual(old_printer.frames, new_printer.frames)
        # and the fake printer really was asked for something
        self.assertGreaterEqual(len(new_printer.frames), 4)

    def test_handshake_matches_packet_by_packet(self):
        old_printer = fake_printer()
        new_printer = fake_printer()
        run_reference_against(old_printer)
        run_library_against(new_printer)
        old_packets = [p.payload for p in old_printer.d4_packets]
        new_packets = [p.payload for p in new_printer.d4_packets]
        self.assertEqual(old_packets, new_packets)
        # The printer says it speaks revision 0x10 while the host offers 0x20,
        # so both implementations must have retried with 0x10.
        self.assertIn(bytes([0x00, 0x20]), old_packets)
        self.assertIn(bytes([0x00, 0x10]), old_packets)

    def test_frame_builders_identical(self):
        for address in (0x00, 0x1C, 0x30, 0xFF, 0x0644):
            self.assertEqual(
                reference.build_read_cmd(address),
                eeprom_read_frame(READ_KEY, address),
            )
            for value in (0x00, 0x5E, 0xFF):
                self.assertEqual(
                    reference.build_write_cmd(address, value),
                    eeprom_write_frame(READ_KEY, WRITE_KEY, address, value),
                )
        for serial in ("MOCKSERIAL", "ABCD012345", "x"):
            self.assertEqual(
                reference.build_service_rw_cmd(serial),
                rw_frame(serial, mode=None),
            )

    def test_golden_hex_of_the_documented_frames(self):
        """The byte layout the issue reports quote, still byte for byte."""
        self.assertEqual(
            eeprom_read_frame((0x4A, 0x36), 0x30),
            bytes.fromhex("7c7c07004a3641bea03000"),
        )
        self.assertEqual(
            eeprom_write_frame(
                (0x4A, 0x36), bytes.fromhex("4e62736a63627a62"), 0x30, 0
            ),
            bytes.fromhex("7c7c10004a3642bd213000004e62736a63627a62"),
        )


class ReadOnlyGateTests(unittest.TestCase):
    """The read-only default must still be read-only, in both implementations."""

    def test_reference_never_writes_without_a_write_call(self):
        printer = fake_printer()
        run_reference_against(printer)
        # one write was requested on purpose in the harness; what must not
        # happen is more than that.
        self.assertEqual(len(printer.eeprom_writes), 1)

    def test_library_read_path_writes_nothing(self):
        printer = fake_printer()
        session = EpsonCtrlSession(
            MockTransport(printer=printer), read_key=READ_KEY,
            write_key=WRITE_KEY
        )
        try:
            session.connect()
            session.read_eeprom(READ_ADDR)
            session.read_eeprom(READ_ADDR + 1)
        finally:
            session.close()
        self.assertEqual(printer.eeprom_writes, [])


if __name__ == "__main__":
    unittest.main()

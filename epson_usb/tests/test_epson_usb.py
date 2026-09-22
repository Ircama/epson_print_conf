#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-contained tests for the hosted ``epson_usb`` library.

Run from the repository root::

    python -m unittest discover -s epson_usb/tests -t .

Everything here uses the in-memory fake printer, so no hardware and no network
are needed. Three things are checked, in this order of importance for *this*
repository:

1. **The integration works**: this repository's own ``EpsonPrinter`` reaches a
   printer over the USB link, through the single method the library overrides
   (``fetch_oid_values``), using this repository's own parameters.
2. **The library is a library**: it carries no printer model data, imports
   nothing from the project it was extracted from, and exposes no model
   registry. One of the tests below reads its source to say so.
3. **The protocol honours its safety rules**: reads never write, a dry run
   writes nothing, an unconfirmed write is reported as a failure, and a counter
   is decoded little-endian (the bug this protocol work spent a session on).

The rest of the library's suite stays in its source repository, because it
tests the client half (model tables, command line, the standalone tool and a
byte-for-byte comparison against a frozen copy of it).
"""

import logging
import os
import sys
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
for path in (REPO_ROOT, HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

from epson_usb import EpsonUsbPrinter
from epson_usb.backends.mock import MockConfig, MockPrinter, MockTransport
from epson_usb.eeprom import decode_counter, percentage
from epson_usb.errors import EepromError
from epson_usb.epson_ctrl import eeprom_read_frame, parse_snmp_oid

#: The keys and addresses the fake printer is told to imitate below. They are
#: *not* model data of the library: they are arguments of this test file, which
#: is exactly the point -- the library has none, so a caller supplies them.
READ_KEY = (0x4A, 0x36)
WRITE_KEY = b"Nbsjcbzb"
CELL_30 = 0x3B
CELL_31 = 0x18


def fake_printer(**overrides) -> MockPrinter:
    """A fake printer holding a known, little-endian counter in 0x30/0x31.

    Keys are *not* enforced: the fake answers whatever key it is sent. That is
    what the integration tests need, because ``epson_print_conf`` builds the
    frames from its own configuration for the model in use -- a key this test
    file has no business agreeing with.
    """
    cells = {0x30: CELL_30, 0x31: CELL_31, 0x1C: 0x00}
    cells.update(overrides.pop("cells", {}))
    return MockPrinter(MockConfig(eeprom=cells, **overrides))


def keyed_fake(**overrides) -> MockPrinter:
    """A fake printer that *enforces* the keys below.

    Used where the point of the test is the key handling itself: a wrong write
    key must be refused, and an absent one must never be guessed.
    """
    overrides.setdefault("read_key", READ_KEY)
    overrides.setdefault("write_key", WRITE_KEY)
    return fake_printer(**overrides)


def open_printer(fake=None, **kwargs) -> EpsonUsbPrinter:
    fake = fake if fake is not None else fake_printer()
    kwargs.setdefault("read_key", READ_KEY)
    kwargs.setdefault("write_key", WRITE_KEY)
    return EpsonUsbPrinter(transport=MockTransport(printer=fake), **kwargs)


class SessionTests(unittest.TestCase):
    """The D4 handshake and the frame grammar, against the fake printer."""

    def test_handshake_negotiates_the_printers_revision(self):
        fake = fake_printer(revision=0x10)
        printer = open_printer(fake)
        try:
            self.assertEqual(printer.revision, 0x10)
            # The host offers 0x20 first and retries with what it was told.
            offered = [packet.payload[:2] for packet in fake.d4_packets
                       if packet.payload[:1] == b"\x00"]
            self.assertIn(bytes([0x00, 0x20]), offered)
            self.assertIn(bytes([0x00, 0x10]), offered)
        finally:
            printer.close()

    def test_the_read_frame_is_the_documented_one(self):
        fake = fake_printer()
        printer = open_printer(fake)
        try:
            self.assertEqual(printer.read_eeprom(0x30), "%02X" % CELL_30)
            self.assertIn(eeprom_read_frame(READ_KEY, 0x30), fake.frames)
        finally:
            printer.close()

    def test_no_reply_is_none_not_an_exception(self):
        # `silent` silences the handshake too, so the printer is connected
        # first and only then goes quiet -- as a cable pulled mid-session would.
        printer = open_printer()
        try:
            printer.transport.printer.config.silent = True
            self.assertIsNone(printer.read_eeprom(0x30))
            self.assertFalse(printer.write_eeprom(0x1C, 0x11))
        finally:
            printer.close()

    def test_a_locked_eeprom_answers_nothing(self):
        printer = open_printer(fake_printer(eeprom_locked=True))
        try:
            self.assertIsNone(printer.read_cell(0x30))
            self.assertFalse(printer.write_eeprom(0x1C, 0x11))
        finally:
            printer.close()


class KeysComeFromTheCallerTests(unittest.TestCase):
    """The library has no keys; asking for EEPROM access without them says so."""

    def test_reading_without_keys_explains_itself(self):
        printer = EpsonUsbPrinter(transport=MockTransport(printer=fake_printer()))
        try:
            with self.assertRaises(EepromError) as context:
                printer.read_eeprom(0x30)
            self.assertIn("read_key", str(context.exception))
            self.assertIn("per-model data", str(context.exception))
        finally:
            printer.close()

    def test_writing_without_keys_is_refused_before_anything_is_sent(self):
        fake = fake_printer()
        printer = EpsonUsbPrinter(read_key=READ_KEY, transport=MockTransport(printer=fake))
        try:
            with self.assertRaises(EepromError):
                printer.write_eeprom(0x1C, 0x11)
            self.assertEqual(fake.eeprom_writes, [])
        finally:
            printer.close()

    def test_a_wrong_write_key_is_refused_by_the_printer(self):
        printer = open_printer(keyed_fake(), write_key=b"XXXXXXXX")
        try:
            self.assertFalse(printer.write_eeprom(0x1C, 0x11))
        finally:
            printer.close()


class SafetyTests(unittest.TestCase):
    """Read paths never write; a dry run cannot write; a write is verified."""

    def test_read_paths_never_write(self):
        fake = fake_printer()
        printer = open_printer(fake)
        try:
            printer.read_eeprom(0x30)
            printer.read_eeprom([0x30, 0x31])
            printer.read_eeprom_many(range(0x30, 0x34))
            printer.read_cell(0x30)
            printer.dump_eeprom(0x30, 0x33)
            printer.get_printer_status()
            printer.get_firmware_version()
            printer.get_device_identification()
            printer.get_cartridges()
            printer.read_serial(range(0x644, 0x64E))
        finally:
            printer.close()
        self.assertEqual(fake.eeprom_writes, [], "a read path wrote to the printer")

    def test_dry_run_sends_a_read_instead_of_a_write(self):
        fake = fake_printer()
        printer = open_printer(fake, dry_run=True)
        try:
            self.assertTrue(printer.write_eeprom(0x1C, 0x11))
        finally:
            printer.close()
        self.assertEqual(fake.eeprom_writes, [])
        self.assertIn(eeprom_read_frame(READ_KEY, 0x1C), fake.frames)
        self.assertFalse(any(frame[4] == 0x42 for frame in fake.frames
                             if len(frame) > 4),
                         "a write opcode reached the printer during a dry run")

    def test_a_write_is_confirmed_and_read_back(self):
        fake = fake_printer()
        printer = open_printer(fake)
        try:
            self.assertTrue(printer.write_cells([(0x1C, 0x11)]))
            self.assertEqual(printer.read_cell(0x1C), 0x11)
        finally:
            printer.close()
        self.assertEqual(fake.eeprom_writes, [(0x1C, 0x11)])

    def test_an_unconfirmed_write_is_reported_as_failure(self):
        # read_only: the printer answers, but refuses the write.
        printer = open_printer(fake_printer(read_only=True))
        try:
            self.assertFalse(printer.write_eeprom(0x1C, 0x11))
        finally:
            printer.close()


class EepromConventionTests(unittest.TestCase):
    """Byte order and the divider unit: the two silent arithmetic traps."""

    def test_counters_are_little_endian(self):
        self.assertEqual(decode_counter([CELL_30, CELL_31]), 6203)
        self.assertEqual(decode_counter([0xCC, 0x18]), 6348)
        self.assertEqual(decode_counter([0x01, 0x02, 0x03]), 0x030201)
        # Read big-endian the same two bytes are 15128, which cannot explain
        # the measured error state: see epson_usb/eeprom.py.
        self.assertNotEqual(decode_counter([CELL_30, CELL_31]), 0x3B18)

    def test_percentage_needs_the_divisor_from_the_caller(self):
        self.assertAlmostEqual(percentage(6203, 6346), 97.75, places=2)
        with self.assertRaises(ValueError):
            percentage(1, 0)


class BackupTests(unittest.TestCase):
    """The backup format is a user-facing contract: 256 cells, JSON."""

    def test_dump_bank0_covers_every_cell(self):
        printer = open_printer()
        try:
            cells = printer.dump_bank0()
        finally:
            printer.close()
        self.assertEqual(len(cells), 256)
        self.assertEqual(cells[0x30], CELL_30)
        self.assertEqual(cells[0x31], CELL_31)

    def test_save_and_restore_round_trip(self):
        import tempfile

        fake = fake_printer()
        printer = open_printer(fake)
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = printer.save_backup(directory=directory)
                self.assertTrue(os.path.isfile(path))
                fake.config.eeprom[0x1C] = 0x63          # damage the printer
                report = printer.restore_backup(
                    path, addresses=[0x1C, 0x30], safety_backup=False,
                    directory=directory,
                )
            self.assertTrue(report.ok, str(report))
            self.assertEqual(printer.read_cell(0x1C), 0x00)
        finally:
            printer.close()


class UpstreamBridgeTests(unittest.TestCase):
    """The whole integration, in one test: ``epson_print_conf`` over USB.

    No model tables are involved. Upstream's own configuration supplies the
    keys, the OID carries the EPSON-CTRL frame, and the library only puts those
    bytes on the cable -- which is why this directory needs no printer
    database.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import epson_print_conf
        except Exception as exc:                     # pragma: no cover
            raise unittest.SkipTest("epson_print_conf is not importable: %s" % exc)
        cls.upstream = epson_print_conf
        config = getattr(epson_print_conf.EpsonPrinter, "PRINTER_CONFIG", {}) or {}
        cls.known = next(
            (name for name, entry in config.items()
             if isinstance(entry, dict) and "read_key" in entry),
            None,
        )
        if cls.known is None:                        # pragma: no cover
            raise unittest.SkipTest("upstream configures no model with a read_key")

    def usb_printer_class(self):
        """The USB-capable ``EpsonPrinter`` subclass, built once per call."""
        from epson_usb.compat import usb_printer

        return usb_printer(self.upstream.EpsonPrinter)

    def usb_printer(self, fake, **kwargs):
        return self.usb_printer_class()(
            model=self.known,
            transport=MockTransport(printer=fake),
            **kwargs
        )

    def test_upstream_reads_eeprom_over_usb(self):
        fake = fake_printer()
        # A model upstream knows keeps its own parameters: the fake printer
        # accepts any read key (MockConfig declares none), which is what makes
        # the comparison about the transport and nothing else.
        printer = self.usb_printer(fake)
        try:
            self.assertEqual(printer.read_eeprom(0x30), "%02X" % CELL_30)
            self.assertEqual(printer.read_eeprom(0x31), "%02X" % CELL_31)
        finally:
            printer.close()
        self.assertTrue(fake.frames, "nothing reached the printer")
        # The frames were built by upstream's own code, from its own parm.
        self.assertTrue(all(frame[:2] == b"||" for frame in fake.frames))

    def test_upstream_writes_eeprom_over_usb_and_dry_run_does_not(self):
        fake = fake_printer()
        printer = self.usb_printer(fake)
        try:
            self.assertTrue(printer.write_eeprom(0x1C, 0x11))
        finally:
            printer.close()
        self.assertEqual(fake.eeprom_writes, [(0x1C, 0x11)])

        dry = fake_printer()
        printer = self.usb_printer(dry, dry_run=True)
        try:
            self.assertTrue(printer.write_eeprom(0x1C, 0x11))
        finally:
            printer.close()
        self.assertEqual(dry.eeprom_writes, [])

    def test_mib_queries_answer_unavailable_instead_of_lying(self):
        printer = self.usb_printer(fake_printer())
        try:
            self.assertEqual(
                printer.fetch_oid_values("1.3.6.1.4.1.1248.1.1.3.1.29.3.1.27.0"),
                [(None, False)],
            )
        finally:
            printer.close()

    def test_printing_methods_fail_loudly(self):
        printer = self.usb_printer(fake_printer())
        try:
            with self.assertRaises(NotImplementedError):
                printer.print_check_nozzles(0)
        finally:
            printer.close()

    def test_construction_alone_does_not_touch_the_hardware(self):
        """The GUI builds printers to list models (ui.py:475)."""
        printer = self.usb_printer(fake_printer())
        try:
            self.assertFalse(printer.usb.connected)
            self.assertEqual(printer.usb_describe(), "not connected")
        finally:
            printer.close()

    def test_the_default_factory_is_not_given_host_identity(self):
        """``model=``/``printer=`` are host identity, not transport options.

        The default factory is ``EpsonUsbPrinter``, whose ``**transport_kwargs``
        are forwarded to the backend constructor: handing it ``model=`` used to
        break device discovery with "__init__() got an unexpected keyword
        argument 'model'" for every caller that did not build the transport
        itself. A transport option (``config=``, ``usb_options=``) must still get
        through.
        """
        from epson_usb.compat import factory_kwargs

        kwargs = factory_kwargs(
            EpsonUsbPrinter,
            {"model": "X", "printer": object(), "backend": "mock", "config": 1},
        )
        self.assertNotIn("model", kwargs)
        self.assertNotIn("printer", kwargs)
        self.assertEqual(kwargs["backend"], "mock")
        self.assertEqual(kwargs["config"], 1)

    def test_automatic_device_discovery_works_with_the_default_factory(self):
        # No `transport=`: the printer has to find its own device, which is the
        # path the regression above broke.
        printer_class = self.usb_printer_class()
        printer = printer_class(model=self.known, backend="mock")
        try:
            # Opening is lazy, so the transport only exists once a command has
            # been sent: that is what makes the discovery path observable here.
            self.assertEqual(printer.read_eeprom(0x30), "00")
            self.assertIsNotNone(printer.usb.transport)
            self.assertTrue(printer.usb.connected)
        finally:
            printer.close()

    def test_the_host_hook_patches_this_repository_and_is_idempotent(self):
        import epson_print_conf as host

        original = host.EpsonPrinter
        # A model this file does not know keeps upstream's own parameters: the
        # hook adds the transport and nothing else.
        try:
            patched = host.enable_usb_transport()
            self.assertIs(host.EpsonPrinter, patched)
            self.assertTrue(issubclass(patched, original))
            self.assertIs(host.NetworkEpsonPrinter, original)
            self.assertIs(host.enable_usb_transport(), patched)   # no double wrap
            self.assertIn("UsbEpsonPrinterMixin", str(patched.__mro__))
        finally:
            host.EpsonPrinter = original
            if hasattr(host, "NetworkEpsonPrinter"):
                del host.NetworkEpsonPrinter


class APrinterThatSkipsTheLeadingNulTests(unittest.TestCase):
    """Replies from a real XP-205, and the host's own framing check.

    Upstream's ``invalid_response`` required ``response[0] == 0`` -- the padding
    a well-behaved ``@BDC`` block carries. A real XP-205 sends none of it::

        b'@BDC PS\\r\\nEE:01660F;\\x0c'      EEPROM cell 358 (Power off timer)
        b'@BDC PS\\r\\n||:OK;\\x0c'          a confirmed write
        b'@BDC PS\\r\\nIA:00;18XL,...;\\x0c' the cartridges

    Every one of those was declared "Invalid response", so a *correct* answer
    turned into a missing value: the reported symptom was "GET Power off timer"
    printing None. The rule now accepts either shape (the library's own check
    always did; ``epson_print_conf`` is the half that needed fixing), and this
    suite -- the only one in this repository -- pins it, because the library
    cannot test code that does not live in it.
    """

    #: Verbatim from the printer's log, including the 0x0C terminator.
    ACCEPTED = (
        b"@BDC PS\r\nEE:01660F;\x0c",
        b"@BDC PS\r\nEE:016700;\x0c",
        b"@BDC PS\r\n||:OK;\x0c",
        b"@BDC PS\r\nIA:00;18XL      ,18XL      ,18XL      ,18XL      ;\x0c",
        # A refusal is a well-formed block, not a malformed reply: the framing
        # check passes it on and the callers' own `:NA;`/`EE:` tests reject it.
        b"@BDC PS\r\n||:NA;\x0c",
        b"\x00@BDC PS\r\nEE:01660F;\x0c",       # the padded shape still passes
        # Bare blocks, with no `@BDC PS` header at all: the same printer sends
        # them for an ink slot it does not have and for a write it confirms.
        b"ii:NA;\x0c",
        b"||:OK;\x0c",
        # A refusal is an *answer*: the printer said no (wrong access key,
        # locked EEPROM). The callers' own tests turn it into None/False, and
        # `brute_force_read_key` -- 65536 attempts, where a refusal is the
        # expected reply for every wrong key -- must not log an error each time.
        b"||:41:NA;\x0c",
        b"||:NA;\x0c",
        # A *write* is confirmed with the same shape, the opcode in the middle:
        # `||:42:OK;` (measured on an XP-205). Calling that invalid made the host
        # report a write the printer had carried out as failed.
        b"||:42:OK;\x0c",
        b"@BDC PS\r\n||:42:OK;\x0c",
    )

    #: Truncated, unrelated or absent: none of these may pass for an answer.
    REJECTED = (
        b"",                                     # nothing at all
        b"\x0c",                                 # terminator only
        b"@BDC PS\r\nEE:01660F;",                # no terminator
        b"\x01\x02\x03\x0c",                     # no `name:...;` element
        False,                                   # the SNMP "no such object"
        None,
    )

    @classmethod
    def setUpClass(cls):
        try:
            import epson_print_conf
        except Exception as exc:                 # pragma: no cover
            raise unittest.SkipTest("epson_print_conf is not importable: %s" % exc)
        cls.host = epson_print_conf
        config = getattr(epson_print_conf.EpsonPrinter, "PRINTER_CONFIG", {}) or {}
        cls.known = next(
            (name for name, entry in config.items()
             if isinstance(entry, dict) and "read_key" in entry),
            None,
        )
        if cls.known is None:                    # pragma: no cover
            raise unittest.SkipTest("upstream configures no model with a read_key")
        # Constructing one touches no hardware (the test above pins that); it is
        # only needed because the check is an instance method.
        cls.printer = epson_print_conf.EpsonPrinter(model=cls.known)

    def usb_printer(self, fake, **kwargs):
        from epson_usb.compat import usb_printer

        return usb_printer(self.host.EpsonPrinter)(
            model=self.known, transport=MockTransport(printer=fake), **kwargs
        )

    def test_the_answer_the_printer_gave_is_not_called_invalid(self):
        for reply in self.ACCEPTED:
            with self.subTest(reply=reply):
                self.assertIs(
                    self.printer.invalid_response(reply), False,
                    "%r was rejected; the printer sent it as a valid answer" % (reply,),
                )

    def test_truncated_and_unrelated_replies_are_still_rejected(self):
        for reply in self.REJECTED:
            with self.subTest(reply=reply):
                self.assertIs(
                    self.printer.invalid_response(reply), True,
                    "%r was accepted; it is not an answer" % (reply,),
                )

    def test_upstream_reads_eeprom_from_such_a_printer(self):
        fake = fake_printer(reply_prefix=b"")
        printer = self.usb_printer(fake)
        try:
            self.assertEqual(printer.read_eeprom(0x30), "%02X" % CELL_30)
            self.assertEqual(printer.read_eeprom(0x31), "%02X" % CELL_31)
        finally:
            printer.close()
        self.assertTrue(fake.frames, "nothing reached the printer")

    def test_upstream_trusts_a_write_confirmed_without_the_leading_nul(self):
        # `write_eeprom()` validates the confirmation with the same rule, so a
        # strict check also reported a *successful* write as a failure.
        fake = fake_printer(reply_prefix=b"")
        printer = self.usb_printer(fake)
        try:
            self.assertTrue(printer.write_eeprom(0x1C, 0x11))
        finally:
            printer.close()
        self.assertEqual(fake.eeprom_writes, [(0x1C, 0x11)])

    def test_a_missing_ink_slot_ends_the_list_instead_of_aborting_it(self):
        # The XP-205 has four slots and answers `ii:NA;` -- bare -- for the
        # fifth. That is the end of the list, not a malformed reply: treating it
        # as one returned None for every cartridge of a printer that had just
        # listed them.
        slot1 = (
            b"@BDC PS\r\nII:03;IQT:1D;PDY:16;PDM:06;STY:02;STM:04;STD:1B;"
            b"EDY:FF;EMD:FF;IC1:0713;IC2:NAVL;IK:NAVL;TOV:24;TVU:06;"
            b"VIQ:0474;UIQ:0233;ERC:0000000000000000;"
            b"SID:16061F09390D0400AD;LOG:;\x0c"
        )
        asked = []

        def fetch(oid, label="unknown"):
            asked.append(oid)
            return [("OctetString", slot1 if len(asked) == 1 else b"ii:NA;\x0c")]

        printer = self.host.EpsonPrinter(model=self.known)
        printer.fetch_oid_values = fetch
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            info = printer.get_cartridge_information()
        finally:
            root.removeHandler(handler)
        self.assertEqual(
            [r.getMessage() for r in records if "Invalid cartridge" in r.getMessage()],
            [],
        )
        self.assertIsNotNone(info, "the cartridge list was abandoned")
        self.assertEqual(len(info), 1)           # slot 1 only; slot 2 ended it
        self.assertEqual(info[0]["ink_quantity"], 29)
        self.assertEqual(len(asked), 2)          # nothing queried past the NA

    def test_a_refused_read_is_none_without_an_error(self):
        # What `brute_force_read_key` does 65536 times: send a key, be refused,
        # try the next one. A refusal must be a quiet negative answer, not an
        # error per attempt -- that is the reported symptom (hundreds of
        # `Invalid response for OID 0 (brute_force_read_key)` lines).
        printer = self.host.EpsonPrinter(model=self.known)
        printer.fetch_oid_values = lambda oid, label="unknown": [
            ("OctetString", b"||:41:NA;\x0c")
        ]
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            self.assertIsNone(printer.read_eeprom(0x00, label="brute_force_read_key"))
        finally:
            root.removeHandler(handler)
        self.assertEqual(
            [r.getMessage() for r in records if r.levelno >= logging.ERROR], []
        )

    def test_a_refused_ink_actuator_query_is_not_a_cartridge_list(self):
        # `||:NA;` with no `IA:00;` element: the substitution would hand the
        # refusal back as if it were the list (a locked EEPROM answers this way).
        printer = self.host.EpsonPrinter(model=self.known)
        printer.fetch_oid_values = lambda oid, label="unknown": [
            ("OctetString", b"||:NA;\x0c")
        ]
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            self.assertIsNone(printer.get_cartridges())
        finally:
            root.removeHandler(handler)
        self.assertEqual(
            [r.getMessage() for r in records if r.levelno >= logging.ERROR], []
        )

    def test_a_silent_transport_stops_the_key_scan_at_once(self):
        # What produces `Invalid response for OID 0 (brute_force_read_key):
        # False`: the transport answered nothing (device gone, wrong address).
        # There is no key to find in that case, and without the upfront check
        # the scan ran all 65536 attempts to report "not found".
        printer = self.host.EpsonPrinter(model=self.known)
        calls = []

        def fetch(oid, label="unknown"):
            calls.append(label)
            return [(None, False)]

        printer.fetch_oid_values = fetch
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            self.assertIsNone(printer.brute_force_read_key())
        finally:
            root.removeHandler(handler)
        self.assertEqual(len(calls), 1, "the scan went on with no reply at all")
        self.assertTrue(
            [r for r in records if r.levelno >= logging.ERROR],
            "a silent transport must be reported, not turned into 'no key'",
        )

    def test_the_key_scan_finds_the_key_and_reports_progress(self):
        # A wrong key is answered with a refusal, the right one with the value:
        # that is the whole scan. It must report progress, because a caller
        # with a window shows it -- the log is silenced while scanning.
        target = (2, 3)
        printer = self.host.EpsonPrinter(model=self.known)

        def fetch(oid, label="unknown"):
            _, payload = parse_snmp_oid(oid)
            key = (payload[0], payload[1])
            addr = payload[5] | (payload[6] << 8)
            if key == target:
                return [
                    ("OctetString",
                     b"@BDC PS\r\nEE:%04X%02X;\x0c" % (addr, 0xA5))
                ]
            return [("OctetString", b"||:41:NA;\x0c")]

        printer.fetch_oid_values = fetch
        seen = []
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            found = printer.brute_force_read_key(
                0, 3, progress=lambda a, t, k: seen.append((a, t, tuple(k)))
            )
        finally:
            root.removeHandler(handler)
        self.assertEqual(found, list(target))
        self.assertEqual(seen[0][0], 1)             # reported from the start
        self.assertEqual(seen[0][1], 16)            # (0..3) ** 2 candidates
        self.assertEqual(seen[0][2], (0, 0))
        # A refusal is the expected answer to a wrong key: the scan must not
        # turn every one of them into a logged error.
        self.assertEqual(
            [r.getMessage() for r in records if r.levelno >= logging.ERROR], []
        )

    def test_the_key_scan_stops_when_the_printer_goes_mute(self):
        # `Invalid response for OID 0 (brute_force_read_key): False` repeating
        # for minutes: the first attempts were answered, then the printer
        # stopped answering altogether. A refusal means "wrong key, try the
        # next"; silence means there is nothing to find, and the remaining
        # attempts would all be wasted.
        printer = self.host.EpsonPrinter(model=self.known)
        calls = []

        def fetch(oid, label="unknown"):
            calls.append(label)
            if len(calls) <= 2:
                return [("OctetString", b"||:41:NA;\x0c")]
            return [(None, False)]

        printer.fetch_oid_values = fetch
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            self.assertIsNone(printer.brute_force_read_key())
        finally:
            root.removeHandler(handler)
        self.assertLessEqual(
            len(calls), 8, "the scan went on with the printer answering nothing"
        )
        self.assertTrue(
            [r for r in records if r.levelno >= logging.ERROR],
            "the silence must be reported, not turned into 'no key found'",
        )

    def test_the_temporary_waste_reset_needs_an_explicit_ok(self):
        # `rw` is the one command that needs no EEPROM key, which is why it is
        # the fallback on printers whose EEPROM is locked. Its answer echoes a
        # mode the printer reports in its own way, so the confirmation is the
        # `rw:` name plus an explicit `:OK;` -- and a refusal must stay one.
        printer = self.host.EpsonPrinter(model=self.known)
        printer.get_serial_number = lambda: "QJFK135617"
        for reply, expected in (
            (b"@BDC PS\r\nrw:01:OK;\x0c", True),
            (b"@BDC PS\r\nrw:02:OK;\x0c", True),   # another mode echoed
            (b"rw:01:OK;\x0c", True),               # bare, as this XP-205 answers
            (b"@BDC PS\r\nrw:00:NA;\x0c", False),  # refused
            (b"||:41:NA;\x0c", False),              # nothing to do with rw
        ):
            with self.subTest(reply=reply):
                printer.fetch_oid_values = (
                    lambda oid, label="unknown", reply=reply: [
                        ("OctetString", reply)
                    ]
                )
                self.assertIs(printer.temporary_reset_waste(), expected)

    def test_a_write_confirmed_with_the_opcode_is_a_success(self):
        # The measured confirmation of a successful write: the opcode sits
        # between two colons, which the framing check used to call invalid -- so
        # a write the printer had carried out was reported as failed, and the
        # write-key detection gave up instead of restoring the byte it had just
        # written as a test.
        printer = self.host.EpsonPrinter(model=self.known)
        printer.fetch_oid_values = lambda oid, label="unknown": [
            ("OctetString", b"||:42:OK;\x0c")
        ]
        self.assertTrue(printer.write_eeprom(0x1C, 0x11, label="test"))

    def test_a_refused_write_is_still_a_failure(self):
        printer = self.host.EpsonPrinter(model=self.known)
        printer.fetch_oid_values = lambda oid, label="unknown": [
            ("OctetString", b"||:42:NA;\x0c")
        ]
        self.assertFalse(printer.write_eeprom(0x1C, 0x11, label="test"))

    def test_a_refusal_is_still_a_refusal(self):
        # `||:NA;` is a well-formed block, so `invalid_response` passes it on:
        # it is the write path's own check that must turn it into a failure.
        fake = fake_printer(reply_prefix=b"", eeprom_locked=True)
        printer = self.usb_printer(fake)
        try:
            self.assertFalse(printer.write_eeprom(0x1C, 0x11))
        finally:
            printer.close()
        self.assertEqual(fake.eeprom_writes, [])


class WriteKeyValidationTests(unittest.TestCase):
    """Checking a write key *changes* a byte of the printer, then puts it back.

    That is upstream's way of validating the key: write the last byte of the
    serial number + 1, read it back, restore the original. A lost reply during
    the restore leaves the printer modified -- reported on hardware as "Write
    operation failed. Check whether the serial number is changed and restore it
    manually", with the serial left one character off (QJFK135617 ->
    QJFK135618 on an XP-205).
    """

    @classmethod
    def setUpClass(cls):
        try:
            import epson_print_conf
        except Exception as exc:                 # pragma: no cover
            raise unittest.SkipTest("epson_print_conf is not importable: %s" % exc)
        cls.host = epson_print_conf
        config = getattr(epson_print_conf.EpsonPrinter, "PRINTER_CONFIG", {}) or {}
        cls.known = next(
            (name for name, entry in config.items()
             if isinstance(entry, dict) and "read_key" in entry),
            None,
        )
        if cls.known is None:                    # pragma: no cover
            raise unittest.SkipTest("upstream configures no model with a read_key")

    def printer_with_cell(self, value, restore_failures=0):
        """A printer whose cell 201 is faked, failing that many restores."""
        printer = self.host.EpsonPrinter(model=self.known)
        state = {"value": value, "writes": [], "failures": restore_failures}

        def write_eeprom(oid, new_value, label="unknown method"):
            state["writes"].append((oid, new_value))
            if new_value == value and state["failures"] > 0:
                state["failures"] -= 1
                return False
            state["value"] = new_value
            return True

        printer.write_eeprom = write_eeprom
        printer.read_eeprom = (
            lambda oid, label="unknown method": "%02X" % state["value"]
        )
        return printer, state

    def test_a_lost_reply_does_not_leave_the_printer_modified(self):
        printer, state = self.printer_with_cell(0x37, restore_failures=1)
        self.assertTrue(printer.validate_write_key(201, 0x37, label="test"))
        self.assertEqual(state["value"], 0x37)   # put back
        self.assertEqual(state["writes"], [(201, 0x38), (201, 0x37), (201, 0x37)])

    def test_a_restore_that_never_works_says_how_to_fix_it(self):
        printer, state = self.printer_with_cell(0x37, restore_failures=99)
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            self.assertIsNone(printer.validate_write_key(201, 0x37, label="test"))
        finally:
            root.removeHandler(handler)
        self.assertNotEqual(state["value"], 0x37)   # the test value stayed
        message = " ".join(
            r.getMessage() for r in records if r.levelno >= logging.ERROR
        )
        self.assertIn("201", message)              # the address to repair
        self.assertIn("55", message)               # and the value to write


class MultiCellParameterTests(unittest.TestCase):
    """A parameter made of several cells is written cell by cell.

    `update_parameter()` used to `return True` from inside its own loop, so
    "Set Printer Serial Number" wrote the first of the ten cells and reported
    "Update operation completed": the serial number looked unchanged, because
    the character that had been asked for was not the one written.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import epson_print_conf
        except Exception as exc:                 # pragma: no cover
            raise unittest.SkipTest("epson_print_conf is not importable: %s" % exc)
        cls.host = epson_print_conf
        config = getattr(epson_print_conf.EpsonPrinter, "PRINTER_CONFIG", {}) or {}
        cls.known = next(
            (name for name, entry in config.items()
             if isinstance(entry, dict) and "read_key" in entry),
            None,
        )
        if cls.known is None:                    # pragma: no cover
            raise unittest.SkipTest("upstream configures no model with a read_key")

    def printer_writing_into(self, written, fail_at=None):
        printer = self.host.EpsonPrinter(model=self.known)

        def write_eeprom(oid, value, label="unknown method"):
            if fail_at is not None and oid == fail_at:
                return False
            written.append((oid, value))
            return True

        printer.write_eeprom = write_eeprom
        printer.parm = {"serial_number": range(192, 202)}
        return printer

    def test_every_cell_of_the_serial_number_is_written(self):
        written = []
        printer = self.printer_writing_into(written)
        values = [ord(c) for c in "QJFK135617"]
        self.assertTrue(
            printer.update_parameter("serial_number", values)
        )
        self.assertEqual(written, list(zip(range(192, 202), values)))

    def test_a_cell_that_fails_stops_the_parameter_and_is_reported(self):
        written = []
        printer = self.printer_writing_into(written, fail_at=195)
        values = [ord(c) for c in "QJFK135617"]
        self.assertFalse(
            printer.update_parameter("serial_number", values)
        )
        self.assertEqual([oid for oid, _ in written], [192, 193, 194])

    def test_a_parameter_held_as_several_ranges_is_written_in_full(self):
        written = []
        printer = self.printer_writing_into(written)
        printer.parm = {"serial_number": [range(192, 195), range(200, 203)]}
        self.assertTrue(
            printer.update_parameter("serial_number", [1, 2, 3])
        )
        self.assertEqual(
            written,
            [(192, 1), (193, 2), (194, 3), (200, 1), (201, 2), (202, 3)],
        )

    def test_a_dry_run_writes_nothing(self):
        written = []
        printer = self.printer_writing_into(written)
        self.assertTrue(
            printer.update_parameter("serial_number", [1] * 10, dry_run=True)
        )
        self.assertEqual(written, [])


class UsbEnvironmentWarningTests(unittest.TestCase):
    """The message macOS and Linux get when USB has no usable backend.

    Windows reaches the printer natively (USBPRINT), so there is nothing to
    install and nothing to warn about. On the other platforms the transport
    needs libusb, PyUSB or a raw device node: a user who selects USB without
    any of the three would only find out on the first command, so the host
    answers the question beforehand (the GUI and the command line both ask).
    """

    @classmethod
    def setUpClass(cls):
        try:
            import epson_print_conf
        except Exception as exc:                 # pragma: no cover
            raise unittest.SkipTest("epson_print_conf is not importable: %s" % exc)
        cls.host = epson_print_conf

    def warning(self, platform, available):
        import epson_usb.backends as backends

        with mock.patch.object(self.host.sys, "platform", platform), mock.patch.object(
            backends, "available_backends", lambda: list(available)
        ):
            return self.host.usb_transport_warning()

    def test_windows_needs_nothing(self):
        self.assertIsNone(self.warning("win32", []))

    def test_a_platform_without_any_backend_says_what_is_missing(self):
        for platform in ("linux", "darwin"):
            with self.subTest(platform=platform):
                message = self.warning(platform, ["mock"])
                self.assertIsNotNone(message)
                for hint in ("libusb", "pyusb", platform):
                    self.assertIn(hint, message)

    def test_libusb_is_enough(self):
        self.assertIsNone(self.warning("linux", ["libusb", "mock"]))

    def test_pyusb_is_enough(self):
        self.assertIsNone(self.warning("darwin", ["pyusb", "mock"]))

    def test_a_raw_device_is_enough(self):
        # A character device needs no library at all.
        self.assertIsNone(self.warning("darwin", ["raw", "mock"]))


class WindowsPrefersTheNativeBackendTests(unittest.TestCase):
    """On Windows the native USBPRINT backend is tried first.

    That is the route needing no driver change: SetupAPI and kernel32 talk to
    the channel the installed Epson driver already publishes. libusb and PyUSB
    stay available, but come after it, because both reach the printer's
    vendor-specific interface directly and would therefore need that driver
    replaced by WinUSB (Zadig).
    """

    def test_usbprint_comes_first_on_windows(self):
        from epson_usb.backends import DEFAULT_ORDER

        order = DEFAULT_ORDER["win32"]
        self.assertEqual(order[0], "usbprint")
        self.assertIn("libusb", order)
        self.assertIn("pyusb", order)

    def test_the_native_backend_is_always_registerable(self):
        # backends are imported lazily, so asking for one must work everywhere;
        # whether it can *run* here is what available() answers.
        from epson_usb.backends import backend_class

        cls = backend_class("usbprint")
        self.assertEqual(cls.name, "usbprint")
        self.assertIsInstance(cls.available(), bool)


class LibraryHasNoModelDataTests(unittest.TestCase):
    """The property that makes hosting this directory reasonable."""

    LIBRARY = os.path.join(REPO_ROOT, "epson_usb")
    CLIENT_MODULES = ("epson_l3250", "epson_l3250_cli", "epson_print_conf_usb",
                      "epson_l3251_usb_reset", "epson_usb_probe")
    FORBIDDEN = ("Maribaya", "Nbsjcbzb", "0x4A, 0x36", "6346", "L3251")

    def sources(self):
        """The library's own modules -- not this test file, which is a client."""
        for root, dirs, files in os.walk(self.LIBRARY):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests",
                                                    "examples")]
            for name in sorted(files):
                if name.endswith(".py"):
                    path = os.path.join(root, name)
                    with open(path, "r", encoding="utf-8") as handle:
                        yield path, handle.read()

    def test_no_client_module_is_imported(self):
        import ast

        for path, text in self.sources():
            tree = ast.parse(text, filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                elif isinstance(node, ast.Call):
                    target = getattr(node.func, "id", None) or getattr(
                        node.func, "attr", None)
                    names = ([argument.value for argument in node.args
                              if isinstance(argument, ast.Constant)] if
                             target in ("import_module", "__import__") else [])
                else:
                    continue
                for name in names:
                    if not isinstance(name, str):
                        continue
                    root = name.split(".")[0]
                    with self.subTest(file=path, import_=name):
                        self.assertNotIn(root, self.CLIENT_MODULES)

    def test_no_per_model_literal_is_used_in_code(self):
        import ast

        for path, text in self.sources():
            tree = ast.parse(text, filename=path)
            docstrings = set()
            holders = (ast.Module, ast.ClassDef, ast.FunctionDef,
                       ast.AsyncFunctionDef)
            for node in ast.walk(tree):
                if isinstance(node, holders):
                    body = getattr(node, "body", [])
                    if body and isinstance(body[0], ast.Expr) and isinstance(
                            body[0].value, ast.Constant):
                        docstrings.add(id(body[0].value))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or id(node) in docstrings:
                    continue
                if not isinstance(node.value, (str, bytes)):
                    continue
                rendered = (node.value.decode("latin-1", "replace")
                            if isinstance(node.value, bytes) else node.value)
                for needle in self.FORBIDDEN:
                    with self.subTest(file=path, needle=needle):
                        self.assertNotIn(needle, rendered)

    def test_the_public_api_has_no_model(self):
        import epson_usb

        for name in ("MODELS", "DEFAULT_MODEL", "PrinterModel",
                     "resolve_model", "print_conf_params"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(epson_usb, name))

    def test_the_constructor_takes_keys_not_a_model(self):
        import inspect

        parameters = inspect.signature(EpsonUsbPrinter.__init__).parameters
        self.assertIn("read_key", parameters)
        self.assertIn("write_key", parameters)
        self.assertNotIn("model", parameters)

    def test_the_client_half_is_not_here(self):
        for name in ("epson_l3250.py", "epson_l3250_cli.py", "models.py"):
            with self.subTest(name=name):
                self.assertFalse(os.path.exists(os.path.join(REPO_ROOT, name)))
                self.assertFalse(
                    os.path.exists(os.path.join(self.LIBRARY, name)))


if __name__ == "__main__":
    unittest.main()

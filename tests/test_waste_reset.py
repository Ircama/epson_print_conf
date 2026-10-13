"""Offline regression tests; every printer exchange stays in memory."""

import copy
import logging
from pathlib import Path
import tempfile
import unittest

from epson_print_conf import EpsonPrinter
from parse_devices import generate_config_from_xml, normalize_config


class MemoryPrinter(EpsonPrinter):
    """Exercise the real EEPROM encoder, decoder and write verification."""

    def __init__(self, model="ET-2814", config=None, **kwargs):
        if config is None:
            config = {
                name: data for name, data in self.PRINTER_CONFIG.items()
                if name == model or model in data.get("alias", [])
            }
        super().__init__(
            conf_dict=copy.deepcopy(config),
            replace_conf=True, model=model, **kwargs
        )
        self.memory = dict(self.parm.get("raw_waste_reset", {}))
        self.memory[0x100] = 1
        self.events = []
        self.refused_writes = set()
        self.discarded_writes = set()
        self.read_hook = None
        self.write_hook = None

    def fetch_oid_values(self, oid, label="unknown"):
        if isinstance(oid, list):
            return [self.fetch_oid_values(item, label)[0] for item in oid]
        prefix = self.EPSON_CTRL_TO_OID + "."
        assert oid.startswith(prefix), oid
        frame = bytes(int(part) for part in oid[len(prefix):].split("."))
        assert frame[:2] == b"||", frame
        payload = frame[4:]
        opcode = payload[2]
        address = int.from_bytes(payload[5:7], "little")
        if opcode == ord("A"):
            self.events.append(("read", address))
            if self.read_hook and self.read_hook(address) is False:
                return [("OctetString", b"||:41:NA;\x0c")]
            value = self.memory.get(address, 0)
            reply = "EE:{:04X}{:02X};\x0c".format(address, value).encode()
        else:
            assert opcode == ord("B"), frame
            value = payload[7]
            self.events.append(("write", address, value))
            if address in self.refused_writes:
                return [("OctetString", b"||:42:NA;\x0c")]
            if address not in self.discarded_writes:
                self.memory[address] = value
            if self.write_hook:
                self.write_hook(address)
            reply = b"||:42:OK;\x0c"
        return [("OctetString", reply)]

    @property
    def writes(self):
        return [event[1:] for event in self.events if event[0] == "write"]


class WasteResetTests(unittest.TestCase):
    def test_zero_counters_still_complete_reset_and_report_flag_change(self):
        printer = MemoryPrinter()
        before = printer.memory.copy()
        report = []
        self.assertTrue(printer.reset_waste_ink_levels(report=report))
        self.assertEqual(printer.memory, {**before, 0x100: 0})
        self.assertEqual(
            printer.writes,
            list(printer.parm["raw_waste_reset"].items()) + [(0x100, 0)],
        )
        self.assertEqual([entry for entry in report if entry[3]],
                         [(0x100, 1, 0, True)])

    def test_preserves_other_bits_using_fresh_value_after_counter_writes(self):
        printer = MemoryPrinter()
        printer.memory[0x100] = 0xA5

        def update_flag(address):
            if address == 255:  # last counter write
                printer.memory[0x100] = 0xB5

        printer.write_hook = update_flag
        self.assertTrue(printer.reset_waste_ink_levels())
        self.assertEqual(printer.memory[0x100], 0xB4)
        self.assertEqual(printer.writes[-1], (0x100, 0xB4))

    def test_clear_flag_does_not_get_written_again(self):
        printer = MemoryPrinter()
        printer.memory[0x100] = 0xA4
        self.assertTrue(printer.reset_waste_ink_levels())
        self.assertFalse(any(address == 0x100 for address, _ in printer.writes))
        self.assertEqual(printer.memory[0x100], 0xA4)

    def test_unreadable_flag_stops_before_any_write(self):
        printer = MemoryPrinter()
        printer.read_hook = lambda address: address != 0x100
        self.assertFalse(printer.reset_waste_ink_levels())
        self.assertEqual(printer.writes, [])

    def test_timed_out_flag_stops_before_any_write(self):
        printer = MemoryPrinter()

        def timeout(address):
            raise TimeoutError("offline timeout")

        printer.read_hook = timeout
        self.assertFalse(printer.reset_waste_ink_levels())
        self.assertEqual(printer.writes, [])

    def test_lost_flag_after_counter_writes_stops_without_committing(self):
        printer = MemoryPrinter()
        printer.write_hook = lambda address: setattr(
            printer, "read_hook", lambda oid: oid != 0x100
        )
        self.assertFalse(printer.reset_waste_ink_levels())
        self.assertEqual(printer.memory[0x100], 1)
        self.assertFalse(any(address == 0x100 for address, _ in printer.writes))

    def test_refused_counter_never_reaches_commit(self):
        printer = MemoryPrinter()
        printer.refused_writes.add(48)
        self.assertFalse(printer.reset_waste_ink_levels())
        self.assertEqual(printer.writes, [(48, 0)])
        self.assertEqual(printer.memory[0x100], 1)

    def test_refused_commit_is_not_retried(self):
        printer = MemoryPrinter()
        printer.refused_writes.add(0x100)
        self.assertFalse(printer.reset_waste_ink_levels())
        self.assertEqual(printer.writes.count((0x100, 0)), 1)

    def test_ack_without_commit_change_fails_even_if_verification_disabled(self):
        for verify in (True, False):
            with self.subTest(verify_writes=verify):
                printer = MemoryPrinter(verify_writes=verify)
                printer.discarded_writes.add(0x100)
                self.assertFalse(printer.reset_waste_ink_levels())
                self.assertEqual(printer.writes.count((0x100, 0)), 1)
                self.assertEqual(printer.memory[0x100], 1)

    def test_dry_runs_never_contact_printer(self):
        for instance_dry_run in (False, True):
            printer = MemoryPrinter(dry_run=instance_dry_run)
            self.assertTrue(printer.reset_waste_ink_levels(
                dry_run=not instance_dry_run
            ))
            self.assertEqual(printer.events, [])

    def test_unrelated_profile_does_not_touch_completion_byte(self):
        printer = MemoryPrinter(model="ET-2800")
        self.assertTrue(printer.reset_waste_ink_levels())
        self.assertFalse(any(event[1] == 0x100 for event in printer.events))

    def test_known_family_aliases_share_completion_definition(self):
        for model in ("ET-2812", "ET-2814", "ET-2810", "ET-2818"):
            with self.subTest(model=model):
                self.assertEqual(MemoryPrinter(model=model).parm[
                    "waste_reset_commit"], {0x100: 0xFE})

    def test_legacy_counter_paths_also_complete_after_last_write(self):
        for borderless in (False, True):
            printer = MemoryPrinter()
            del printer.parm["raw_waste_reset"]
            if not borderless:
                del printer.parm["borderless_waste"]
            self.assertTrue(printer.reset_waste_ink_levels())
            self.assertEqual(printer.writes[-1], (0x100, 0))

    def test_invalid_commit_configuration_is_rejected_before_io(self):
        for masks in (None, [], {256: 256}, {-1: 254}, {65536: 254},
                      {"256": 254}, {256: True}):
            with self.subTest(masks=masks):
                printer = MemoryPrinter()
                printer.parm["waste_reset_commit"] = masks
                self.assertFalse(printer.reset_waste_ink_levels())
                self.assertFalse(printer.reset_waste_ink_levels(dry_run=True))
                self.assertEqual(printer.events, [])


CLOSE = """<close>
    <query>0x100 $byte</query>
    <var>$byte : $byte 0xFE &amp;</var>
    <write>0x100 $byte</write>
</close>"""


class XmlCommitTests(unittest.TestCase):
    def parse(self, close=CLOSE, extra_spec=""):
        xml = """<root>
            <printer title="Epson ET-2812/2814" short="ET-2812/2814"
                     model="ET-2810 Series" specs="BASE,OVERRIDE"/>
            <BASE>
                <service><factory>0x4A 0x36</factory>
                    <keyword>0x4E 0x62 0x73 0x6A 0x63 0x62 0x7A 0x62</keyword>
                </service>
                <waste><reset>0x30 0x00 {}</reset></waste>
            </BASE>
            <OVERRIDE>{}</OVERRIDE>
        </root>""".format(close, extra_spec)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "devices.xml"
            path.write_text(xml, encoding="utf-8")
            return generate_config_from_xml(path)

    def test_imported_close_survives_alias_normalization_and_runs(self):
        config = normalize_config(self.parse())
        printer = MemoryPrinter(config=config)
        self.assertEqual(printer.parm["waste_reset_commit"], {256: 254})
        self.assertTrue(printer.reset_waste_ink_levels())
        self.assertEqual(printer.writes, [(48, 0), (256, 0)])

    def test_reset_without_close_keeps_original_behavior(self):
        config = self.parse(close="")
        self.assertNotIn("waste_reset_commit", config["ET-2812/2814"])

    def test_later_reset_replaces_inherited_completion(self):
        config = self.parse(extra_spec="<waste><reset>0x32 0x00</reset></waste>")
        self.assertNotIn("waste_reset_commit", config["ET-2812/2814"])
        self.assertEqual(config["ET-2812/2814"]["raw_waste_reset"], {50: 0})

    def test_unsupported_close_disables_reset_instead_of_dropping_step(self):
        for close in (
            "<close><raw>unsupported</raw></close>",
            CLOSE.replace("0xFE", "0x1FE"),
            CLOSE.replace("0x100", "0x10000"),
            CLOSE.replace("<write>0x100", "<write>0x101"),
            CLOSE.replace("$byte : $byte", "$other : $byte"),
            CLOSE.replace("&amp;", "|"),
            CLOSE.replace("</var>", "<unexpected/></var>"),
        ):
            with self.subTest(close=close):
                config = normalize_config(self.parse(close=close))
                printer = MemoryPrinter(config=config)
                self.assertIn("waste_reset_commit_error", printer.parm)
                self.assertFalse(printer.reset_waste_ink_levels())
                self.assertEqual(printer.events, [])

    def test_merging_builtin_profile_cannot_hide_unsupported_xml_close(self):
        config = normalize_config(self.parse(close="<close><raw/></close>"))
        # Isolate the built-in table: __init__ expands aliases in place.
        class IsolatedPrinter(MemoryPrinter):
            PRINTER_CONFIG = {"ET-2812": copy.deepcopy(
                EpsonPrinter.PRINTER_CONFIG["ET-2812"]
            )}

        printer = IsolatedPrinter.__new__(IsolatedPrinter)
        EpsonPrinter.__init__(printer, conf_dict=config, model="ET-2814")
        printer.events = []
        self.assertIn("waste_reset_commit_error", printer.parm)
        self.assertFalse(printer.reset_waste_ink_levels())
        self.assertEqual(printer.events, [])


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main()

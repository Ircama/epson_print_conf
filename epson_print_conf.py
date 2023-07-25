#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Epson Printer Configuration accessed via SNMP (TCP/IP)
"""

import itertools
import re
from typing import Any
import datetime
import easysnmp  # pip3 install easysnmp
import time


class EpsonPrinter:
    """SNMP Epson Printer Configuration."""

    PRINTER_MODEL = {  # Known Epson models
        "XP-205": {
            "read_key": [25, 7],
            "write_key": b'Wakatobi',
            "main_waste": {"oids": [24, 25], "divider": 73.5},
            "borderless_waste": {"oids": [26, 27], "divider": 34.34},
            "serial_number": range(192, 202),
            "printer_head_id_h": range(122, 127),
            "printer_head_id_f": [136, 137, 138, 129],
            "stats": {
                "Manual cleaning counter": [[147], "0"],
                "Timer cleaning counter": [[149], "0"],
                "Ink replacement cleaning counter": [[148], "0"],
                "Total print pass counter": [[171, 170, 169, 168], "0"],
                "Total print page counter": [[167, 166, 165, 164], "0"],
                "Total scan counter": [[215, 214, 213, 212], "1"],
                "First TI received time": [[173, 172], "0"]
            },
            "ink_replacement_counters": {
                "Black": { "1B": 242, "1S": 208, "1L": 209},
                "Yellow": { "1B": 248, "1S": 246, "1L": 247},
                "Magenta": { "1B": 251, "1S": 249, "1L": 250},
                "Cyan": { "1B": 245, "1S": 243, "1L": 244},
            },
            "last_printer_fatal_errors": [60, 203, 204, 205, 206],
            "last_printer_fatal_err_ext": [211],
        },
        "L355": {
            "read_key": [65, 9],
            # to be completed
        },
        "L4160": {
            "read_key": [73, 8],
            "write_key": b'Arantifo',
            # to be completed
        },
        "XP-315": {
            "read_key": [129, 8],
            "write_key": b'Wakatobi',
            # to be completed
        },
        "XP-422": {
            "read_key": [85, 5],
            "write_key": b'Muscari.',
            # to be completed
        },
        "XP-435": {
            "read_key": [133, 5],
            "write_key": b'Polyxena',
            # to be completed
        },
        "XP-510": {
            "read_key": [121, 4],
            "write_key": b'Gossypiu',
            # to be completed
        },
        "XP-530": {
            "read_key": [40, 9],
            "write_key": b'Irisgarm',
            # to be completed
        },
        "XP-540": {
            "read_key": [20, 4],
            "write_key": b'Firmiana',

            "addr_waste": range(0x10, 0x16),  # To be changed
            "main_waste": {"oids": [24, 25], "divider": 69},  # To be changed
            "borderless_waste": {"oids": [26, 27], "divider": 32.53},  # To be changed
            # to be completed
        },
        "XP-610": {
            "read_key": [121, 4],
            "write_key": b'Gossypiu',
            # to be completed
        },
        "XP-620": {
            "read_key": [57, 5],
            "write_key": b'Althaea.',
            # to be completed
        },
        "XP-630": {
            "read_key": [40, 9],
            "write_key": b'Irisgarm',  #  (Iris graminea with typo?)
            # to be completed
        },
        "XP-700": {
            "read_key": [40, 0],
            # to be completed
        },
        "XP-760": {
            "read_key": [87, 5],
            # to be completed
        },
        "XP-830": {
            "read_key": [40, 9],
            "write_key": b'Irisgarm',  #  (Iris graminea with typo?)

            "addr_waste": (  # To be changed
                0x10, 0x11,  # '>H' "main pad counter" Max: 0x2102 (8450)
                0x06,
                0x14, 0x15,
                0x12, 0x13,  # '>H' "platen pad counter" Max: 0x0d2a (3370)
                0x06
            ),  # or 0x08?
            "main_waste": {"oids": [24, 25], "divider": 69},   # To be changed
            "borderless_waste": {"oids": [26, 27], "divider": 32.53},   # To be changed
            "idProduct": 0x110b,
            # to be completed
        },
        "XP-850": {
            "read_key": [40, 0],
            "write_key": b'Hibiscus',
            # to be completed
        },
        "XP-7100": {
            "read_key": [40, 5],
            "write_key": b'Leucojum',

            "addr_waste": range(0x10, 0x16),   # To be changed
            "main_waste": {"oids": [24, 25], "divider": 69},   # To be changed
            "borderless_waste": {"oids": [26, 27], "divider": 32.53},   # To be changed
            # to be completed
        },
    }

    snmp_info = {
        "Model": "1.3.6.1.2.1.25.3.2.1.3.1",
        "Model short": "1.3.6.1.4.1.1248.1.1.3.1.3.8.0",
        "EEPS2 firmware version": "1.3.6.1.2.1.2.2.1.2.1",
        "Descr": "1.3.6.1.2.1.1.1.0",
        "UpTime": "1.3.6.1.2.1.1.3.0",
        "Name": "1.3.6.1.2.1.1.5.0",
        "MAC Address": "1.3.6.1.2.1.2.2.1.6.1",
        "Print input": "1.3.6.1.2.1.43.8.2.1.13.1.1",
        "Lang 1": "1.3.6.1.2.1.43.15.1.1.3.1.1",
        "Lang 2": "1.3.6.1.2.1.43.15.1.1.3.1.2",
        "Lang 3": "1.3.6.1.2.1.43.15.1.1.3.1.3",
        "Lang 4": "1.3.6.1.2.1.43.15.1.1.3.1.4",
        "Lang 5": "1.3.6.1.2.1.43.15.1.1.3.1.5",
        "Emulation 1": "1.3.6.1.2.1.43.15.1.1.5.1.1",
        "Emulation 2": "1.3.6.1.2.1.43.15.1.1.5.1.2",
        "Emulation 3": "1.3.6.1.2.1.43.15.1.1.5.1.3",
        "Emulation 4": "1.3.6.1.2.1.43.15.1.1.5.1.4",
        "Emulation 5": "1.3.6.1.2.1.43.15.1.1.5.1.5",
    }

    SNMP_OID_ENTERPRISE = "1.3.6.1.4.1"
    SNMP_EPSON = "1248"
    OID_PRV_CTRL = "1.2.2.44.1.1.2"

    eeprom_link: str = f'{SNMP_OID_ENTERPRISE}.{SNMP_EPSON}.{OID_PRV_CTRL}.1'

    session: object
    printer_model: str
    hostname: str
    parm: dict

    def __init__(
            self,
            printer_model:
            str, hostname: str,
            debug: bool=False,
            dry_run: bool=False) -> None:
        """Initialise printer model."""
        self.printer_model = printer_model
        self.hostname = hostname
        self.debug = debug
        self.dry_run = dry_run
        if self.printer_model in self.valid_printers:
            self.parm = self.PRINTER_MODEL[self.printer_model]
        else:
            self.parm = None
        self.session = EpsonSession(printer=self, debug=debug, dry_run=dry_run)

    @property
    def valid_printers(self):
        """Return list of valid printers."""
        return {
            printer_name
                for printer_name in self.PRINTER_MODEL.keys()
                if "read_key" in self.PRINTER_MODEL[printer_name] and
                "write_key" in self.PRINTER_MODEL[printer_name]
        }

    @property
    def list_methods(self):
        """Return list of available information methods about the printer."""
        return(filter(lambda x: x.startswith("get_") and x not in dir(
            easysnmp.Session), dir(self.session)))

    def stats(self):
        """Return all available information about the printer."""
        stat_set = {}
        for method in self.list_methods:
            ret = self.session.__getattribute__(method)()
            if ret:
                stat_set[method[4:]] = ret
            else:
                if self.debug:
                    print(f"No value for method '{method}'.")
        return stat_set

    def caesar(self, key):
        return ".".join(str(b + 1) for b in key)


class EpsonSession(easysnmp.Session):
    """SNMP session wrapper for Epson printer."""

    def __init__(
        self,
        printer: EpsonPrinter,
        community: str="public",
        version: int=1,
        debug: bool=False,
        dry_run: bool=False
    ) -> None:
        """Initialise session."""
        self.printer = printer
        self.debug = debug
        self.dry_run = dry_run
        super().__init__(
            hostname=self.printer.hostname, community=community, version=version
        )

    def read_eeprom_oid_address(self, oid: int, ext: str="0") -> str:
        """Return address for reading from EEPROM for specified OID."""
        return (
            f"{self.printer.eeprom_link}"
            ".124.124"  # || (0x7C 0x7C)
            ".7.0"  # read
            f".{self.printer.parm['read_key'][0]}"
            f".{self.printer.parm['read_key'][1]}"
            ".65.190.160"
            f".{oid}.{ext}"
        )

    def write_eeprom_oid_address(
            self, oid: int, value: Any, ext: str="0") -> str:
        """Return address for writing to EEPROM for specified OID."""
        write_op = (
            f"{self.printer.eeprom_link}"
            ".124.124"  # || (0x7C 0x7C)
            ".16.0"  # write
            f".{self.printer.parm['read_key'][0]}"
            f".{self.printer.parm['read_key'][1]}"
            ".66.189.33"
            f".{oid}.{ext}.{value}"
            f".{self.printer.caesar(self.printer.parm['write_key'])}"
        )
        if self.dry_run:
            print("WRITE_DRY_RUN:", write_op)
            return self.read_eeprom_oid_address(oid, ext)
        else:
            return write_op

    def read_value(self, oids: str):
        """Return value of OIDs."""
        try:
            value = self.get(oids).value
        except easysnmp.exceptions.EasySNMPTimeoutError as e:
            raise TimeoutError(str(e))
        except Exception as e:
            raise ValueError(str(e))
        return value

    def read_eeprom(self, oid: int, ext: str="0") -> str:
        """Read EEPROM data."""
        response = self.read_value(self.read_eeprom_oid_address(oid, ext))
        if self.debug:
            print(
                "EEPROM_DUMP"
                f": ADDRESS: {self.read_eeprom_oid_address(oid, ext)}"
                f". OID: {oid}"
                f". RESPONSE: {response}"
            )
        response = re.findall(r"EE:[0-9A-F]{6}", response)[0][3:]
        chk_addr = response[2:4]
        value = response[4:6]
        if int(chk_addr, 16) != oid:
            raise ValueError(
                f"Address and response address are"
                f" not equal: {oid} != {chk_addr}"
            )
        return value

    def read_eeprom_many(self, oids: list, ext: str="0"):
        """Read EEPROM data with multiple values."""
        return [self.read_eeprom(oid, ext) for oid in oids]

    def write_eeprom(self, oid: int, value: int) -> None:
        """Write value to OID with specified type to EEPROM."""
        try:
            self.get(self.write_eeprom_oid_address(oid, value))
        except easysnmp.exceptions.EasySNMPTimeoutError as e:
            raise TimeoutError(str(e))
        except Exception as e:
            raise ValueError(str(e))

    def status_parser(self, data):
        """Parse an ST2 status response and decode as much as possible."""
        colour_ids = {
                0x01: 'Black',
                0x03: 'Cyan',
                0x04: 'Magenta',
                0x05: 'Yellow',
                0x06: 'Light Cyan',
                0x07: 'Light Magenta',
                0x0a: 'Light Black',
                0x0b: 'Matte Black',
                0x0f: 'Light Light Black',
                0x10: 'Orange',
                0x11: 'Green',
        }

        status_ids = {
            0: 'Error',
            1: 'Self Printing',
            2: 'Busy',
            3: 'Waiting',
            4: 'Idle',
            5: 'Paused',
            7: 'Cleaning',
            15: 'Nozzle Check',
        }

        if len(data) < 16:
            return "invalid packet"
        if data[:11] != b'\x00@BDC ST2\r\n':
            return "printer status error"
        len_p = int.from_bytes(data[11:13], byteorder='little')
        if len(data) - 13 != len_p:
            return "message error"
        buf = data[13:]
        data_set = {}
        while len(buf):
            if len(buf) < 3:
                return "invalid element"
            (ftype, length) = buf[:2]
            buf = buf[2:]
            item = buf[:length]
            if len(item) != length:
                return "invalid element length"
            buf = buf[length:]

            if self.debug:
                print("Processing status. ftype", hex(ftype),
                "length:", length, "item:", item, "buf:", buf)

            if ftype == 0x0f:  # ink
                colourlen = item[0]
                offset = 1
                inks = []
                while offset < length:
                    colour = item[offset]
                    level = item[offset+2]
                    offset += colourlen

                    if colour in colour_ids:
                        name = colour_ids[colour]
                    else:
                        name = "0x%X" % colour
                    
                    inks.append((colour, level, name))

                data_set["ink_level"] = inks

            elif ftype == 0x0d:  # maintenance tanks
                (tank1, tank2) = item[0:2]
                data_set["tanks"] = (tank1, tank2)

            elif ftype == 0x19:  # current job name
                data_set["jobname"] = item
                if item == b'\x00\x00\x00\x00\x00unknown':
                    data_set["jobname"] = "Not defined"

            elif ftype == 0x1f:  # serial
                data_set["serial"] = str(item)

            elif ftype == 0x01:  # status
                printer_status = item[0]
                status_text = "unknown"
                if printer_status in status_ids:
                    status_text = status_ids[printer_status]
                else:
                    status_text = 'unknown: %d' % printer_status
                if printer_status == 3 or printer_status == 4:
                    data_set["ready"] = True
                else:
                    data_set["ready"] = False
                data_set["status"] = (printer_status, status_text)

            elif ftype == 0x02:  # errcode
                data_set["errcode"] = item

            elif ftype == 0x03:  # Self print code
                data_set["self_print_code"] = item

            elif ftype == 0x04:  # warning
                data_set["warning_code"] = item

            elif ftype == 0x06:  # Paper path
                data_set["paper_path"] = item
                if item == b'\x01\xff':
                    data_set["paper_path"] = "Cut sheet (Rear)"

            elif ftype == 0x0e:  # Replace cartridge information
                data_set["replace_cartridge"] = "{:08b}".format(item[0])

            elif ftype == 0x10:  # Loading path information
                data_set["loading_path"] = item.hex().upper()
                if data_set["loading_path"] == "01094E":
                    data_set["loading_path"] = "fixed"

            elif ftype == 0x13:  # Cancel code
                data_set["cancel_code"] = item
                if item == b'\x01':
                    data_set["cancel_code"] = "No request"
                if item == b'\xA1':
                    data_set["cancel_code"] = (
                        "Received cancel command and printer initialization"
                    )
                if item == b'\x81':
                    data_set["cancel_code"] = "Request"

            elif ftype == 0x37: # Maintenance box information
                i = 1
                for j in range(item[0]):
                    if item[i] == 0:
                        data_set[f"maintenance_box_{j}"] = (
                            f"not full ({item[i + 1]})"
                        )
                    elif item[i] == 1:
                        data_set[f"maintenance_box_{j}"] = (
                            f"near full ({item[i + 1]})"
                        )
                    elif item[i] == 2:
                        data_set[f"maintenance_box_{j}"] = (
                            f"full ({item[i + 1]})"
                        )
                    else:
                        data_set[f"maintenance_box_{j}"] = (
                            f"unknown ({item[i + 1]})"
                        )
                    i += 2

            else:  # unknown stuff
                if "unknown" not in data_set:
                    data_set["unknown"] = []
                data_set["unknown"].append((hex(ftype), item))
        return data_set

    def get_snmp_info(self, mib_name: str=None) -> str:
        """Return general SNMP information of printer."""
        sys_info = {}
        if mib_name and mib_name in self.printer.snmp_info.keys():
            snmp_info = { mib_name: self.printer.snmp_info[mib_name] }
        else:
            snmp_info = self.printer.snmp_info
        for name, oid in snmp_info.items():
            try:
                sys_info[name] = self.read_value(oid)
            except Exception:
                if self.debug:
                    print(f"No value for SNMP OID '{name}'.")
        if "UpTime" in sys_info:
            sys_info["UpTime"] = time.strftime(
                '%H:%M:%S', time.gmtime(int(sys_info["UpTime"])/100))
        if "MAC Address" in sys_info:
            sys_info["MAC Address"] = bytes(
                [ord(i) for i in sys_info["MAC Address"]]).hex("-").upper()
        return sys_info

    def get_serial_number(self) -> str:
        """Return serial number of printer."""
        if "serial_number" not in self.printer.parm:
            return None
        return "".join(
            chr(int(value, 16))
            for value in self.read_eeprom_many(
                self.printer.parm["serial_number"])
        )

    def get_stats(self) -> str:
        """Return printer statistics."""
        if "stats" not in self.printer.parm:
            return None
        stats_result = {}
        for stat_name, oids in self.printer.parm["stats"].items():
            total = 0
            for val in self.read_eeprom_many(oids[0], oids[1]):
                total = (total << 8) + int(val, 16)
            stats_result[stat_name] = total
        ftrt = stats_result["First TI received time"]
        year = 2000 + ftrt // (16 * 32)
        month = (ftrt - (year - 2000) * (16 * 32)) // 32
        day = (ftrt - (year - 2000) * (16 * 32)) // 16
        stats_result["First TI received time"] = datetime.datetime(
            year, month, day).strftime('%d %b %Y')
        return stats_result

    def get_printer_head_id(self) -> str:  # to be revised
        """Return printer head id."""
        if "printer_head_id_h" not in self.printer.parm:
            return None
        if "printer_head_id_f" not in self.printer.parm:
            return None
        a = self.read_eeprom_many(self.printer.parm["printer_head_id_h"])
        b = self.read_eeprom_many(self.printer.parm["printer_head_id_f"])
        return(f'{"".join(a)} - {"".join(b)}')

    def get_firmware_version(self) -> str:
        """Return firmware version."""
        firmware_string = self.read_value(
            f"{self.printer.eeprom_link}.118.105.1.0.0")
        if not firmware_string:
            return None
        firmware = re.sub(r".*vi:00:(.{6}).*", r'\g<1>', firmware_string)
        year = ord(firmware[4:5]) + 1945
        month = int(firmware[5:], 16)
        day = int(firmware[2:4])
        return firmware + " " + datetime.datetime(
            year, month, day).strftime('%d %b %Y')

    def get_cartridges(self) -> str:
        """Return list of cartridge types."""
        cartridges_string = self.read_value(
            f"{self.printer.eeprom_link}.105.97.1.0.0")
        if not cartridges_string:
            return None
        cartridges = re.sub(
            r".*IA:00;(.*);.*", r'\g<1>', cartridges_string, flags=re.S)
        return [i.strip() for i in cartridges.split(',')]

    def get_ink_replacement_counters(self) -> str:
        """Return list of ink replacement counters."""
        if "ink_replacement_counters" not in self.printer.parm:
            return None
        irc = {
            (color, counter, int(self.read_eeprom(value), 16))
                for color, data in self.printer.parm[
                        "ink_replacement_counters"].items()
                    for counter, value in data.items()
        }
        return irc

    def get_printer_status(self):
        """Return printer status and ink levels."""
        result = self.read_value(f"{self.printer.eeprom_link}.115.116.1.0.1")
        if not result:
            return None
        if self.debug:
            print("PRINTER_STATUS", bytes([ord(i) for i in result]).hex(" "))
        return self.status_parser(bytes([ord(i) for i in result]))

    def get_waste_ink_levels(self):
        """Return waste ink levels as a percentage."""
        if "main_waste" not in self.printer.parm:
            return None
        results = []
        
        level = self.read_eeprom_many(self.printer.parm["main_waste"]["oids"])
        level_b10 = int("".join(reversed(level)), 16)
        results.append(
            round(level_b10 / self.printer.parm["main_waste"]["divider"],
            2)
        )

        if "borderless_waste" in self.printer.parm:
            level = self.read_eeprom_many(
                self.printer.parm["borderless_waste"]["oids"])
            level_b10 = int("".join(reversed(level)), 16)
            results.append(round(level_b10 / self.printer.parm[
                "borderless_waste"]["divider"], 2))

        return results

    def get_last_printer_fatal_errors(self) -> str:
        """Return list of last printer fatal errors in hex format."""
        if "last_printer_fatal_errors" not in self.printer.parm:
            return None
        err = self.read_eeprom_many(
            self.printer.parm["last_printer_fatal_errors"])
        if "last_printer_fatal_err_ext" in self.printer.parm:
            err.extend(self.read_eeprom_many(
                self.printer.parm["last_printer_fatal_err_ext"], "1"))
        return err

    def dump_eeprom(self, ext: str="0", start: int = 0, end: int = 0xFF):
        """
        Dump EEPROM data from start to end (less significant byte).
        ext = most significant byte
        """
        d = {}
        for oid in range(start, end):
            d[oid] = int(self.read_eeprom(oid, ext), 16)
        return d

    def reset_waste_ink_levels(self) -> None:
        """
        Set waste ink levels to 0.
        """
        for oid in self.printer.parm["main_waste"]["oids"] + self.printer.parm[
                "borderless_waste"]["oids"]:
            self.write_eeprom(oid, 0)

    def write_first_ti_received_time(
            self, year: int, month: int, day: int) -> None:
        """Update first TI received time"""
        b = self.printer.parm["stats"]["First TI received time"][0][0]
        l = self.printer.parm["stats"]["First TI received time"][0][1]
        n = (year - 2000) * 16 * 32 + 32 * month + day
        if self.debug:
            print("FTRT:", hex(n // 256), hex(n % 256))
        self.write_eeprom(b, n // 256)
        self.write_eeprom(l, n % 256)

    def brute_force_read_key(
        self, minimum: int = 0x00, maximum: int = 0xFF
    ):
        """Brute force read_key for printer."""
        for x, y in itertools.permutations(range(minimum, maximum), r=2):
            self.printer.parm['read_key'] = [x, y]
            print(f"Trying {self.printer.parm['read_key']}...")
            try:
                self.read_eeprom(0x00)
                print(f"read_key found: {self.printer.parm['read_key']}")
                return self.printer.parm['read_key']
            except IndexError:
                continue
            except KeyboardInterrupt:
                return None
        return None


if __name__ == "__main__":
    import argparse
    from pprint import pprint


    parser = argparse.ArgumentParser(
        epilog='Epson Printer Configuration accessed via SNMP (TCP/IP)')

    parser.add_argument(
        '-m',
        '--model',
        dest='model',
        action="store",
        help='Printer model. Example: -m XP-205'
            ' (use ? to print all supported models)',
        required=True)
    parser.add_argument(
        '-a',
        '--address',
        dest='hostname',
        action="store",
        help='Printer host name or IP address. (Example: -m 192.168.1.87)',
        required=True)
    parser.add_argument(
        '-i',
        '--info',
        dest='info',
        action='store_true',
        help='Print all available information and statistics (default option)')
    parser.add_argument(
        '-q',
        '--query',
        dest='query',
        action='store',
        type=str,
        nargs=1,
        help='Print specific information.'
            ' (Use ? to list all available queries)')
    parser.add_argument(
        '--reset_waste_ink',
        dest='reset_waste_ink',
        action='store_true',
        help='Reset all waste ink levels to 0')
    parser.add_argument(
        "--brute-force-read-key",
        dest='brute_force',
        action='store_true',
        help="Detect the read_key via brute force")
    parser.add_argument(
        '-d',
        '--debug',
        dest='debug',
        action='store_true',
        help='Print debug information')
    parser.add_argument(
        '-e',
        '--eeprom-dump',
        dest='dump_eeprom',
        action='store',
        type=int,
        nargs=3,
        help='Dump EEPROM (arguments: extension, start, stop)')
    parser.add_argument(
        '--dry-run',
        dest='dry_run',
        action='store_true',
        help='Dry-run change operations')
    parser.add_argument(
        '--write-first-ti-received-time',
        dest='ftrt',
        type=int,
        help='Change the first TI received time (arguments: year, month, day)',
        nargs=3,
    )
    args = parser.parse_args()

    printer = EpsonPrinter(
        args.model, args.hostname, debug=args.debug, dry_run=args.dry_run)
    if not printer.parm:
        print("Unknown printer. Valid printers:", ", ".join(
            printer.valid_printers))
        quit(1)
    print_opt = False
    try:
        if args.reset_waste_ink:
            print_opt = True
            printer.session.reset_waste_ink_levels()
        if args.brute_force:
            print_opt = True
            printer.session.brute_force_read_key()
        if args.ftrt:
            print_opt = True
            printer.session.write_first_ti_received_time(
                int(args.ftrt[0]), int(args.ftrt[1]), int(args.ftrt[2]))
        if args.dump_eeprom:
            print_opt = True
            for addr, val in printer.session.dump_eeprom(
                        str(args.dump_eeprom[0] % 256),
                        args.dump_eeprom[1] % 256,
                        int(args.dump_eeprom[2] % 256 + 1)
                    ).items():
                print(f"{str(addr).rjust(3)}: {val:#04x} = {str(val).rjust(3)}")
        if args.query:
            print_opt = True
            if args.query[0] in printer.snmp_info.keys():
                ret = printer.session.get_snmp_info(args.query[0])
                if ret:
                    pprint(ret)
                else:
                    print("No information returned. Check printer definition.")
            else:
                if args.query[0].startswith("get_"):
                    method = args.query[0]
                else:
                    method = "get_" + args.query[0]
                if method in printer.list_methods:
                    ret = printer.session.__getattribute__(method)()
                    if ret:
                        pprint(ret)
                    else:
                        print("No information returned."
                            " Check printer definition.")
                else:
                    print(
                        "Option error: unavailable query.\nAvailable queries:",
                        ", ".join(printer.list_methods),
                        "\nAvailable SNMP elements:",
                        ", ".join(printer.snmp_info.keys())
                    )
        if args.info or not print_opt:
            ret = printer.stats()
            if ret:
                pprint(ret)
            else:
                print("No information returned. Check printer definition.")
    except TimeoutError as e:
        print(f"Timeout error: {str(e)}")
    except ValueError as e:
        raise(f"Generic error: {str(e)}")
    except KeyboardInterrupt:
        quit(2)

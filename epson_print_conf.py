#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Epson Printer Configuration via SNMP (TCP/IP)
"""

import itertools
import re
from typing import Any
import datetime
import time
import textwrap
import ast
from pysnmp.hlapi.v1arch import *


class EpsonPrinter:
    """SNMP Epson Printer Configuration."""

    PRINTER_CONFIG = {  # Known Epson models
        "XP-205": {
            "alias": ["XP-200", "XP-207"],
            "read_key": [25, 7],
            "write_key": b'Wakatobi',
            "main_waste": {"oids": [24, 25, 30], "divider": 73.5},
            "borderless_waste": {"oids": [26, 27, 34], "divider": 34.34},
            "serial_number": range(192, 202),
            "printer_head_id_h": range(122, 127),
            "printer_head_id_f": [136, 137, 138, 129],
            "stats": {
                "Manual cleaning counter": [147],
                "Timer cleaning counter": [149],
                "Ink replacement cleaning counter": [148],
                "Total print pass counter": [171, 170, 169, 168],
                "Total print page counter": [167, 166, 165, 164],
                "Total scan counter": [0x01d7, 0x01d6, 0x01d5, 0x01d4],
                "First TI received time": [173, 172],
                "Maintenance required level of 1st waste ink counter": [46],
                "Maintenance required level of 2nd waste ink counter": [47],
            },
            "raw_waste_reset": {
                24: 0, 25: 0, 30: 0,  # Data of 1st counter
                28: 0, 29: 0,  # another store of 1st counter
                46: 94,  # Maintenance required level of 1st counter
                26: 0, 27: 0, 34: 0,  # Data of 2nd counter
                47: 94,  # Maintenance required level of 2st counter
                49: 0  # ?
            },
            "ink_replacement_counters": {
                "Black": {"1B": 242, "1S": 208, "1L": 209},
                "Yellow": {"1B": 248, "1S": 246, "1L": 247},
                "Magenta": {"1B": 251, "1S": 249, "1L": 250},
                "Cyan": {"1B": 245, "1S": 243, "1L": 244},
            },
            "last_printer_fatal_errors": [60, 203, 204, 205, 206, 0x01d3],
        },
        "Stylus Photo PX730WD": {
            "alias": ["Epson Artisan 730"],
            "read_key": [0x8, 0x77],
            "write_key": b'Cattleya',
            "main_waste": {"oids": [0xe, 0xf], "divider": 81.82},
            "borderless_waste": {"oids": [0x10, 0x11], "divider": 122.88},
            "stats": {
                "Manual cleaning counter": [0x7e],
                "Timer cleaning counter": [0x61],
                "Total print pass counter": [0x2C, 0x2D, 0x2E, 0x2F],
                "Total print page counter": [0x9E, 0x9F],
                "Total print page counter (duplex)": [0xA0, 0xA1],
                "Total print CD-R counter": [0x4A, 0x4B],
                "Total print CD-R tray open/close counter": [0xA2, 0xA3],
                "Total scan counter": [0x01DA, 0x01DB, 0x01DC, 0x01DD],
            },
            "last_printer_fatal_errors": [0x3B, 0xC0, 0xC1, 0xC2, 0xC3, 0x5C],
            "ink_replacement_counters": {
                "Black": {"1S": 0x66, "2S": 0x67, "3S": 0x62},
                "Yellow": {"1S": 0x70, "2S": 0x71, "3S": 0xAB},
                "Magenta": {"1S": 0x68, "2S": 0x69, "3S": 0x63},
                "Cyan": {"1S": 0x6C, "2S": 0x6D, "3S": 0x65},
                "Light magenta": {"1S": 0x6A, "2S": 0x6B, "3S": 0x64},
                "Light cyan": {"1S": 0x6E, "2S": 0x6F, "3S": 0x9B},
            },
            "serial_number": range(0xE7, 0xF0),
            # untested
        },
        "WF-7525": {
            "read_key": [101, 0],
            "write_key": b'Sasanqua',
            "main_waste": {"oids": [20, 21], "divider": 196.5},
            "borderless_waste": {"oids": [22, 23], "divider": 52.05},
            "serial_number": range(192, 202),
            "stats": {
                "Maintenance required level of 1st waste ink counter": [60],
                "Maintenance required level of 2nd waste ink counter": [61],
            },
            "raw_waste_reset": {
                20: 0, 21: 0, 22: 0, 23: 0, 24: 0, 25: 0, 59: 0, 60: 94, 61: 94
            }
            # to be completed
        },
        "L355": {
            "read_key": [65, 9],
            # to be completed
        },
        "L3250": {
            "read_key": [74, 54],
            "write_key": b'Maribaya',
            "serial_number": range(68, 78),
            "main_waste": {"oids": [48, 49], "divider": 63.45},
            "second_waste": {"oids": [50, 51], "divider": 34.13},
            "third_waste": {"oids": [252, 253], "divider": 13},
            "raw_waste_reset": {
                48: 0, 49: 0, 50: 0, 51: 0, 252: 0, 253: 0
            }
            # to be completed
        },
        "L3160": {
            "read_key": [151, 7],
            "write_key": b'Maribaya',
            "stats": {
                "Maintenance required level of 1st waste ink counter": [54],
                "Maintenance required level of 2nd waste ink counter": [55],
            },
            "raw_waste_reset": {
                48: 0, 49: 0, 47: 0, 52: 0, 53: 0,
                54: 94, 50: 0, 51: 0, 55: 94, 28: 0
            }
            # to be completed
        },
        "L4160": {
            "read_key": [73, 8],
            "write_key": b'Arantifo',
            "stats": {
                "Maintenance required level of 1st waste ink counter": [54],
                "Maintenance required level of 2nd waste ink counter": [55],
            },
            "raw_waste_reset": {
                48: 0, 49: 0, 47: 0, 52: 0, 53: 0,
                54: 94, 50: 0, 51: 0, 55: 94, 28: 0
            }
            # to be completed
        },
        "XP-315": {
            "read_key": [129, 8],
            "write_key": b'Wakatobi',
            "main_waste": {"oids": [24, 25, 30], "divider": 196.5},
            "borderless_waste": {"oids": [26, 27, 34], "divider": 52.05},
            "stats": {
                "Maintenance required level of 1st waste ink counter": [46],
                "Maintenance required level of 2nd waste ink counter": [47],
            },
            "raw_waste_reset": {
                24: 0, 25: 0, 30: 0,  # Data of 1st counter
                28: 0, 29: 0,  # another store of 1st counter
                46: 94,  # Maintenance required level of 1st counter
                26: 0, 27: 0, 34: 0,  # Data of 2nd counter
                47: 94,  # Maintenance required level of 2st counter
                49: 0  # ?
            }
            # to be completed
        },
        "XP-422": {
            "read_key": [85, 5],
            "write_key": b'Muscari.',
            # to be completed
            "main_waste": {"oids": [24, 25, 30], "divider": 196.5},
            "borderless_waste": {"oids": [26, 27, 34], "divider": 52.05},
            "stats": {
                "Maintenance required level of 1st waste ink counter": [46],
                "Maintenance required level of 2nd waste ink counter": [47],
            },
            "raw_waste_reset": {
                24: 0, 25: 0, 26: 0, 27: 0, 28: 0,
                29: 0, 30: 0, 34: 0, 46: 94, 47: 94, 49: 0
            }
        },
        "XP-435": {
            "read_key": [133, 5],
            "write_key": b'Polyxena',
            # to be completed
        },
        "XP-540": {
            "read_key": [20, 4],
            "write_key": b'Firmiana',
            "main_waste": {"oids": [0x10, 0x11], "divider": 84.5},  # To be changed
            "borderless_waste": {"oids": [0x12, 0x13], "divider": 33.7},  # To be changed
            # to be completed
        },
        "XP-610": {
            "alias": ["XP-611", "XP-615", "XP-510"],
            "read_key": [121, 4],
            "write_key": b'Gossypiu',
            "main_waste": {"oids": [16, 17], "divider": 84.5},  # divider to be changed
            "borderless_waste": {"oids": [18, 19], "divider": 33.7},  # divider to be changed
            # to be completed
        },
        "XP-620": {
            "read_key": [57, 5],
            "write_key": b'Althaea.',
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
            "alias": ["XP-530", "XP-630", "XP-635"],
            "read_key": [40, 9],
            "write_key": b'Irisgarm',  # (Iris graminea with typo?)
            "main_waste": {"oids": [0x10, 0x11], "divider": 84.5},  # To be changed
            "borderless_waste": {"oids": [0x12, 0x13], "divider": 33.7},  # To be changed
            "idProduct": 0x110b,
            # to be completed
        },
        "XP-850": {
            "read_key": [40, 0],
            "write_key": b'Hibiscus',
            "main_waste": {"oids": [16, 17], "divider": 84.5},  # divider to be changed
            "borderless_waste": {"oids": [18, 19], "divider": 33.7},  # divider to be changed
            # to be completed
        },
        "XP-7100": {
            "read_key": [40, 5],
            "write_key": b'Leucojum',
            "main_waste": {"oids": [0x10, 0x11], "divider": 84.5},  # To be changed
            "borderless_waste": {"oids": [0x12, 0x13], "divider": 33.7},  # To be changed
            # to be completed
        },
        "ET-2500": {
            "read_key": [68, 1],
            "write_key": b'Gerbera*',
            "stats": {
                "Maintenance required level of waste ink counter": [46],
            },
            "raw_waste_reset": {24: 0, 25: 0, 30: 0, 28: 0, 29: 0, 46: 94}
            # to be completed
        },
        "XP-3150": {
            "read_key": [80, 9],
            "stats": {
                "Total print page counter": [133, 132, 131, 130],
            },
            # draft
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
        "Print counter": "1.3.6.1.2.1.43.10.2.1.4.1.1",
        "IP Address": "1.3.6.1.4.1.1248.1.1.3.1.4.19.1.3.1",
        "URL_path": "1.3.6.1.4.1.1248.1.1.3.1.4.19.1.4.1",
        "URL": "1.3.6.1.4.1.1248.1.1.3.1.4.46.1.2.1",
        "WiFi": "1.3.6.1.4.1.1248.1.1.3.1.29.2.1.9.0",
        "hex_data": "1.3.6.1.4.1.1248.1.1.3.1.1.5.0",
        "device_id": "1.3.6.1.4.1.11.2.3.9.1.1.7.0",
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
            timeout: (None, float) = None,
            retries: (None, float) = None,
            debug: bool = False,
            dry_run: bool = False) -> None:
        """Initialise printer model."""
        for printer_name, printer_data in self.PRINTER_CONFIG.copy().items():
            if "alias" in printer_data:
                aliases = printer_data["alias"]
                del printer_data["alias"]
                for alias_name in aliases:
                    if alias_name in self.PRINTER_CONFIG:
                        self.PRINTER_CONFIG[alias_name] = {
                            **printer_data, **self.PRINTER_CONFIG[alias_name]
                        }
                    else:
                        self.PRINTER_CONFIG[alias_name] = printer_data
        self.printer_model = printer_model
        self.hostname = hostname
        self.timeout = timeout
        self.retries = retries
        self.debug = debug
        self.dry_run = dry_run
        if self.printer_model in self.valid_printers:
            self.parm = self.PRINTER_CONFIG[self.printer_model]
        else:
            self.parm = None

    @property
    def valid_printers(self):
        """Return list of defined printers."""
        return {
            printer_name
            for printer_name in self.PRINTER_CONFIG.keys()
            if "read_key" in self.PRINTER_CONFIG[printer_name]
        }

    @property
    def list_methods(self):
        """Return list of available information methods about a printer."""
        return(filter(lambda x: x.startswith("get_"), dir(self)))

    def stats(self):
        """Return all available information about a printer."""
        stat_set = {}
        for method in self.list_methods:
            ret = self.__getattribute__(method)()
            if ret:
                stat_set[method[4:]] = ret
            else:
                if self.debug:
                    print(f"No value for method '{method}'.")
        return stat_set

    def caesar(self, key):
        """Convert the string write key to a sequence of numbers"""
        return ".".join(str(b + 1) for b in key)

    def eeprom_oid_read_address(
            self,
            oid: int,
            msb: int = 0,
            label: str = "unknown method") -> str:
        """
        Return the OID string to read the value of the EEPROM address 'oid'.
        oid can be a number between 0x0000 and 0xffff.
        Return None in case of error.
        """
        if oid > 255:
            msb = oid // 256
            oid = oid % 256
        if msb > 255:
            return None
        if 'read_key' not in self.parm:
            return None
        return (
            f"{self.eeprom_link}"
            ".124.124"  # || (0x7C 0x7C)
            ".7.0"  # read
            f".{self.parm['read_key'][0]}"
            f".{self.parm['read_key'][1]}"
            ".65.190.160"
            f".{oid}.{msb}"
        )

    def eeprom_oid_write_address(
            self,
            oid: int,
            value: Any,
            msb: int = 0,
            label: str = "unknown method") -> str:
        """
        Return the OID string to write a value to the EEPROM address 'oid'.
        oid can be a number between 0x0000 and 0xffff.
        Return None in case of error.
        """
        if oid > 255:
            msb = oid // 256
            oid = oid % 256
        if msb > 255:
            return None
        if ('write_key' not in self.parm
                or 'read_key' not in self.parm):
            return None
        write_op = (
            f"{self.eeprom_link}"
            ".124.124"  # || (0x7C 0x7C)
            ".16.0"  # write
            f".{self.parm['read_key'][0]}"
            f".{self.parm['read_key'][1]}"
            ".66.189.33"
            f".{oid}.{msb}.{value}"
            f".{self.caesar(self.parm['write_key'])}"
        )
        if self.dry_run:
            print("WRITE_DRY_RUN:", write_op)
            return self.eeprom_oid_read_address(oid, label=label)
        else:
            return write_op

    def snmp_mib(self, mib):
        """Generic SNMP query, returning value of a MIB."""
        utt = UdpTransportTarget(
                (self.hostname, 161),
            )
        if self.timeout is not None:
            utt.timeout = self.timeout
        if self.retries is not None:
            utt.retries = self.retries
        iterator = getCmd(
            SnmpDispatcher(),
            CommunityData('public', mpModel=0),
            utt,
            (mib, None)
        )
        for response in iterator:
            errorIndication, errorStatus, errorIndex, varBinds = response
            if errorIndication:
                if self.debug:
                    print("snmp_mib error", errorIndication)
                return False
            elif errorStatus:
                if self.debug:
                    print(
                        'snmp_mib error: %s at %s' % (
                        errorStatus.prettyPrint(),
                        errorIndex and varBinds[int(errorIndex) - 1][0] or '?')
                    )
                return False
            else:
                for varBind in varBinds:
                    try:
                        return "".join(
                            [chr(x) for x in varBind[1].asNumbers()])
                    except Exception:
                        return varBind[1].prettyPrint()
            if self.debug:
                print("snmp_mib error: invalid multiple data")
            return False
        if self.debug:
            print("snmp_mib error: invalid multiple data")
        return False

    def read_eeprom(
            self,
            oid: int,
            label: str = "unknown method") -> str:
        """Read a single byte from the Epson EEPROM address 'oid'."""
        if self.debug:
            print(
                f"EEPROM_DUMP {label}:\n"
                f"  ADDRESS: "
                f"{self.eeprom_oid_read_address(oid, label=label)}\n"
                f"  OID: {oid}={hex(oid)}"
            )
        response = self.snmp_mib(
            self.eeprom_oid_read_address(oid, label=label))
        if self.debug:
            print(f"  RESPONSE: {repr(response)}")
        try:
            response = re.findall(r"EE:[0-9A-F]{6}", response)[0][3:]
        except (TypeError, IndexError):
            if self.debug:
                print(f"Invalid read key.")
            return None
        chk_addr = response[0:4]
        value = response[4:6]
        if int(chk_addr, 16) != oid:
            raise ValueError(
                f"Address and response address are"
                f" not equal: {oid} != {chk_addr}"
            )
        return value

    def read_eeprom_many(
            self,
            oids: list,
            label: str = "unknown method"):
        """
        Read a list of bytes from the list of Epson EEPROM addresses 'oids'.
        """
        return [self.read_eeprom(oid, label=label) for oid in oids]

    def write_eeprom(
            self,
            oid: int,
            value: int,
            label: str = "unknown method") -> None:
        """Write a single byte 'value' to the Epson EEPROM address 'oid'."""
        if "write_key" not in self.parm:
            if self.debug:
                print(f"Missing 'write_key' parameter in configuration.")
            return False
        if not self.dry_run and self.debug:
            response = self.read_eeprom(oid, label=label)
            print(f"Previous value for {label}: {response}")
        oid_string = self.eeprom_oid_write_address(oid, value, label=label)
        response = None
        try:
            response = self.get(oid_string)
        except easysnmp.exceptions.EasySNMPTimeoutError as e:
            if not self.dry_run:
                raise TimeoutError(str(e))
        except Exception as e:
            raise ValueError(str(e))
        if self.debug:
            print(
                f"EEPROM_WRITE {label}:\n"
                f"  ADDRESS: {oid_string}\n"
                f"  OID: {oid}={hex(oid)}"
            )
        if self.debug and response:
            print(f"  RESPONSE: {repr(response.value)}")
        if response and not ":OK;" in repr(response.value):  # ":NA;" is an error
            return False
        return True

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
                print(
                    "Processing status - ftype", hex(ftype),
                    "length:", length, "item:", item.hex(' ')
                )

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

            elif ftype == 0x37:  # Maintenance box information
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

    def get_snmp_info(self, mib_name: str = None) -> str:
        """Return general SNMP information of printer."""
        sys_info = {}
        if mib_name and mib_name in self.snmp_info.keys():
            snmp_info = {mib_name: self.snmp_info[mib_name]}
        else:
            snmp_info = self.snmp_info
        for name, oid in snmp_info.items():
            try:
                sys_info[name] = self.snmp_mib(oid)
            except Exception as e:
                if self.debug:
                    print(
                        f"No value for SNMP OID '{name}'. "
                        f"MIB: {oid}. Error: {e}"
                )
        if "hex_data" in sys_info and sys_info["hex_data"] is not False:
            sys_info["hex_data"] = bytes(
                [ord(i) for i in sys_info["hex_data"]]).hex(" ").upper()
        if "UpTime" in sys_info and sys_info["UpTime"] is not False:
            sys_info["UpTime"] = time.strftime(
                '%H:%M:%S', time.gmtime(int(sys_info["UpTime"])/100))
        if "MAC Address" in sys_info and sys_info["MAC Address"] is not False:
            sys_info["MAC Address"] = bytes(
                [ord(i) for i in sys_info["MAC Address"]]).hex("-").upper()
        return sys_info

    def get_serial_number(self) -> str:
        """Return serial number of printer."""
        if "serial_number" not in self.parm:
            return None
        return "".join(
            chr(int(value or "0", 16))
            for value in self.read_eeprom_many(
                self.parm["serial_number"], label="serial_number")
        )

    def get_stats(self, stat_name: str = None) -> str:
        """Return printer statistics."""
        if "stats" not in self.parm:
            return None
        if stat_name and stat_name in self.parm["stats"].keys():
            stat_info = {stat_name: self.parm["stats"][stat_name]}
        else:
            stat_info = self.parm["stats"]
        stats_result = {}
        for stat_name, oids in stat_info.items():
            total = 0
            for val in self.read_eeprom_many(oids, label=stat_name):
                if val is None:
                    return None
                total = (total << 8) + int(val, 16)
            stats_result[stat_name] = total
        ftrt = stats_result["First TI received time"]
        year = 2000 + ftrt // (16 * 32)
        month = (ftrt - (year - 2000) * (16 * 32)) // 32
        day = ftrt - (year - 2000) * 16 * 32 - 32 * month
        stats_result["First TI received time"] = datetime.datetime(
            year, month, day).strftime('%d %b %Y')
        return stats_result

    def get_printer_head_id(self) -> str:  # to be revised
        """Return printer head id."""
        if "printer_head_id_h" not in self.parm:
            return None
        if "printer_head_id_f" not in self.parm:
            return None
        a = self.read_eeprom_many(
            self.parm["printer_head_id_h"], label="printer_head_id_h")
        b = self.read_eeprom_many(
            self.parm["printer_head_id_f"], label="printer_head_id_f")
        if (
            a == [None, None, None, None, None]
            or b == [None, None, None, None, None]
        ):
            return None
        return(f'{"".join(a)} - {"".join(b)}')

    def get_firmware_version(self) -> str:
        """Return firmware version."""
        firmware_string = self.snmp_mib(
            f"{self.eeprom_link}.118.105.1.0.0")
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
        cartridges_string = self.snmp_mib(
            f"{self.eeprom_link}.105.97.1.0.0")
        if not cartridges_string:
            return None
        cartridges = re.sub(
            r".*IA:00;(.*);.*", r'\g<1>', cartridges_string, flags=re.S)
        return [i.strip() for i in cartridges.split(',')]

    def get_ink_replacement_counters(self) -> str:
        """Return list of ink replacement counters."""
        if "ink_replacement_counters" not in self.parm:
            return None
        irc = {
            (
                color,
                counter,
                int(
                    self.read_eeprom(
                        value, label="ink_replacement_counters") or "-1", 16
                ),
            )
            for color, data in self.parm[
                "ink_replacement_counters"].items()
            for counter, value in data.items()
        }
        return irc

    def get_printer_status(self):
        """Return printer status and ink levels."""
        result = self.snmp_mib(f"{self.eeprom_link}.115.116.1.0.1")
        if not result:
            return None
        if self.debug:
            print(
                textwrap.fill(
                    "PRINTER_STATUS: " + bytes(
                        [ord(i) for i in result]).hex(" "),
                    initial_indent="",
                    subsequent_indent="    ",
                )
            )
        return self.status_parser(bytes([ord(i) for i in result]))

    def get_waste_ink_levels(self):
        """Return waste ink levels as a percentage."""
        if "main_waste" not in self.parm:
            return None
        results = {}
        for waste_type in ["main_waste", "borderless_waste", "first_waste",
                "second_waste", "third_waste"]:
            if waste_type not in self.parm:
                continue
            level = self.read_eeprom_many(
                self.parm[waste_type]["oids"], label=waste_type)
            if level == [None, None, None]:
                return None
            level_b10 = int("".join(reversed(level)), 16)
            results[waste_type] = round(
                level_b10 / self.parm[waste_type]["divider"], 2)
        return results

    def get_last_printer_fatal_errors(self) -> str:
        """Return list of last printer fatal errors in hex format."""
        if "last_printer_fatal_errors" not in self.parm:
            return None
        return self.read_eeprom_many(
            self.parm["last_printer_fatal_errors"],
            label="last_printer_fatal_errors"
        )

    def dump_eeprom(self, start: int = 0, end: int = 0xFF):
        """
        Dump EEPROM data from start to end (less significant byte).
        """
        d = {}
        for oid in range(start, end + 1):
            d[oid] = int(self.read_eeprom(oid, label="dump_eeprom"), 16)
        return d

    def reset_waste_ink_levels(self) -> bool:
        """
        Set waste ink levels to 0.
        """
        if "raw_waste_reset" in self.parm:
            for oid, value in self.parm["raw_waste_reset"].items():
                if not self.write_eeprom(oid, value, label="raw_waste_reset"):
                    return False
            return True
        if "main_waste" not in self.parm:
            return None
        for oid in self.parm["main_waste"]["oids"]:
            if not self.write_eeprom(oid, 0, label="main_waste"):
                return False
        if "borderless_waste" not in self.parm:
            return True
        for oid in self.parm["borderless_waste"]["oids"]:
            if not self.write_eeprom(oid, 0, label="borderless_waste"):
                return False
        return True

    def write_first_ti_received_time(
            self, year: int, month: int, day: int) -> bool:
        """Update first TI received time"""
        try:
            msb = self.parm["stats"]["First TI received time"][0]
            lsb = self.parm["stats"]["First TI received time"][1]
        except KeyError:
            return False
        n = (year - 2000) * 16 * 32 + 32 * month + day
        if self.debug:
            print("FTRT:", hex(n // 256), hex(n % 256), "=", n // 256, n % 256)
        if not self.write_eeprom(msb, n // 256, label="First TI received time"):
            return False
        if not self.write_eeprom(lsb, n % 256, label="First TI received time"):
            return False
        return True

    def list_known_keys(self, debug=False):
        for model, chars in self.PRINTER_CONFIG.items():
            if 'write_key' in chars:
                print(f"{repr(model).rjust(25)}: {repr(chars['read_key']).rjust(10)} - {repr(chars['write_key'])[1:]}")
            else:
                print(f"{repr(model).rjust(25)}: {repr(chars['read_key']).rjust(10)} (unknown write key)")

    def brute_force_read_key(
        self, minimum: int = 0x00, maximum: int = 0xFF, debug=False
    ):
        """Brute force read_key for printer."""
        for x, y in itertools.permutations(range(minimum, maximum + 1), r=2):
            self.parm['read_key'] = [x, y]
            if debug:
                print(f"Trying {self.parm['read_key']}...")
            val = self.read_eeprom(0x00, label="brute_force_read_key")
            if val is None:
                continue
            return self.parm['read_key']
        return None

    def write_sequence_to_string(self, write_sequence):
        try:
            int_sequence = [int(b) for b in write_sequence[0].split(".")]
            return "".join([chr(b-1) for b in int_sequence])
        except Exception:
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
        "--detect-key",
        dest='detect_key',
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
        nargs=2,
        help='Dump EEPROM (arguments: start, stop)')
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
    parser.add_argument(
        '-R',
        '--read-eeprom',
        dest='read_eeprom',
        action='store',
        type=str,
        nargs=1,
        help='Read the values of a list of printer EEPROM addreses.'
        ' Format is: address [, ...]')
    parser.add_argument(
        '-W',
        '--write-eeprom',
        dest='write_eeprom',
        action='store',
        type=str,
        nargs=1,
        help='Write related values to a list of printer EEPROM addresses.'
        ' Format is: address: value [, ...]')
    parser.add_argument(
        '-S',
        '--write-sequence-to-string',
        dest='ws_to_string',
        action='store',
        type=str,
        nargs=1,
        help='Convert write sequence of numbers to string.'
    )
    parser.add_argument(
        '-t',
        '--timeout',
        dest='timeout',
        type=float,
        default=None,
        help='SNMP GET timeout (floating point argument)',
    )
    parser.add_argument(
        '-r',
        '--retries',
        dest='retries',
        type=float,
        default=None,
        help='SNMP GET retries (floating point argument)',
    )
    args = parser.parse_args()

    printer = EpsonPrinter(
        args.model,
        args.hostname,
        timeout=args.timeout,
        retries=args.retries,
        debug=args.debug,
        dry_run=args.dry_run)
    if not printer.parm:
        print(textwrap.fill("Unknown printer. Valid printers: " + ", ".join(
            printer.valid_printers),
            initial_indent='', subsequent_indent='  ')
        )
        quit(1)
    print_opt = False
    try:
        if args.ws_to_string:
            print_opt = True
            print(self.write_sequence_to_string(args.ws_to_string))
        if args.reset_waste_ink:
            print_opt = True
            if self.reset_waste_ink_levels():
                print("Reset waste ink levels done.")
            else:
                print("Failed to reset waste ink levels. Check configuration.")
        if args.detect_key:
            print_opt = True
            read_key = self.brute_force_read_key(debug=True)
            if read_key:
                print(f"read_key found: {read_key}")
                print("List of known keys:")
                self.list_known_keys(debug=True)
            else:
                print(f"Cannot found read_key")
        if args.ftrt:
            print_opt = True
            if self.write_first_ti_received_time(
                    int(args.ftrt[0]), int(args.ftrt[1]), int(args.ftrt[2])):
                print("Write first TI received time done.")
            else:
                print(
                    "Failed to write first TI received time."
                    " Check configuration."
                )
        if args.dump_eeprom:
            print_opt = True
            for addr, val in self.dump_eeprom(
                        args.dump_eeprom[0] % 256,
                        int(args.dump_eeprom[1] % 256)
                    ).items():
                print(f"{str(addr).rjust(3)}: {val:#04x} = {str(val).rjust(3)}")
        if args.query:
            print_opt = True
            if ("stats" in printer.parm and
                    args.query[0] in printer.parm["stats"]):
                ret = self.get_stats(args.query[0])
                if ret:
                    pprint(ret)
                else:
                    print("No information returned. Check printer definition.")
            elif args.query[0] in printer.snmp_info.keys():
                ret = self.get_snmp_info(args.query[0])
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
                    ret = self.__getattribute__(method)()
                    if ret:
                        pprint(ret)
                    else:
                        print(
                            "No information returned."
                            " Check printer definition."
                        )
                else:
                    print(
                        "Option error: unavailable query.\n" +
                        textwrap.fill(
                            "Available queries: " +
                            ", ".join(printer.list_methods),
                            initial_indent='', subsequent_indent='  '
                        ) + "\n" +
                        (
                            (
                                textwrap.fill(
                                    "Available statistics: " +
                                    ", ".join(printer.parm["stats"].keys()),
                                    initial_indent='', subsequent_indent='  '
                                ) + "\n"
                            ) if "stats" in printer.parm else ""
                        ) +
                        textwrap.fill(
                            "Available SNMP elements: " +
                            ", ".join(printer.snmp_info.keys()),
                            initial_indent='', subsequent_indent='  '
                        )
                    )
        if args.read_eeprom:
            print_opt = True
            read_list = re.split(',\s*', args.read_eeprom[0])
            for value in read_list:
                try:
                    val = self.read_eeprom(
                        ast.literal_eval(value), label='read_eeprom')
                    if val is None:
                        print("EEPROM read error.")
                    else:
                        print(f"0x{val}={int(val, 16)}")
                except (ValueError, SyntaxError):
                    print("invalid argument for read_eeprom")
                    quit(1)
        if args.write_eeprom:
            print_opt = True
            read_list = re.split(',\s*|;\s*|\|\s*', args.write_eeprom[0])
            for key_val in read_list:
                key, val = re.split(':|=', key_val)
                try:
                    val_int = ast.literal_eval(val)
                    if not self.write_eeprom(
                            ast.literal_eval(key),
                            str(val_int), label='write_eeprom'
                        ):
                        print("invalid write operation")
                        quit(1)
                except (ValueError, SyntaxError):
                    print("invalid argument for write_eeprom")
                    quit(1)                    
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

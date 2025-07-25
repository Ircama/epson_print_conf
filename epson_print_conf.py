#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Epson Printer Configuration via SNMP (TCP/IP)
"""

import itertools
from itertools import chain
import re
from typing import Any, List, Tuple, Union
import datetime
import time
import textwrap
import ast
import logging
import os
import yaml
from pathlib import Path
import pickle
import abc
import hashlib
import struct

from pysnmp.hlapi.v1arch.asyncio import *
from pyasn1.type.univ import OctetString as OctetStringType
from pysnmp_sync_adapter import (
    get_cmd_sync,
    parallel_get_sync,
    create_transport,
    cluster_varbinds
)
from pysnmp.proto.errind import RequestTimedOut
from pyprintlpr import LprClient


class EpsonPrinter:
    """SNMP Epson Printer Configuration."""

    PRINTER_CONFIG = {  # Known Epson models
        "L386": {
            "read_key": [16, 8],
            "write_key": b"Sinabung",
            "printer_head_id_h": range(122, 126),
            "printer_head_id_f": [129],
            "main_waste": {"oids": [24, 25, 30], "divider": 62.07},
            "borderless_waste": {"oids": [26, 27, 34], "divider": 24.2},
            "raw_waste_reset": {
                24: 0, 25: 0, 30: 0,  # Data of 1st counter
                28: 0, 29: 0,  # another store of 1st counter
                46: 94,  # Maintenance required level of 1st counter
                26: 0, 27: 0, 34: 0,  # Data of 2nd counter
                47: 94,  # Maintenance required level of 2nd counter
                49: 0  # ?
            },
            "stats": {
                "Manual cleaning counter": [147],
                "Timer cleaning counter": [149],
                "Power cleaning counter": [148],
                "Total print pass counter": [171, 170, 169, 168],
                "Total print page counter": [167, 166, 165, 164],
                "Total scan counter": [471, 470, 469, 468],
                "First TI received time": [173, 172],
                "Maintenance required level of 1st waste ink counter": [46],
                "Maintenance required level of 2nd waste ink counter": [47],
                "Power off timer": [359, 358],
            },
            "serial_number": range(192, 202),
            "last_printer_fatal_errors": [
                453, 452, 455, 454, 457, 456, 459, 458, 461, 460, 467,
                499, 498, 501, 500, 503, 502, 505, 504, 507, 506
            ],
        },
        "XP-205": {
            "alias": ["XP-200", "XP-207"],
            "read_key": [25, 7],
            "printer_head_id_h": range(122, 127),
            "printer_head_id_f": [136, 137, 138, 129],
            "main_waste": {"oids": [24, 25, 30], "divider": 73.5},
            "borderless_waste": {"oids": [26, 27, 34], "divider": 34.34},
            "wifi_mac_address": range(130, 136),
            "brand_name": range(868, 932),
            "model_name": range(934, 998),
            "same-as": "XP-315"
        },
        "ET-4700": {
            "read_key": [151, 7],
            "write_key": b"Maribaya",
            "main_waste": {"oids": [48, 49, 47], "divider": 63.46},
            "borderless_waste": {"oids": [50, 51, 47], "divider": 34.16},
            "raw_waste_reset": {
                48: 0, 49: 0, 47: 0, 52: 0, 53: 0, 54: 94, 50: 0, 51: 0,
                55: 94, 28: 0
            },
            "stats": {
                "First TI received time": [9, 8],
                "Total print pass counter": [133, 132, 131, 130],
                "Total print page counter": [776, 775, 774, 773],
                "Total scan counter": [1843, 1842, 1841, 1840],
                "Total scan counter % (ADF)": [1855, 1854, 1853, 1852],
                "Ink replacement counter - Black": [554],
                "Ink replacement counter - Cyan": [555],
                "Ink replacement counter - Magenta": [556],
                "Ink replacement counter - Yellow": [557],
                "Maintenance required level of 1st waste ink counter": [54],
                "Maintenance required level of 2nd waste ink counter": [55],
            },
            "serial_number": range(1604, 1614),
        },
        "Stylus Photo PX720WD": {
            "read_key": [54, 6],
            "write_key": b"IhroroQU",
            "main_waste": {"divider": 79.23, "oids": [14, 15]},
            "borderless_waste": {"divider": 122.84, "oids": [16, 17]},
            "raw_waste_reset": {
                8: 0, 9: 0, 12: 0, 13: 0, 14: 0, 15: 0, 16: 0, 17: 0,
                18: 0, 19: 0
            },
            "stats": {
                "Manual cleaning counter": [126],
                "Timer cleaning counter": [97],
                "Total print pass counter": [47, 46, 45, 44],
                "Total print page counter": [159, 158],
                "Total print page counter - duplex": [161, 160],
                "Total print CD-R counter": [75, 74],
                "Total CD-R tray open/close counter": [163, 162],
                "Total scan counter": [477, 476, 475, 474],
            },
            "ink_replacement_counters": {
                "Black": {"1S": 102, "2S": 103, "3S": 98},
                "Yellow": {"1S": 112, "2S": 113, "4S": 171},
                "Magenta": {"1S": 104, "2S": 105, "4S": 99},
                "Cyan": {"1S": 108, "2S": 109, "4S": 101},
                "Light Magenta": {"1S": 106, "2S": 107, "3S": 100},
                "Light Cyan": {"1S": 110, "2S": 111, "3S": 155},
            },
            "serial_number": range(231, 241),
            "alias": ["TX720WD", "Artisan 720", "PX720WD"],
        },
        "Stylus Photo PX730WD": {
            "alias": ["TX730WD", "PX730WD", "Stylus Photo PX730", "Artisan 730"],
            "read_key": [119, 8],  # "read_key": [0x8, 0x77], (I'm afraid 0x8, 0x77 is wrong)
            "write_key": b'Cattleya',
            "main_waste": {"oids": [0xe, 0xf, 60], "divider": 81.82},
            "borderless_waste": {"oids": [0x10, 0x11, 60], "divider": 122.88},
            "raw_waste_reset": {
                8: 0, 9: 0, 12: 0, 13: 0, 14: 0, 15: 0, 16: 0, 17: 0,
                18: 0, 19: 0, 60: 0, 61: 94, 62: 94
            },
            "stats": {
                "Manual cleaning counter": [0x7e],
                "Timer cleaning counter": [0x61],
                "Total print pass counter": [0x2C, 0x2D, 0x2E, 0x2F],
                "Total print page counter": [0x9E, 0x9F],
                "Total print page counter (duplex)": [0xA0, 0xA1],
                "Total print CD-R counter": [0x4A, 0x4B],
                "Total print CD-R tray open/close counter": [0xA2, 0xA3],
                "Total scan counter": [0x01DA, 0x01DB, 0x01DC, 0x01DD],
                "Maintenance required level of 1st waste ink counter": [61],
                "Maintenance required level of 2nd waste ink counter": [62],
            },
            "last_printer_fatal_errors": [0x3B, 0xC0, 0xC1, 0xC2, 0xC3, 0x5C],
            "ink_replacement_counters": {
                "Black": {"1S": 0x66, "2S": 0x67, "3S": 0x62},
                "Yellow": {"1S": 0x70, "2S": 0x71, "4S": 0xAB},
                "Magenta": {"1S": 0x68, "2S": 0x69, "4S": 0x63},
                "Cyan": {"1S": 0x6C, "2S": 0x6D, "4S": 0x65},
                "Light magenta": {"1S": 0x6A, "2S": 0x6B, "3S": 0x64},
                "Light cyan": {"1S": 0x6E, "2S": 0x6F, "3S": 0x9B},
            },
            "serial_number": range(0xE7, 0xF1),
        },
        "WF-7525": {
            "read_key": [101, 0],
            "write_key": b'Sasanqua',
            "alias": ["WF-7515"],
            "main_waste": {"oids": [20, 21, 59], "divider": 196.5},
            "borderless_waste": {"oids": [22, 23, 59], "divider": 52.05},
            "serial_number": range(192, 202),
            "stats": {
                "Maintenance required level of 1st waste ink counter": [60],
                "Maintenance required level of 2nd waste ink counter": [61],
                "Manual cleaning counter": [131],
                "Timer cleaning counter": [134],
                "Ink replacement cleaning counter": [133],
                "Total print pass counter": [159, 158, 157, 156],
                "Total print page counter": [147, 146, 145, 144],
                "Total scan counter": [471, 470, 469, 468],
                "Total scan counter % (ADF)": [475, 474, 473, 472],
            },
            "ink_replacement_counters": {
                "Black": {"1L": 242, "1S": 243, "2S": 244},
                "Yellow": {"1S": 248, "2S": 249, "3S": 250},
                "Magenta": {"1S": 251, "2S": 252, "3S": 253},
                "Cyan": {"1S": 245, "2S": 246, "3S": 247},
            },
           "raw_waste_reset": {
                20: 0, 21: 0, 22: 0, 23: 0, 24: 0, 25: 0, 59: 0, 60: 94, 61: 94
            }
        },
        "L355": {
            "read_key": [65, 9],
            "write_key": b"Wakatobi",
            "main_waste": {"oids": [24, 25, 30], "divider": 65.0},
            "raw_waste_reset": {24: 0, 25: 0, 30: 0, 28: 0, 29: 0, 46: 94},
            "stats": {
                "Manual cleaning counter": [147],
                "Timer cleaning counter": [149],
                "Total print pass counter": [171, 170, 169, 168],
                "Total print page counter - Color": [439, 438, 437, 436],
                "Total print page counter - Black": [435, 434, 433, 432],
                "Total print page counter - Blank": [443, 442, 441, 440],
                "Total print page counter": [167, 166, 165, 164],
                "Total scan counter": [471, 470, 469, 468],
                "First TI received time": [173, 172],
                "Ink replacement counter - Black": [242],
                "Ink replacement counter - Yellow": [244],
                "Ink replacement counter - Magenta": [245],
                "Ink replacement counter - Cyan": [243],
            },
            "serial_number": range(192, 202),
        },
        "L366": {
            "read_key": [130, 2],
            "write_key": b'Gerbera*',
            "main_waste": {"oids": [24, 25, 30], "divider": 62.0625},
            "borderless_waste": {"oids": [26, 27, 34], "divider": 24.20},
            "stats": {
                "Maintenance required level of 1st waste ink counter": [46],
                "Maintenance required level of 2nd waste ink counter": [47],
                "Ink replacement counter - Black": [242],
                "Ink replacement counter - Yellow": [243],
                "Ink replacement counter - Cyan": [244],
                "Ink replacement counter - Magenta": [245],
            },
            "raw_waste_reset": {
                24: 0, 25: 0, 30: 0, 26: 0, 27: 0, 34: 0, 28: 0, 29: 0,
                49: 0, 46: 94, 47: 94
            },
            "serial_number": range(192, 202),
        },
        "L3060": {
            "read_key": [149, 3],
            "write_key": b"Maninjau",
            "main_waste": {"oids": [24, 25, 30], "divider": 62.07},
            "borderless_waste": {"oids": [26, 27, 34], "divider": 24.2},
            "raw_waste_reset": {
                24: 0, 25: 0, 30: 0, 28: 0, 29: 0,
                46: 94, 26: 0, 27: 0, 34: 0, 47: 94
            },
            "stats": {
                "Maintenance required level of 1st waste ink counter": [46],
                "Maintenance required level of 2nd waste ink counter": [47],
                "Manual cleaning counter": [147],
                "Timer cleaning counter": [149],
                "Power cleaning counter": [148],
                "Total print pass counter": [171, 170, 169, 168],
                "Total print page counter - rear feed": [167, 166, 165, 164],
                "Total scan counter": [471, 470, 469, 468],
                "First TI received time": [173, 172],
                "Ink replacement counter - Black": [242],
                "Ink replacement counter - Yellow": [244],
                "Ink replacement counter - Magenta": [245],
                "Ink replacement counter - Cyan": [243],
            },
            "serial_number": range(192, 202),
        },
        "ET-2400": {
            "alias": ["ET-2401", "ET-2403", "ET-2405"],
            "read_key": [74, 54],
            "write_key": b"Maribaya",
            "main_waste": {"oids": [48, 49, 47], "divider": 63.46},
            "borderless_waste": {"oids": [50, 51, 47], "divider": 34.16},
            "third_waste": {"oids": [252, 253, 254], "divider": 13.0},
            "raw_waste_reset": {
                48: 0, 49: 0, 47: 0, 52: 0, 53: 0, 54: 94, 50: 0, 51: 0,
                55: 94, 28: 0, 252: 0, 253: 0, 254: 0, 255: 94,
            },
            "stats": {
                "Maintenance required level of 1st waste ink counter": [54],
                "Maintenance required level of 2nd waste ink counter": [55],
                "Maintenance required level of 3rd waste ink counter": [255],
                "Manual cleaning counter": [90],
                "Timer cleaning counter": [89],
                "Power cleaning counter": [91],
                "Total print pass counter": [133, 132, 131, 130],
                "Total print page counter": [776, 775, 774, 773],
                "Total scan counter": [1843, 1842, 1841, 1840],
            },
            "serial_number": range(1604, 1614),
        },
        "ET-2600": {
            "alias": ["ET-2650", "L395"],
            "read_key": [16, 8],
            "write_key": b'Sinabung',
            "main_waste": {"oids": [24, 25, 30], "divider": 62.06},
            "raw_waste_reset": {24: 0, 25: 0, 30: 0, 28: 0, 29: 0, 46: 94},
            "stats": {
                "Manual cleaning counter": [147],
                "Timer cleaning counter": [149],
                "Power cleaning counter": [148],
                "Total print pass counter": [171, 170, 169, 168],
                "Total print page counter": [167, 166, 165, 164],
                "Total scan counter": [471, 470, 469, 468],
                "First TI received time": [173, 172],
            },
            "serial_number": range(192, 202),
        },
        "ET-2720": {
            "alias": ["ET-2714", "ET-2721", "ET-2723", "ET-2725"],
            "read_key": [151, 7],
            "write_key": b'Maribaya',
            "main_waste": {"oids": [48, 49, 47], "divider": 63.45},
            "borderless_waste": {"oids": [50, 51, 47], "divider": 34.15},
            "same-as": "ET-2700"
        },
        "ET-2750": {
            "serial_number": range(1604, 1614),
            "alias": ["ET-2751", "ET-2756"],
            "read_key": [73, 8],
            "write_key": b"Arantifo",
            "main_waste": {"oids": [48, 49, 47], "divider": 109.13},
            "borderless_waste": {"oids": [50, 51, 47], "divider": 16.31},
            "raw_waste_reset": {
                48: 0, 49: 0, 47: 0, 52: 0, 53: 0,
                54: 94,
                50: 0, 51: 0,
                55: 94,
                28: 0
            },
            "stats": {
                "First TI received time": [9, 8],
                "Total print pass counter": [133, 132, 131, 130],
                "Total print page counter - rear feed": [755, 754, 753, 752],
                "Total scan counter": [1843, 1842, 1841, 1840],
                "Ink replacement counter - Black": [554],
                "Ink replacement counter - Cyan": [555],
                "Ink replacement counter - Magenta": [556],
                "Ink replacement counter - Yellow": [557],
                "Maintenance required level of 1st waste ink counter": [54],
                "Maintenance required level of 2nd waste ink counter": [55],
            },
        },
        "ET-2800": {
            "read_key": [74, 54],
            "write_key": b"Maribaya",
            "main_waste": {"oids": [48, 49, 47], "divider": 63.46},
            "borderless_waste": {"oids": [50, 51, 47], "divider": 34.16},
            "third_waste": {"oids": [252, 253, 254], "divider": 13.0},
            "raw_waste_reset": {
                48: 0,
                49: 0,
                47: 0,
                52: 0,
                53: 0,
                54: 94,
                50: 0,
                51: 0,
                55: 94,
                28: 0,
                252: 0,
                253: 0,
                254: 0,
                255: 94,
            },
            "stats": {
                "Manual cleaning counter": [90],
                "Timer cleaning counter": [89],
                "Power cleaning counter": [91],
                "Total print pass counter": [133, 132, 131, 130],
                "Total print page counter": [776, 775, 774, 773],
                "Total scan counter": [1843, 1842, 1841, 1840],
                "Maintenance required level of 1st waste ink counter": [54],
                "Maintenance required level of 2nd waste ink counter": [55],
                "Maintenance required level of 3rd waste ink counter": [255],
            },
            "serial_number": range(1604, 1614),
            "alias": ["ET-2801", "ET-2803", "ET-2805"],
        },
        "ET-2812": {
            "read_key": [74, 54],
            "write_key": b"Maribaya",
            "main_waste": {"oids": [48, 49, 47], "divider": 63.46},
            "borderless_waste": {"oids": [50, 51, 47], "divider": 34.16},
            "third_waste": {"oids": [252, 253, 254], "divider": 13.0},
            "raw_waste_reset": {
                48: 0, 49: 0, 47: 0, 52: 0, 53: 0, 54: 94, 50: 0, 51: 0,
                55: 94, 28: 0, 252: 0, 253: 0, 254: 0, 255: 94
            },
            "stats": {
                "Maintenance required level of 1st waste ink counter": [54],
                "Maintenance required level of 2nd waste ink counter": [55],
                "Maintenance required level of 3rd waste ink counter": [255],
                "Manual cleaning counter": [90],
                "Timer cleaning counter": [89],
                "Power cleaning counter": [91],
                "Total print pass counter": [133, 132, 131, 130],
                "Total print page counter": [776, 775, 774, 773],
                "Total scan counter": [1843, 1842, 1841, 1840],
            },
            "serial_number": range(1604, 1614),
            "alias": [
                "ET-2814", "ET-2816", "ET-2818", "ET-2810", "ET-2811",
                "ET-2813", "ET-2815"
            ],
        },
        "ET-4800": {
            "read_key": [74, 54],
            "write_key": b"Maribaya",
            "main_waste": {"oids": [48, 49, 47], "divider": 63.46},
            "borderless_waste": {"oids": [50, 51, 47], "divider": 34.16},
            "third_waste": {"oids": [252, 253, 254], "divider": 13.0},
            "raw_waste_reset": {
                48: 0, 49: 0, 47: 0, 52: 0, 53: 0, 54: 94, 50: 0, 51: 0,
                55: 94, 28: 0, 252: 0, 253: 0, 254: 0, 255: 94
            },
            "stats": {
                "Manual cleaning counter": [90],
                "Timer cleaning counter": [89],
                "Power cleaning counter": [91],
                "Total print pass counter": [133, 132, 131, 130],
                "Total print page counter": [776, 775, 774, 773],
                "Total scan counter": [1843, 1842, 1841, 1840],
                "Total scan counter % (ADF)": [1855, 1854, 1853, 1852],
                "Ink replacement counter %-- Black": [554],
                "Ink replacement counter %-- Cyan": [555],
                "Ink replacement counter %-- Magenta": [556],
                "Ink replacement counter %-- Yellow": [557],
                "Maintenance required level of 1st waste ink counter": [54],
                "Maintenance required level of 2nd waste ink counter": [55],
                "Maintenance required level of 3rd waste ink counter": [255],
            },
            "serial_number": [range(793, 803), range(1604, 1614)],
            "wifi_mac_address": range(1920, 1926),
        },
        "L3150": {
            "alias": ["L3151", "L3160", "L3166", "L3168"],
            "read_key": [151, 7],
            "write_key": b'Maribaya',
            "main_waste": {"oids": [48, 49, 47], "divider": 63.46},
            "borderless_waste": {"oids": [50, 51, 47], "divider": 34.16},
            "same-as": "L4160"
        },
        "L405": {
            "read_key": [149, 3],
            "write_key": b"Maninjau",
            "main_waste": {"oids": [24, 25, 30], "divider": 62.07},
            "raw_waste_reset": {24: 0, 25: 0, 30: 0, 28: 0, 29: 0, 46: 94},
            "stats": {
                "Maintenance required level of waste ink counter": [46],
                "Manual cleaning counter": [147],
                "Timer cleaning counter": [149],
                "Power cleaning counter": [148],
                "Total print pass counter": [171, 170, 169, 168],
                "Total print page counter": [167, 166, 165, 164],
                "Total scan counter": [471, 470, 469, 468],
                "First TI received time": [173, 172],
                "Ink replacement counter - Black": [242],
                "Ink replacement counter - Yellow": [244],
                "Ink replacement counter - Magenta": [245],
                "Ink replacement counter - Cyan": [243],
            },
            "serial_number": range(192, 202),
        },
        "R2000": {
            "read_key": [1, 0],
            "write_key": b"Yutamori",
            "main_waste": {"divider": 215.0, "oids": [87, 88]},
            "borderless_waste": {"divider": 70.3, "oids": [89, 90]},
            "raw_waste_reset": {
                83: 0, 84: 0, 85: 0, 86: 0, 87: 0, 88: 0, 89: 0, 90: 0,
                58: 0, 59: 0
            },
            "stats": {
                "Manual cleaning counter": [362],
                "Timer cleaning counter": [364],
                "Ink replacement cleaning counter": [363],
                "Total print pass counter": [183, 182, 181, 180],
                "Total print page counter": [179, 178, 177, 176],
                "Total print CD-R counter": [185, 184],
                "Total print page counter - fine paper": [211, 210, 209, 208],
                "Total print page counter - board paper": [193, 192],
                "Total print page counter - roll paper": [397, 396, 395, 394],
                "Ink replacement counter - Yellow": [400],
                "Ink replacement counter - Magenta": [401],
                "Ink replacement counter - Matte Black": [402],
                "Ink replacement counter - Red": [403],
                "Ink replacement counter - Orange": [404],
                "Ink replacement counter - Photo Black": [405],
                "Ink replacement counter - Gloss Optimizer": [406],
                "Ink replacement counter - Cyan": [407],
            },
            "serial_number": range(466, 476),
        },
        "L4160": {
            "read_key": [73, 8],
            "write_key": b'Arantifo',
            "alias": [
                "L4150", "L4152", "L4154", "L4156", "L4158",
                "L4162", "L4164", "L4166", "L4168"
            ],
            "main_waste": {"oids": [48, 49, 47], "divider": 109.13},
            "borderless_waste": {"oids": [50, 51, 47], "divider": 16.31},
            "stats": {
                "Maintenance required level of 1st waste ink counter": [54],
                "Maintenance required level of 2nd waste ink counter": [55],
                "First TI received time": [9, 8],
                "Total print pass counter": [133, 132, 131, 130],
                "Total print page counter": [776, 775, 774, 773],
                "Total scan counter": [1843, 1842, 1841, 1840],
                "Ink replacement counter - Black": [554],
                "Ink replacement counter - Cyan": [555],
                "Ink replacement counter - Magenta": [556],
                "Ink replacement counter - Yellow": [557],
            },
            "serial_number": range(1604, 1614),
            "raw_waste_reset": {
                48: 0, 49: 0, 47: 0, 52: 0, 53: 0,
                54: 94,
                50: 0, 51: 0,
                55: 94,
                28: 0
            },
        },
        "XP-315": {
            "alias": ["XP-312", "XP-313"],
            "read_key": [129, 8],
            "write_key": b'Wakatobi',
            "printer_head_id_h": range(122, 126),
            "printer_head_id_f": [129],
            "main_waste": {"oids": [24, 25], "divider": 69},
            "borderless_waste": {"oids": [26, 27], "divider": 32.53},
            "serial_number": range(192, 202),
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
                "Power off timer": [359, 358],
            },
            "raw_waste_reset": {
                24: 0, 25: 0,  # Data of 1st waste ink level
                30: 0,  # First maintenance box reset counter
                28: 0, 29: 0,  # another store of 1st waste ink level
                46: 94,  # Maintenance required level of 1st counter
                26: 0, 27: 0,  # Data of 2nd waste ink level
                34: 0,  # Second maintenance box reset counter
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
        "XP-342": {
            "alias": ["XP-343", "XP-345"],
            "read_key": [1, 5],
            "write_key": b"Suramadu",
            "main_waste": {"oids": [24, 25, 30], "divider": 39.9},
            "borderless_waste": {"oids": [26, 27, 34], "divider": 32.55},
            "raw_waste_reset": {24: 0, 25: 0, 30: 0, 28: 0, 29: 0, 46: 94, 26: 0, 27: 0, 34: 0, 47: 94, 49: 0},
            "stats": {
                "Manual cleaning counter": [147],
                "Timer cleaning counter": [149],
                "Power cleaning counter": [148],
                "Total print pass counter": [171, 170, 169, 168],
                "Total print page counter": [167, 166, 165, 164],
                "Total scan counter": [471, 470, 469, 468],
                "First TI received time": [173, 172],
                "Maintenance required level of 1st waste ink counter": [46],
                "Maintenance required level of 2nd waste ink counter": [47],
            },
            "serial_number": range(192, 202),
            "alias": ["XP-343", "XP-345"],
        },
        "XP-422": {
            "alias": ["XP-423", "XP-425", "XP-225"],
            "read_key": [85, 5],
            "write_key": b'Muscari.',
            "main_waste": {"oids": [24, 25, 30], "divider": 196.5},
            "borderless_waste": {"oids": [26, 27, 34], "divider": 52.05},
            "stats": {
                "Maintenance required level of 1st waste ink counter": [46],
                "Maintenance required level of 2nd waste ink counter": [47],
            },
            "raw_waste_reset": {
                24: 0, 25: 0, 26: 0, 27: 0, 28: 0,
                29: 0, 30: 0, 34: 0, 46: 94, 47: 94, 49: 0
            },
            "serial_number": range(192, 202),
        },
        "XP-432": {
            "read_key": [133, 5],
            "write_key": b"Polyxena",
            "main_waste": {"oids": [24, 25, 30], "divider": 39.9},
            "borderless_waste": {"oids": [26, 27, 34], "divider": 32.55},
            "raw_waste_reset": {
                24: 0, 25: 0, 30: 0, 28: 0, 29: 0, 46: 94, 26: 0, 27: 0,
                34: 0, 47: 94, 49: 0
            },
            "stats": {
                "Maintenance required level of 1st waste ink counter": [46],
                "Maintenance required level of 2nd waste ink counter": [47]
            },
            "alias": ["XP-235", "XP-433", "XP-435"],
        },
        "XP-540": {
            "read_key": [20, 4],
            "write_key": b"Firmiana",
            "main_waste": {"oids": [16, 17, 6], "divider": 48.06},
            "borderless_waste": {"oids": [18, 19, 6], "divider": 20.82},
            "raw_waste_reset": {16: 0, 17: 0, 6: 0, 52: 94, 20: 0, 21: 0, 18: 0, 19: 0, 53: 94, 493: 0},
            "stats": {
                "Timer cleaning counter": [245],
                "Total print pass counter": [99, 98, 97, 96],
                "Total scan counter": [453, 452, 451, 450],
                "Maintenance required level of 1st waste ink counter": [52],
                "Maintenance required level of 2nd waste ink counter": [53],
            },
            "serial_number": range(216, 226),
        },
        "XP-610": {
            "alias": ["XP-611", "XP-615", "XP-510", "XP-55"],
            "read_key": [121, 4],
            "write_key": b"Gossypiu",
            "main_waste": {"oids": [16, 17, 6], "divider": 84.5},
            "borderless_waste": {"oids": [18, 19, 6], "divider": 29.03},
            "raw_waste_reset": {
                16: 0, 17: 0, 6: 0, 52: 94, 20: 0, 21: 0, 18: 0, 19: 0,
                53: 94, 493: 0
            },
            "stats": {
                "Timer cleaning counter": [245],
                "Total print pass counter": [99, 98, 97, 96],
                "Total print CD-R counter": [255, 254],
                "Maintenance required level of 1st waste ink counter": [52],
                "Maintenance required level of 2nd waste ink counter": [53],
            },
            "serial_number": range(216, 226),
            "alias": ["XP-611", "XP-615"],
        },
        "XP-620": {
            "read_key": [87, 5],
            "write_key": b"Althaea.",
            "main_waste": {"oids": [16, 17, 6], "divider": 84.5},
            "borderless_waste": {"oids": [18, 19, 6], "divider": 33.7},
            "raw_waste_reset": {
                16: 0, 17: 0, 6: 0, 52: 94, 20: 0, 21: 0, 18: 0, 19: 0,
                53: 94, 493: 0
            },
            "stats": {
                "Timer cleaning counter": [245],
                "Total print pass counter": [99, 98, 97, 96],
                "Total print CD-R counter": [255, 254],
                "Maintenance required level of 1st waste ink counter": [52],
                "Maintenance required level of 2nd waste ink counter": [53],
            },
            "serial_number": range(216, 226),
            "alias": ["XP-621", "XP-625"],
        },
        "XP-700": {
            "read_key": [40, 0],
            "write_key": b"Hibiscus",
            "main_waste": {"oids": [16, 17, 6], "divider": 84.5},
            "borderless_waste": {"oids": [18, 19, 6], "divider": 29.03},
            "raw_waste_reset": {16: 0, 17: 0, 6: 0, 52: 94, 20: 0, 21: 0, 18: 0, 19: 0, 53: 94, 493: 0},
            "stats": {
                "Timer cleaning counter": [245],
                "Total print pass counter": [99, 98, 97, 96],
                "Total print CD-R counter": [255, 254],
                "Maintenance required level of 1st waste ink counter": [52],
                "Maintenance required level of 2nd waste ink counter": [53],
            },
            "serial_number": range(216, 226),
            "alias": ["XP-701", "XP-702"],
        },
        "XP-760": {
            "read_key": [87, 5],
            "write_key": b"Althaea.",
            "main_waste": {"oids": [16, 17, 6], "divider": 84.5},
            "borderless_waste": {"oids": [18, 19, 6], "divider": 33.7},
            "raw_waste_reset": {16: 0, 17: 0, 6: 0, 52: 94, 20: 0, 21: 0, 18: 0, 19: 0, 53: 94, 493: 0},
            "stats": {
                "Timer cleaning counter": [245],
                "Total print pass counter": [99, 98, 97, 96],
                "Total print CD-R counter": [255, 254],
                "Maintenance required level of 1st waste ink counter": [52],
                "Maintenance required level of 2nd waste ink counter": [53],
            },
            "serial_number": range(216, 226),
        },
        "XP-830": {
            "read_key": [40, 9],
            "write_key": b"Irisgarm",  # (Iris graminea with typo?)
            "main_waste": {"oids": [16, 17, 6], "divider": 84.5},
            "borderless_waste": {"oids": [18, 19, 6], "divider": 33.7},
            "raw_waste_reset": {16: 0, 17: 0, 6: 0, 52: 94, 20: 0, 21: 0, 18: 0, 19: 0, 53: 94, 493: 0},
            "stats": {
                "Timer cleaning counter": [245],
                "Total print pass counter": [99, 98, 97, 96],
                "Total print CD-R counter": [255, 254],
                "Total scan counter": [453, 452, 451, 450],
                "Total scan counter % (ADF)": [457, 456, 455, 454],
                "Maintenance required level of 1st waste ink counter": [52],
                "Maintenance required level of 2nd waste ink counter": [53],
            },
            "serial_number": range(216, 226),
            "idProduct": 0x110b,
        },
        "XP-960": {
            "read_key": [40, 9],
            "write_key": b"Irisgarm",
            "main_waste": {"oids": [16, 17, 6], "divider": 93.85},
            "borderless_waste": {"oids": [18, 19, 6], "divider": 29.77},
            "raw_waste_reset": {
                16: 0, 17: 0, 6: 0, 52: 94, 18: 0, 19: 0, 20: 0, 21: 0,
                53: 94, 493: 0
            },
            "stats": {
                "Timer cleaning counter": [245],
                "Total print pass counter": [99, 98, 97, 96],
                "Total print CD-R counter": [255, 254],
                "Total scan counter": [453, 452, 451, 450],
                "Maintenance required level of 1st waste ink counter": [52],
                "Maintenance required level of 2nd waste ink counter": [53],
            },
            "serial_number": range(216, 226),
        },
        "XP-820": {
            "read_key": [87, 5],
            "write_key": b"Althaea.",
            "borderless_waste": {"oids": [18, 19, 6], "divider": 33.7},
            "alias": ["XP-821"],
            "same-as": "XP-850"
        },
        "XP-850": {
            "read_key": [40, 0],
            "write_key": b"Hibiscus",
            "main_waste": {"oids": [16, 17, 6], "divider": 84.5},
            "borderless_waste": {"oids": [18, 19, 6], "divider": 29.03},
            "raw_waste_reset": {
                16: 0, 17: 0, 6: 0, 52: 94, 20: 0, 21: 0, 18: 0, 19: 0,
                53: 94, 493: 0
            },
            "stats": {
                "Timer cleaning counter": [245],
                "Total print pass counter": [99, 98, 97, 96],
                "Total print CD-R counter": [255, 254],
                "Maintenance required level of 1st waste ink counter": [52],
                "Maintenance required level of 2nd waste ink counter": [53],
            },
            "serial_number": range(216, 226),
        },
        "XP-7100": {
            "read_key": [40, 5],
            "write_key": b"Leucojum",
            "main_waste": {"oids": [16, 17, 6], "divider": 84.5},
            "borderless_waste": {"oids": [18, 19, 6], "divider": 33.7},
            "raw_waste_reset": {
                16: 0, 17: 0, 6: 0, 52: 94, 20: 0, 21: 0, 18: 0,
                19: 0, 53: 94, 493: 0
            },
            "stats": {
                "First TI received time": [9, 8],
                "Total print pass counter": [99, 98, 97, 96],
                "Total print page counter - front feed lower": [696, 695, 694, 693],
                "Total print page counter - front feed upper": [744, 743, 742, 741],
                "Total print page counter - rear": [748, 747, 746, 745],
                "Total print page counter - duplex": [752, 751, 750, 749],
                "Total print CD-R counter": [255, 254],
                "Total scan counter": [453, 452, 451, 450],
                "Total scan counter (ADF)": [457, 456, 455, 454],
                "Ink replacement counter - Black": [701],
                "Ink replacement counter % PB": [705],
                "Ink replacement counter - Cyan": [702],
                "Ink replacement counter - Magenta": [703],
                "Ink replacement counter - Yellow": [704],
                "Maintenance required level of 1st waste ink counter": [52],
                "Maintenance required level of 2nd waste ink counter": [53],
            },
            "serial_number": range(216, 226),
        },
        "XP-2150": {
            "read_key": [80, 9],
            "write_key": b"Bidadari",
            "main_waste": {"oids": [337, 338, 336], "divider": 69.0},
            "borderless_waste": {"oids": [339, 340, 336], "divider": 30.49},
            "raw_waste_reset": {
                336: 0, 337: 0, 338: 0, 339: 0, 340: 0, 341: 0, 343: 94,
                342: 0, 344: 94, 28: 0
            },
            "stats": {
                "First TI received time": [9, 8],
                "Manual cleaning counter": [203],
                "Timer cleaning counter": [205],
                "Total print pass counter": [133, 132, 131, 130],
                "Total scan counter": [1843, 1842, 1841, 1840],
                "Total print page counter": [792, 791, 790, 789],
                "Ink replacement counter - Black": [554],
                "Ink replacement counter - Cyan": [555],
                "Ink replacement counter - Magenta": [556],
                "Ink replacement counter - Yellow": [557],
                "Maintenance required level of 1st waste ink counter": [343],
                "Maintenance required level of 2nd waste ink counter": [344],
            },
            "serial_number": range(1604, 1614),
            "alias": ["XP-2100", "XP-2151", "XP-2155"],
        },
        "XP-2200": {  # 06.51.IU19M506.58.IU05P2
            "read_key": [75, 54],
            "write_key": b"Kenjeran",
            "main_waste": {"oids": [337, 338, 336], "divider": 69.0},
            "borderless_waste": {"oids": [339, 340, 336], "divider": 30.49},
            "raw_waste_reset": {
                336: 0, 337: 0, 338: 0, 339: 0, 340: 0, 341: 0, 343: 94,
                342: 0, 344: 94, 28: 0
            },
            "stats": {
                "First TI received time": [9, 8],
                "Manual cleaning counter": [203],
                "Timer cleaning counter": [205],
                "Total print pass counter": [133, 132, 131, 130],
                "Total scan counter": [1843, 1842, 1841, 1840],
                "Total print page counter": [792, 791, 790, 789],
                "Ink replacement counter - Black": [554],
                "Ink replacement counter - Cyan": [555],
                "Ink replacement counter - Magenta": [556],
                "Ink replacement counter - Yellow": [557],
                "Maintenance required level of 1st waste ink counter": [343],
                "Maintenance required level of 2nd waste ink counter": [344],
                "Power off timer 1": [230, 229],
                "Power off timer 2": [231, 230],
                "Power off timer 3": [262, 261],
            },
            "serial_number": range(1604, 1614),
            "wifi_mac_address": range(1920, 1926),
            "alias": ["XP-2205"],
        },
        "ET-2500": {
            "read_key": [68, 1],
            "write_key": b"Gerbera*",
            "main_waste": {"oids": [24, 25, 30], "divider": 62.07},
            "raw_waste_reset": {24: 0, 25: 0, 30: 0, 28: 0, 29: 0, 46: 94},
            "stats": {"Maintenance required level of 1st waste ink counter": [46]},
            "serial_number": range(192, 202),
        },
        "XP-3150": {
            "alias": ["XP-3151", "XP-3155"],
            "read_key": [80, 9],
            "write_key": b'Bidadari',
            "serial_number": range(1604, 1614),
            "printer_head_id_h": [171, 189, 190, 175],
            "printer_head_id_f": [191, 188],
            "stats": {
                "MAC Address": range(0x780, 0x786),
                "First TI received time": [9, 8],
                "Total print pass counter": [133, 132, 131, 130],
                "Total print page counter": [0x2fb, 0x2fa, 0x2f9, 0x2f8],
                "Total scan counter": [0x0733, 0x0732, 0x0731, 0x0730],
                "Paper count color": [0x314, 0x313, 0x312, 0x311],
                "Paper count monochrome": [0x318, 0x317, 0x316, 0x315],
                "Ink replacement counter - Black": [0x22a],
                "Ink replacement counter - Cyan": [0x22b],
                "Ink replacement counter - Magenta": [0x22c],
                "Ink replacement counter - Yellow": [0x22d],
                "Maintenance_box_replacement_counter": [0x22e],
            },
            "last_printer_fatal_errors": chain(
                range(0x120, 0x12a), range(0x727, 0x72c), range(0x7f4, 0x7fe)
            ),
        },
        "ET-2550": {  # Epson EcoTank ET-2550
            "read_key": [0x44, 0x01],
            "write_key": b'Gazania*',
            "main_waste": {"oids": [24, 25, 30], "divider": 62.06},
            "serial_number": range(192, 202),
            "stats": {
                "Maintenance required level of waste ink counter": [46]
            },
            "raw_waste_reset": {
                24: 0, 25: 0, 30: 0,  # Data of the waste ink counter
                28: 0, 29: 0,  # another store of the waste ink counter
                46: 94,  # Maintenance required level of the waste ink counter
            }
        },
        "ET-2700": {  # Epson EcoTank ET-2700 Series
            "alias": ["ET-2701", "ET-2703", "ET-2705"],
            "read_key": [73, 8],
            "write_key": b'Arantifo',
            "serial_number": range(1604, 1614),
            "main_waste": {"oids": [48, 49, 47], "divider": 109.13},
            "borderless_waste": {"oids": [50, 51, 47], "divider": 16.31},
            "stats": {
                "Maintenance required level of 1st waste ink counter": [54],
                "Maintenance required level of 2nd waste ink counter": [55],
                "First TI received time": [9, 8],
                "Total print pass counter": [133, 132, 131, 130],
                "Total print page counter - rear feed": [755, 754, 753, 752],
                "Total scan counter": [1843, 1842, 1841, 1840],
                "Ink replacement counter - Black": [554],
                "Ink replacement counter - Cyan": [555],
                "Ink replacement counter - Magenta": [556],
                "Ink replacement counter - Yellow": [557],
            },
            "raw_waste_reset": {
                48: 0, 49: 0, 47: 0,  # Data of 1st counter
                52: 0, 53: 0,  # another store of 1st counter
                54: 94,  # Maintenance required level of 1st counter
                50: 0, 51: 0,  # Data of 2nd counter
                55: 94,  # Maintenance required level of 2st counter
                28: 0  # ?
            }
        },
    }

    CARTRIDGE_TYPE = {  # map cartridge number with color
        1811: 'Black', 1812: 'Cyan', 1813: 'Magenta', 1814: 'Yellow',  # T18xx / 18XL
        711: 'Black', 712: 'Cyan', 713: 'Magenta', 714: 'Yellow',  # T7xx
        10332: 'Black', 10360: 'Cyan', 10361: 'Magenta', 10362: 'Yellow',  # 603XL
    }

    MIB_MGMT = "1.3.6.1.2"
    PRINT_MIB = MIB_MGMT + ".1.43"
    MIB_OID_ENTERPRISE = "1.3.6.1.4.1"
    MIB_EPSON = MIB_OID_ENTERPRISE + ".1248"
    OID_PRV_CTRL = "1.2.2.44.1.1.2"
    EPSON_CTRL_TO_OID = f'{MIB_EPSON}.{OID_PRV_CTRL}.1'

    MIB_INFO = {
        "Model": f"{MIB_MGMT}.1.25.3.2.1.3.1",
        "Epson Printer Name": f"{MIB_EPSON}.1.2.2.1.1.1.2.1",
        "Model short": f"{MIB_EPSON}.1.1.3.1.3.8.0",
        "Epson Personal Name": f"{MIB_EPSON}.1.2.2.1.1.1.3.1",
        "EEPS2 firmware version": f"{MIB_MGMT}.1.2.2.1.2.1",
        "Epson Version number": f"{MIB_EPSON}.1.2.2.2.1.1.2.1.4",
        "Descr": f"{MIB_MGMT}.1.1.1.0",
        "UpTime": f"{MIB_MGMT}.1.1.3.0",
        "Name": f"{MIB_MGMT}.1.1.5.0",
        "MAC Address": f"{MIB_MGMT}.1.2.2.1.6.1",
        "Print input": f"{PRINT_MIB}.8.2.1.13.1.1",
        "Lang 1": f"{PRINT_MIB}.15.1.1.3.1.1",
        "Lang 2": f"{PRINT_MIB}.15.1.1.3.1.2",
        "Lang 3": f"{PRINT_MIB}.15.1.1.3.1.3",
        "Lang 4": f"{PRINT_MIB}.15.1.1.3.1.4",
        "Lang 5": f"{PRINT_MIB}.15.1.1.3.1.5",
        "Emulation 1": f"{PRINT_MIB}.15.1.1.5.1.1",
        "Emulation 2": f"{PRINT_MIB}.15.1.1.5.1.2",
        "Emulation 3": f"{PRINT_MIB}.15.1.1.5.1.3",
        "Emulation 4": f"{PRINT_MIB}.15.1.1.5.1.4",
        "Emulation 5": f"{PRINT_MIB}.15.1.1.5.1.5",
        "Total printed pages": f"{PRINT_MIB}.10.2.1.4.1.1",
        #"Total copies": f"{PRINT_MIB}.11.1.1.9.1.1",
        #"Serial number": f"{PRINT_MIB}.5.1.1.17.1",
        "IP Address": f"{MIB_EPSON}.1.1.3.1.4.19.1.3.1",
        "IPP_URL_path": f"{MIB_EPSON}.1.1.3.1.4.19.1.4.1",
        "IPP_URL": f"{MIB_EPSON}.1.1.3.1.4.46.1.2.1",
        "LPR_URL": "1.3.6.1.4.1.2699.1.2.1.3.1.1.4.1.1",
        "Driver": "1.3.6.1.4.1.1248.1.1.3.1.29.3.1.27.0",
        "WiFi": f"{MIB_EPSON}.1.1.3.1.29.2.1.9.0",
        "MAC Addr": f"{MIB_EPSON}.1.1.3.1.1.5.0",
        "device_id": f"{MIB_OID_ENTERPRISE}.11.2.3.9.1.1.7.0",
        "Epson device id": f"{MIB_EPSON}.1.2.2.1.1.1.1.1",
    }

    MIB_INFO_ADVANCED = {
        "Printer Status": f"{MIB_MGMT}.1.25.3.5.1.1",  # hrPrinterStatus
        "Printer Alerts": f"{MIB_MGMT}.1.43.18.1.1.8",  # prtAlertDescription
        "Printer Marker Supplies Level": f"{MIB_MGMT}.1.43.11.1.1.9",  # prtMarkerSuppliesLevel
        "Printer Marker Life Count": f"{MIB_MGMT}.1.43.11.1.1.6",  # prtMarkerLifeCount
        "Input Tray Status": f"{MIB_MGMT}.1.43.8.2.1.10",  # prtInputStatus
        "Output Tray Status": f"{MIB_MGMT}.1.43.9.2.1.10",  # prtOutputStatus
        "Printer Description": f"{MIB_MGMT}.1.25.3.2.1.3",  # hrDeviceDescr
        "Device Identification": f"{MIB_MGMT}.1.43.5.1.1.17",  # prtGeneralSerialNumber
        "Job Count": f"{MIB_MGMT}.1.43.10.2.1.4",  # prtJobEntryJobCount
        "Toner Level": f"{MIB_MGMT}.1.43.11.1.1.9.1",  # prtMarkerSuppliesLevel
        "Error Status": f"{MIB_MGMT}.1.43.16.5.1.2",  # prtConsoleDisplayBufferText
        "Power On Time": f"{MIB_MGMT}.1.25.3.2.1.5",  # hrDeviceUptime
        "Device Name": f"{MIB_MGMT}.1.1.5",  # sysName
        "Device Location": f"{MIB_MGMT}.1.1.6",  # sysLocation
    }

    session: object
    model: str
    hostname: str
    parm: dict
    mib_dict: dict = {}
    used_net_val: tuple = ()
    snmp_conf: object = None

    def __init__(
            self,
            conf_dict: dict = {},
            replace_conf = False,
            model: str = None,
            hostname: str = None,
            port: int = 161,
            timeout: (None, float) = None,
            retries: (None, float) = None,
            dry_run: bool = False
        ) -> None:
        """Initialise printer model."""
        def merge(source, destination):
            for key, value in source.items():
                if isinstance(value, dict):
                    merge(value, destination.setdefault(key, {}))
                else:
                    if key == "alias" and "alias" in destination:
                        destination[key] += value
                    else:
                        destination[key] = value
            return destination

        if conf_dict:
            self.expand_printer_conf(conf_dict)
        if conf_dict and replace_conf:
            self.PRINTER_CONFIG = conf_dict
        else:
            self.expand_printer_conf(self.PRINTER_CONFIG)
        if conf_dict and not replace_conf:
            self.PRINTER_CONFIG = merge(self.PRINTER_CONFIG, conf_dict)
            for key, values in self.PRINTER_CONFIG.items():
                if 'alias' in values:
                    values['alias'] = [
                        i for i in values['alias']
                        if i not in self.PRINTER_CONFIG
                    ]
                    if not values['alias']:
                        del values['alias']
        self.MIB_INFO["Power Off Timer"] = self.epctrl_snmp_oid(
            "ot", b"\x01\x01"
        )  # ".111.116.2.0.1.1" (off timer)
        self.model = model
        self.hostname = hostname
        self.port = port
        self.timeout = timeout
        self.retries = retries
        self.dry_run = dry_run
        if self.model in self.valid_printers:
            self.parm = self.PRINTER_CONFIG[self.model]
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
        """
        Return the list of methods that can be invoked to get the printer
        information data.
        Used by stats() and other modes to return all available information
        about a printer.
        A conforming method shall start with "get_".
        Do not use "get_" for new methods if you do not want them to be part
        of list_methods.
        """
        return(filter(lambda x: x.startswith("get_"), dir(self)))

    def expand_printer_conf(self, conf):
        """
        Expand "alias" and "same-as" of a printer database for all printers
        """
        # process "alias" definintion
        for printer_name, printer_data in conf.copy().items():
            if "alias" in printer_data:
                aliases = printer_data["alias"]
                del printer_data["alias"]
                if not isinstance(aliases, list):
                    logging.error(
                        "Alias '%s' of printer '%s' in configuration "
                        "must be a list.",
                        aliases, printer_name
                    )
                    continue
                for alias_name in aliases:
                    if alias_name in conf:
                        logging.error(
                            "Alias '%s' of printer '%s' is already defined "
                            "in configuration.",
                            alias_name, printer_name
                        )
                    else:
                        conf[alias_name] = printer_data
        # process "same-as" definintion
        for printer_name, printer_data in conf.copy().items():
            if "same-as" in printer_data:
                sameas = printer_data["same-as"]
                #del printer_data["same-as"]
                if sameas in conf:
                    conf[printer_name] = {
                        **conf[sameas],
                        **printer_data
                    }
                else:
                    logging.error(
                        "Undefined 'same-as' printer '%s' "
                        "in '%s' configuration.",
                        sameas, printer_name
                    )
        # process itertools classes
        def expand_itertools_in_dict(d):
            for key, value in d.items():
                if isinstance(value, dict):  # If the value is another dictionary, recurse into it
                    expand_itertools_in_dict(value)
                elif isinstance(
                    value, (
                    itertools.chain, itertools.cycle, itertools.islice, 
                    itertools.permutations, itertools.combinations, 
                    itertools.product, itertools.zip_longest, 
                    itertools.starmap, itertools.groupby
                    )
                ):
                    d[key] = list(value)  # Convert itertools object to a list
                elif isinstance(value, list):  # Check inside lists for dictionaries
                    for i, item in enumerate(value):
                        if isinstance(item, dict):
                            expand_itertools_in_dict(item)
        for printer_name, printer_data in conf.copy().items():
            expand_itertools_in_dict(printer_data)

    def stats(self):
        """Return all available information about a printer."""
        stat_set = {}
        # Run "list(self.printer.list_methods)" to get the list of all methods
        for method in self.list_methods:  # Run one by one all functions starting with "get_"
            ret = self.__getattribute__(method)()
            if ret:
                stat_set[method[4:]] = ret
            else:
                logging.info(f"No value for method '{method}'.")
        return stat_set

    def caesar(self, key, hex=False, list=False):
        """Convert the string write key to a sequence of numbers"""
        if list:
            return [ 0 if b == 0 else b + 1 for b in key ]
        if hex:
            return " ".join(
                '00' if b == 0 else '{0:02x}'.format(b + 1) for b in key
            )
        return ".".join("0" if b == 0 else str(b + 1) for b in key)


    def reverse_caesar(self, eight_bytes):
        """
        Convert a bytes type sequence key (8 bytes length) to string.
        Example:
        import epson_print_conf
        printer = epson_print_conf.EpsonPrinter()
        printer.reverse_caesar(bytes.fromhex("48 62 7B 62 6F 6A 62 2B"))
        """
        return "".join([chr(b - 1) for b in eight_bytes])

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
            logging.error("EpsonPrinter - invalid API usage")
            return None
        if not self.parm:
            logging.error("EpsonPrinter - invalid API usage")
            return None
        if 'read_key' not in self.parm:
            return None
        return self.epctrl_snmp_oid(
            "||",  # (7C 7C); "||" stands for EEPROM
            [
                self.parm['read_key'][0],
                self.parm['read_key'][1],
                ord('A'), #  -> 65 ('A' = read)
                ~ord('A') & 0xff,  # -> 190
                (ord('A')>>1 & 0x7f) | (ord('A')<<7 & 0x80),  # -> 160
                oid, msb
            ]
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
            logging.error("EpsonPrinter - invalid API usage")
            return None
        if not self.parm:
            logging.error("EpsonPrinter - invalid API usage")
            return None
        if (
            'write_key' not in self.parm
                or 'read_key' not in self.parm):
            return None
        write_op = self.epctrl_snmp_oid(
            "||",  # (7C 7C); "||" stands for EEPROM
            [
                self.parm['read_key'][0],
                self.parm['read_key'][1],
                ord('B'),  # -> 66 ('B' = write)
                ~ord('B') & 0xff,  # -> 189
                (ord('B')>>1 & 0x7f) | (ord('B')<<7 & 0x80),  # -> 33
                oid, msb, value
            ] + self.caesar(self.parm['write_key'], list=True)
        )
        if self.dry_run:
            logging.warning("WRITE_DRY_RUN: %s", write_op)
            return self.eeprom_oid_read_address(oid, label=label)
        else:
            return write_op

    def fetch_oid_values(
        self,
        oid: Union[str, List[Union[str, List[str]]]],
        label: str = "unknown"
    ) -> Union[
        Tuple[str, Any],
        List[Tuple[str, Any]]
    ]:
        """
        Query one or more OIDs and return their values.

        - If oid is a single string, returns [(type_name, value)].
        - If oid is a list of strings or list-of-lists, returns a list of
          (type_name, value) in the same order.

        Lists of strings are grouped into a single PDU; top-level list runs
        in parallel using parallel_get_sync.
        """
        # Config‐file overrides
        if self.mib_dict:
            # single‐OID case only
            if isinstance(oid, str):
                if oid not in self.mib_dict:
                    logging.error(
                        "MIB '%s' not in config. Operation: %s", oid, label
                    )
                    return [(None, False)]
                return self.mib_dict[oid]
            else:
                # list case: map through dict
                results = []
                for element in oid:
                    if isinstance(element, str):
                        if element not in self.mib_dict:
                            logging.error(
                                "MIB '%s' missing in config. Operation: %s",
                                element, label
                            )
                            results.append((None, False))
                        else:
                            results.append(self.mib_dict[element])
                    else:
                        # inner list grouping not supported by config
                        results.append((None, False))
                return results

        # Build or reuse SNMP network config
        if not self.hostname:
            return [(None, False)]

        net_val = (self.hostname, self.port, self.timeout, self.retries)
        if net_val != self.used_net_val:
            try:
                self.snmp_conf = (
                    SnmpDispatcher(),
                    CommunityData("public", mpModel=0),
                    create_transport(
                        UdpTransportTarget,
                        (self.hostname, self.port),
                        timeout=self.timeout, retries=self.retries
                    )
                )
            except Exception as e:
                logging.critical("fetch_oid_values invalid address: %s", e)
                self.used_net_val = ()
                return [(None, False)]

            self.used_net_val = net_val

        if not self.snmp_conf:
            return [(None, False)]

        # SNMP lookup
        def _single_lookup(single_oid: str) -> Tuple[str, Any]:
            """
            Internal helper to perform one get_cmd_sync.
            """
            engine, auth, transport = self.snmp_conf
            errorInd, errorStat, errorIdx, varBinds = get_cmd_sync(
                engine, auth, transport,
                ObjectType(ObjectIdentity(single_oid)),
                timeout=self.timeout
            )
            # transport-level timeout?
            if isinstance(errorInd, RequestTimedOut):
                raise TimeoutError(errorInd)
            elif errorInd is not None:
                logging.info("fetch_oid_values error: %s. OID: %s. Label: %s",
                             errorInd, single_oid, label)
                return [(None, False)]

            # SNMP-level errorStatus
            if int(errorStat) != 0:
                # find offending OID
                bad_oid = varBinds[int(errorIdx) - 1][0] if errorIdx else "?"
                logging.info(
                    "fetch_oid_values PDU error: %s at %s. OID: %s. Label: %s",
                    errorStat.prettyPrint(), bad_oid, single_oid, label
                )
                return [(None, False)]

            # unpack the varBinds
            final = []
            for oid_name, val in varBinds:
                if isinstance(val, OctetStringType):
                    final.append((val.__class__.__name__, val.asOctets()))
                else:
                    final.append((val.__class__.__name__, val.prettyPrint()))

            return final

        # Dispatch single vs batch
        if isinstance(oid, str):
            return _single_lookup(oid)

        # list of queries
        # normalize list elements → either str or [str,...]
        queries = []
        for elt in oid:
            if isinstance(elt, str):
                queries.append([elt])      # single‐OID PDU
            elif isinstance(elt, (list, tuple)):
                queries.append(list(elt))  # grouped‐OID PDU
            else:
                queries.append([])

        # run parallel_get_sync: each inner list packs into one PDU, all run in parallel
        engine, auth, transport = self.snmp_conf
        # build ObjectType lists
        wrapped_queries = [
            [ ObjectType(ObjectIdentity(x)) for x in group ]
            for group in queries
        ]
        wrapped_queries = cluster_varbinds(wrapped_queries, max_per_pdu=3)
        raw_results = parallel_get_sync(
            engine,
            auth,
            transport,
            queries=wrapped_queries,
            max_parallel=5
        )

        # raw_results is a list of SNMP tuples; map them through the same extraction logic
        final = []
        for (errI, errS, errX, vbs) in raw_results:
            # transport-level timeout?
            if isinstance(errI, RequestTimedOut):
                raise TimeoutError(errI)

            # SNMP errorStatus?
            if errI is not None or int(errS) != 0:
                # on error we don’t know how many OIDs were in this PDU,
                # but we do know len(vbs), so record a failure for each
                final.extend([(None, False)] * len(vbs))
                continue

            # unpack each var-bind in this PDU, in order
            for obj in vbs:
                # obj is an ObjectType; obj[1] is the value
                val = obj[1]
                if isinstance(val, OctetStringType):
                    final.append((val.__class__.__name__, val.asOctets()))
                else:
                    final.append((val.__class__.__name__, val.prettyPrint()))

        return final

    def invalid_response(self, response):
        if response is False:
            return True
        return len(response) < 2 or response[0] != 0 or response[-1] != 12

    def read_eeprom(
        self,
        oid: Union[int, str, List[Union[int,str]]],
        label: str = "unknown method"
    ) -> Union[str, List[Union[str,None]]]:
        """
        Read one or more EEPROM bytes at the given OID(s).
        
        - Single int/str → returns the two-hex-digit string or None.
        - List of int/str → returns a list of those strings/None, in order.
        """
        def _process_response(
            tag: Any, response: Any, oid_val: int
        ) -> Union[str, None]:
            """Extract and validate the 'EE:xxxxxx' payload for one response."""
            if not response or self.invalid_response(response):
                logging.error("Invalid response for OID %s (%s): %r", oid_val, label, response)
                return None

            # find the EE:xxxxxx substring
            try:
                txt = response.decode() if isinstance(
                    response, (bytes, bytearray)
                ) else response
                match = re.search(r"EE:([0-9A-Fa-f]{6})", txt)
                payload = match.group(1)
            except Exception:
                logging.info(
                    "Invalid read key for OID %s (%s)", oid_val, label
                )
                return None

            # split into address + value
            addr_hex, val_hex = payload[:4], payload[4:]
            if int(addr_hex, 16) != oid_val:
                logging.critical(
                    "EEPROM address mismatch: expected %04x != returned %s; %s",
                    oid_val, addr_hex, label
                )
                return None

            return val_hex.upper()

        # Build the address for SNMP
        def _addr(o):
            return self.eeprom_oid_read_address(o, label=label)

        # Call fetch_oid_values (single or batch)
        resp = self.fetch_oid_values(
            _addr(oid) if not isinstance(oid, list) else [
                _addr(o) for o in oid
            ],
            label=label
        )
        # resp is a list of (tag, response)
        if isinstance(oid, int):
            tag, response = resp[0]
            return _process_response(tag, response, oid)
        results: List[Union[str,None]] = []
        for o, entry in zip(oid, resp):
            tag, response = entry
            results.append(_process_response(tag, response, int(o)))

        return results

    def read_eeprom_many(
        self,
        oids: Union[range, List[Union[int,str]]],
        label: str = "unknown method"
    ) -> List[Union[str,None]]:
        """
        Read a list of bytes from the Epson EEPROM at addresses in `oids`,
        using a single parallel batch SNMP query.

        Accepts a list of ints/strs or a range() of ints.

        Returns a list of two-hex-digit strings (e.g. "A3") or None,
        for each OID, preserving order.

        If any element is None, returns [None].
        """
        # Normalize a range into a list of ints
        if isinstance(oids, range):
            oids = list(oids)

        # Delegate to read_eeprom (which handles both single and lists)
        results = self.read_eeprom(oids, label=label)
        if not isinstance(results, list):
            results = [results]

        if any(r is None for r in results):
            return [None]

        return results

    def write_eeprom(
            self,
            oid: int,
            value: int,
            label: str = "unknown method") -> None:
        """Write a single byte 'value' to the Epson EEPROM address 'oid'."""
        if not self.parm:
            logging.error("EpsonPrinter - invalid API usage")
            return False
        if "write_key" not in self.parm:
            logging.error(
                f"Missing 'write_key' parameter in configuration.")
            return False
        if not self.dry_run:
            response = self.read_eeprom(oid, label=label)
            logging.debug(f"Previous value for {label}: {response}")
        oid_string = self.eeprom_oid_write_address(oid, value, label=label)
        logging.debug(
            f"EEPROM_WRITE {label}:\n"
            f"  ADDRESS: {oid_string}\n"
            f"  OID: {oid}={hex(oid)}\n"
            f"  VALUE: {value} = {hex(int(value))}"
        )
        tag, response = self.fetch_oid_values(oid_string, label=label)[0]
        if response:
            logging.debug("  TAG: %s\n  RESPONSE: %s", tag, repr(response))
        if not self.dry_run and response and not ":OK;" in repr(response):
            logging.info(
                "Write error. Oid=%s, value=%s, label=%s", oid, value, label)
            return False  # ":NA;" is an error
        if self.invalid_response(response):
            logging.error(
                "Invalid write response. Oid=%s, value=%s, label=%s",
                oid, value, label
            )
            return False
        return True

    def status_parser(self, data):
        """
        Parse an ST2 status response and decode as much as possible.
        Example:
        import epson_print_conf
        import pprint
        printer = epson_print_conf.EpsonPrinter()
        pprint.pprint(printer.status_parser(bytes.fromhex(
            "40 42 44 43 20 53 54 32 0D 0A....."
        )))
        """
        colour_ids = {  # Ink cartridge name
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

        ink_color_ids = {  # Ink color
            0x00: 'Black',
            0x01: 'Cyan',
            0x02: 'Magenta',
            0x03: 'Yellow',
            0x04: 'Light Cyan',
            0x05: 'Light Magenta',
            0x06: "Dark Yellow",
            0x07: "Grey",
            0x08: "Light Black",
            0x09: "Red",
            0x0A: "Blue",
            0x0B: "Gloss Optimizer",
            0x0C: "Light Grey",
            0x0D: "Orange",
        }

        status_ids = {
            0x00: 'Error',
            0x01: 'Self Printing',
            0x02: 'Busy',
            0x03: 'Waiting',
            0x04: 'Idle (ready to print)',
            0x05: 'Paused',
            0x07: 'Cleaning',
            0x08: 'Factory shipment (not initialized)',
            0x0a: 'Shutdown',
            0x0f: 'Nozzle Check',
            0x11: "Charging",
        }
        
        errcode_ids = {
            0x00: "Fatal error",
            0x01: "Other I/F is selected",
            0x02: "Cover Open",
            0x04: "Paper jam",
            0x05: "Ink out",
            0x06: "Paper out",
            0x0c: "Paper size or paper type or paper path error",
            0x10: "Ink overflow error (Waste ink pad counter overflow)",
            0x11: "Wait return from the tear-off position",
            0x12: "Double Feed",
            0x1a: "Cartridge cover is opened error",
            0x1c: "Cutter error (Fatal Error)",
            0x1d: "Cutter jam error (recoverable)",
            0x22: "Maintenance cartridge is missing error",
            0x25: "Rear cover is opened error",
            0x29: "CD-R tray is out error",
            0x2a: "Memory Card loading Error",
            0x2B: "Tray cover is opened",
            0x2C: "Ink cartridge overflow error",
            0x2F: "Battery abnormal voltage error",
            0x30: "Battery abnormal temperature error",
            0x31: "Battery is empty error",
            0x33: "Initial filling is impossible error",
            0x36: "Maintenance cartridge cover is opened error",
            0x37: "Scanner or front cover is opened error",
            0x41: "Maintenance request",
            0x47: "Printing disable error",
            0x4a: "Maintenance Box near End error",
            0x4b: "Driver mismatch error ",
        }
        
        warning_ids = {
            0x10: "Ink low (Black or Yellow)",
            0x11: "Ink low (Magenta)",
            0x12: "Ink low (Yellow or Cyan)",
            0x13: "Ink low (Cyan or Matte Black)",
            0x14: "Ink low (Photo Black)",
            0x15: "Ink low (Red)",
            0x16: "Ink low (Blue)",
            0x17: "Ink low (Gloss optimizer)",
            0x44: "Black print mode",
            0x51: "Cleaning Disabled (Cyan)",
            0x52: "Cleaning Disabled (Magenta)",
            0x53: "Cleaning Disabled (Yellow)",
            0x54: "Cleaning Disabled (Black)",
        }

        if len(data) < 16:
            logging.info("status_parser: invalid packet")
            return "invalid packet"
        if data[:11] != b'\x00@BDC ST2\r\n':
            logging.debug("Unaligned BDC ST2 header. Trying to fix...")
            start = data.find(b'BDC ST2\r\n')
            if start < 0:
                logging.info(
                    "status_parser: "
                    "printer status error (must start with BDC ST2...)")
                return "printer status error (must start with BDC ST2...)"
            data = bytes(2) + data[start:]
        len_p = int.from_bytes(data[11:13], byteorder='little')
        if len(data) - 13 != len_p:
            logging.info("status_parser: message error (invalid length)")
            return "message error (invalid length)"
        buf = data[13:]
        data_set = {}
        while len(buf):
            if len(buf) < 3:
                logging.info("status_parser: invalid element")
                return "invalid element"
            (ftype, length) = buf[:2]
            buf = buf[2:]
            item = buf[:length]
            if len(item) != length:
                logging.info("status_parser: invalid element length")
                return "invalid element length"
            buf = buf[length:]
            logging.debug(
                "Processing status - ftype %s, length: %s, item: %s",
                hex(ftype), length, item.hex(' ')
            )
            if ftype == 0x01:  # Status code
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

            elif ftype == 0x02:  # Error code
                printer_status = item[0]
                if printer_status in errcode_ids:
                    data_set["errcode"] = errcode_ids[printer_status]
                else:
                    data_set["errcode"] = 'unknown: %d' % printer_status

            elif ftype == 0x03:  # Self print code
                data_set["self_print_code"] = item
                if item[0] == 0:
                    data_set["self_print_code"] = "Nozzle test printing"

            elif ftype == 0x04:  # Warning code
                data_set["warning_code"] = []
                for i in item:
                    if i in warning_ids:
                        data_set["warning_code"].append(warning_ids[i])
                    else:
                        data_set["warning_code"].append('unknown: %d' % i)

            elif ftype == 0x06:  # Paper path
                data_set["paper_path"] = item
                if item == b'\x01\xff':
                    data_set["paper_path"] = "Cut sheet (Rear)"
                if item == b'\x03\x01':
                    data_set["paper_path"] = "Roll paper"
                if item == b'\x03\x02':
                    data_set["paper_path"] = "Photo Album"
                if item == b'\x02\x01\x00':
                    data_set["paper_path"] = "Cut Sheet (Auto Select)"
                if item == b'\x02\x01':
                    data_set["paper_path"] = "CD-R, cardboard"
                if item == b'\x02\x01':
                    data_set["paper_path"] = "CD-R, cardboard"

            elif ftype == 0x07:  # Paper mismatch error
                data_set["paper_error"] = item

            elif ftype == 0x0c:  # Cleaning time information
                data_set["cleaning_time"] = int.from_bytes(
                    item , "little", signed=True)

            elif ftype == 0x0d:  # maintenance tanks
                data_set["tanks"] = str([i for i in item])

            elif ftype == 0x0e:  # Replace cartridge information
                data_set["replace_cartridge"] = "{:08b}".format(item[0])

            elif ftype == 0x0f:  # Ink information
                colourlen = item[0]
                offset = 1
                inks = []
                while offset < length:
                    colour = item[offset]
                    ink_color = item[offset + 1]
                    level = item[offset + 2]
                    offset += colourlen

                    if colour in colour_ids:
                        name = colour_ids[colour]
                    else:
                        name = "0x%X" % colour

                    if ink_color in ink_color_ids:
                        ink_name = ink_color_ids[ink_color]
                    else:
                        ink_name = "0x%X" % ink_color

                    inks.append((colour, ink_color, name, ink_name, level))

                data_set["ink_level"] = inks

            elif ftype == 0x10:  # Loading path information
                data_set["loading_path"] = item.hex().upper()
                if data_set["loading_path"] in [
                        "01094E", "01084E0E4E4E014E4E", "010C4E0E4E4E084E4E"]:
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

            elif ftype == 0x14:  # Cutter information
                try:
                    data_set["cutter"] = item.decode()
                except Exception:
                    data_set["cutter"] = str(item)
                if item == b'\x01':
                    data_set["cutter"] = "Set cutter"

            elif ftype == 0x18:  # Stacker(tray) open status
                data_set["tray_open"] = item
                if item == b'\x02':
                    data_set["tray_open"] = "Closed"
                if item == b'\x03':
                    data_set["tray_open"] = "Open"

            elif ftype == 0x19:  # Current job name information
                data_set["jobname"] = item
                if item == b'\x00\x00\x00\x00\x00unknown':
                    data_set["jobname"] = "Not defined"

            elif ftype == 0x1c:  # Temperature information
                data_set["temperature"] = item
                if item == b'\x01':
                    data_set["temperature"] = (
                        "The printer temperature is higher than 40C"
                    )
                if item == b'\x00':
                    data_set["temperature"] = (
                        "The printer temperature is lower than 40C"
                    )

            elif ftype == 0x1f:  # serial
                try:
                    data_set["serial"] = item.decode()
                except Exception:
                    data_set["serial"] = str(item)

            elif ftype == 0x35:  # Paper jam error information
                data_set["paper_jam"] = item
                if item == b'\x00':
                    data_set["paper_jam"] = "No jams"
                if item == b'\x01':
                    data_set["paper_jam"] = "Paper jammed at ejecting"
                if item == b'\x02':
                    data_set["paper_jam"] = "Paper jam in rear ASF or no feed"
                if item == b'\x80':
                    data_set["paper_jam"] = "No papers at rear ASF"

            elif ftype == 0x36:  # Paper count information
                if length != 20:
                    data_set["paper_count"] = "error"
                    logging.info(
                        "status_parser: paper_count error. Length: %s", length)
                    continue
                data_set["paper_count_normal"] = int.from_bytes(
                    item[0:4] , "little", signed=True)
                data_set["paper_count_page"] = int.from_bytes(
                    item[4:8] , "little", signed=True)
                data_set["paper_count_color"] = int.from_bytes(
                    item[8:12] , "little", signed=True)
                data_set["paper_count_monochrome"] = int.from_bytes(
                    item[12:16] , "little", signed=True)
                data_set["paper_count_blank"] = int.from_bytes(
                    item[16:20] , "little", signed=True)

            elif ftype == 0x37:  # Maintenance box information
                num_bytes = item[0]
                if num_bytes < 1 or num_bytes > 2:
                    data_set["maintenance_box"] = "unknown"
                    continue
                j = 1
                for i in range(1, length, num_bytes):
                    if item[i] == 0:
                        data_set[f"maintenance_box_{j}"] = (
                            f"not full ({item[i]})"
                        )
                    elif item[i] == 1:
                        data_set[f"maintenance_box_{j}"] = (
                            f"near full ({item[i]})"
                        )
                    elif item[i] == 2:
                        data_set[f"maintenance_box_{j}"] = (
                            f"full ({item[i]})"
                        )
                    else:
                        data_set[f"maintenance_box_{j}"] = (
                            f"unknown ({item[i]})"
                        )
                    if num_bytes > 1:
                        data_set[f"maintenance_box_reset_count_{j}"] = item[
                            i + 1]
                    j += 1

            elif ftype == 0x3d:  # Printer I/F status
                data_set["interface_status"] = item
                if item == b'\x00':
                    data_set["interface_status"] = (
                        "Available to accept data and reply"
                    )
                if item == b'\x01':
                    data_set["interface_status"] = (
                        "Not available to accept data"
                    )

            elif ftype == 0x40:  # Serial No. information
                try:
                    data_set["serial_number_info"] = item.decode()
                except Exception:
                    data_set["serial_number_info"] = str(item)

            elif ftype == 0x45 and length == 4:  # Ink replacement counter (TBV)
                data_set["ink_replacement_counter"] = {
                    "Black": item[0],
                    "Cyan": item[1],
                    "Magenta": item[2],
                    "Yellow": item[3],
                }

            elif ftype == 0x46 and length == 1:  # Maintenance_box_replacement_counter (TBV)
                data_set["maintenance_box_replacement_counter"] = item[0]

            else:  # unknown stuff
                if "unknown" not in data_set:
                    data_set["unknown"] = []
                data_set["unknown"].append((hex(ftype), item))
        return data_set

    # Start of "get_" methods
    def get_snmp_info(
        self,
        mib_name: str = None,
        advanced: bool = False
    ) -> str:
        """Return general SNMP information of printer."""
        sys_info = {}
        if advanced:
            oids = {**self.MIB_INFO, **self.MIB_INFO_ADVANCED}
        else:
            oids = self.MIB_INFO
        if mib_name and mib_name in oids.keys():
            snmp_info = {mib_name: oids[mib_name]}
        else:
            snmp_info = oids
        for name, oid in snmp_info.items():
            logging.debug(
                f"SNMP_DUMP {name}:\n"
                f"  ADDRESS: {oid}"
            )
            tag, result = self.fetch_oid_values(
                oid, label="get_snmp_info " + name
            )[0]
            logging.debug("  TAG: %s\n  RESPONSE: %s", tag, repr(result))

            if name == "Power Off Timer" and result and result.find(
                    b'@BDC PS\r\not:01') > 0:
                try:
                    power_off_h = int.from_bytes(bytes.fromhex(
                        result[
                            result.find(b'@BDC PS\r\not:01') + 14
                            :
                            result.find(b';')
                        ].decode()
                    ), byteorder="little")
                    sys_info[name] = f"{power_off_h} minutes"
                except Exception:
                    sys_info[name] = "(unknown)"
            elif name == "hex_data" and result is not False:
                sys_info[name] = result.hex(" ").upper()
            elif name == "UpTime" and result is not False:
                sys_info[name] = time.strftime(
                    '%H:%M:%S', time.gmtime(int(result)/100))
            elif name.startswith("MAC ") and result is not False:
                sys_info[name] = result.hex("-").upper()
            elif isinstance(result, bytes):
                sys_info[name] = result.decode()
            elif isinstance(result, str):
                sys_info[name] = result
            else:
                logging.info(
                    f"No value for SNMP OID '{name}'. MIB: {oid}.")
        return sys_info

    def get_serial_number(self) -> str:
        """Return the serial number of the printer (or "?" if error)."""
        if not self.parm:
            logging.error("EpsonPrinter - invalid API usage")
            return None
        if "serial_number" not in self.parm:
            return None
        if isinstance(self.parm["serial_number"], (list, tuple)):
            left_val = None
            for i in self.parm["serial_number"]:
                val = "".join(
                    chr(int(value or "0x3f", 16))  # "0x3f" --> "?"
                    for value in self.read_eeprom_many(i, label="serial_number")
                )
                if left_val is not None and val != left_val:
                    return False
                left_val = val
            return left_val
        else:
            try:
                return "".join(
                    chr(int(value or "0x3f", 16))  # "0x3f" --> "?"
                    for value in self.read_eeprom_many(
                        self.parm["serial_number"], label="serial_number")
                )
            except Exception:
                return None

    def get_printer_brand(self) -> str:
        """Return the producer name of the printer ("EPSON")."""
        if not self.parm:
            logging.error("EpsonPrinter - invalid API usage")
            return None
        if "brand_name" not in self.parm:
            return None
        try:
            return ''.join(
                [chr(int(i or "0x3f", 16))
                for i in self.read_eeprom_many(
                    self.parm["brand_name"], label="get_brand_name"
                ) if i != '00']
            )
        except Exception:
            return None

    def get_printer_model(self) -> str:
        """Return the model name of the printer."""
        if not self.parm:
            logging.error("EpsonPrinter - invalid API usage")
            return None
        if "model_name" not in self.parm:
            return None
        try:
            return ''.join(
                [chr(int(i or "0x3f", 16))
                for i in self.read_eeprom_many(
                    self.parm["model_name"], label="get_model_name"
                ) if i != '00']
            )
        except Exception:
            return None

    def get_wifi_mac_address(self) -> str:
        """Return the WiFi MAC address of the printer."""
        if not self.parm:
            logging.error("EpsonPrinter - invalid API usage")
            return None
        if "wifi_mac_address" not in self.parm:
            return None
        try:
            return '-'.join(
                octet.upper() for octet in self.read_eeprom_many(
                    self.parm["wifi_mac_address"], label="get_wifi_mac_address"
                )
            )
        except Exception:
            return None

    def get_stats(self, stat_name: str = None) -> str:
        """Return printer statistics."""
        if not self.parm:
            logging.error("EpsonPrinter - invalid API usage")
            return None
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
                    total = None
                    break
                else:
                    total = (total << 8) + int(val, 16)
            stats_result[stat_name] = total
            if stat_name == "MAC Address" and total != None:
                stats_result[stat_name] = total.to_bytes(
                    length=6, byteorder='big').hex("-").upper()
        if "First TI received time" not in stats_result:
            return stats_result
        ftrt = stats_result["First TI received time"]
        try:
            year = 2000 + ftrt // (16 * 32)
            month = (ftrt - (year - 2000) * (16 * 32)) // 32
            day = ftrt - (year - 2000) * 16 * 32 - 32 * month
            stats_result["First TI received time"] = datetime.datetime(
                year, month, day).strftime('%d %b %Y')
        except Exception:
            stats_result["First TI received time"] = "?"
        return stats_result

    def get_printer_head_id(self) -> str:  # only partially correct
        """Return printer head id."""
        if not self.parm:
            logging.error("EpsonPrinter - invalid API usage")
            return None
        if "printer_head_id_h" not in self.parm:
            return None
        if "printer_head_id_f" not in self.parm:
            return None
        a = self.read_eeprom_many(
            self.parm["printer_head_id_h"], label="printer_head_id_h")
        b = self.read_eeprom_many(
            self.parm["printer_head_id_f"], label="printer_head_id_f")
        if a == [None] or b == [None]:
            return None
        return(f'{"".join(a)} - {"".join(b)}')

    def get_firmware_version(self) -> str:
        """
        Return firmware version.
        Query firmware version: 1.3.6.1.4.1.1248.1.2.2.44.1.1.2.1.118.105.1.0.0
        """
        oid = self.epctrl_snmp_oid(
            "vi",  # This command stands for Version Information.
            0
        )
        label = "get_firmware_version"
        logging.debug(
            f"SNMP_DUMP {label}:\n"
            f"  ADDRESS: {oid}"
        )
        tag, firmware_string = self.fetch_oid_values(oid, label=label)[0]
        if not firmware_string:
            return None
        if self.invalid_response(firmware_string):
            logging.error(
                f"Invalid response for %s: '%s'",
                label, repr(firmware_string)
            )
        logging.debug("  TAG: %s\n  RESPONSE: %s", tag, repr(firmware_string))
        firmware = re.sub(
            r".*vi:00:(.{6}).*", r'\g<1>', firmware_string.decode())
        year = ord(firmware[4:5]) + 1945
        month = int(firmware[5:], 16)
        day = int(firmware[2:4])
        return firmware + " " + datetime.datetime(
            year, month, day).strftime('%d %b %Y')

    def get_device_identification(self) -> str:
        oid = self.epctrl_snmp_oid("di", 1)  # di = device identification
        label = "get_device_identification"
        logging.debug(
            f"SNMP_DUMP {label}:\n"
            f"  ADDRESS: {oid}"
        )
        tag, device_id = self.fetch_oid_values(oid, label=label)[0]
        key_map = {
            "MFG": "Manufacturer",
            "CMD": "Commands",
            "MDL": "Model",
            "CLS": "Class",
            "DES": "Description"
        }
        return {
            key_map.get(k, k): [v for v in vals if v]
            for i in device_id.decode()[10:].split(";") if i
            for k, *vals in [i.split(":")]
        }

    def get_cartridges(self) -> str:
        """Return list of cartridge types."""
        oid = self.epctrl_snmp_oid("ia", 0)  # ".105.97.1.0.0"  # 69 61 01 00 00 (ink actuator)
        label = "get_cartridges"
        logging.debug(
            f"SNMP_DUMP {label}:\n"
            f"  ADDRESS: {oid}"
        )
        tag, cartridges_string = self.fetch_oid_values(oid, label=label)[0]
        if self.invalid_response(cartridges_string):
            logging.error(
                f"Invalid response for %s: '%s'",
                label, repr(cartridges_string)
            )
        if not cartridges_string:
            return None
        logging.debug(
            "  TAG: %s\n  RESPONSE: %s", tag, repr(cartridges_string))
        cartridges = re.sub(
            r".*IA:00;(.*);.*", r'\g<1>',
            cartridges_string.decode(),
            flags=re.S
        )
        return [i.strip() for i in cartridges.split(',')]

    def get_ink_replacement_counters(self) -> str:
        """Return list of ink replacement counters."""
        if not self.parm:
            logging.error("EpsonPrinter - invalid API usage")
            return None
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
        """
        Return printer status and ink levels.
        Query printer status: 1.3.6.1.4.1.1248.1.2.2.44.1.1.2.1.115.116.1.0.1
        or 1.3.6.1.4.1.1248.1.2.2.1.1.1.4.1
        """
        address = self.epctrl_snmp_oid("st", 1)  # ".115.116.1.0.1"  # 73 74 01 00 01 (status)
        logging.debug(f"PRINTER_STATUS:\n  ADDRESS: {address}")
        tag, result = self.fetch_oid_values(
            address, label="get_printer_status"
        )[0]
        if not result:
            return None
        logging.debug("  TAG: %s\n  RESPONSE: %s...\n%s",
            tag,
            repr(result[:20]),
            textwrap.fill(
                result.hex(' '),
                initial_indent="    ",
                subsequent_indent="    ",
            )
        )
        return self.status_parser(result)

    def get_waste_ink_levels(self):
        """Return waste ink levels as a percentage."""
        if not self.parm:
            logging.error("EpsonPrinter - invalid API usage")
            return None
        if "main_waste" not in self.parm:
            return None
        results = {}
        for waste_type in ["main_waste", "borderless_waste", "first_waste",
                "second_waste", "third_waste"]:
            if waste_type not in self.parm:
                continue
            level = self.read_eeprom_many(
                self.parm[waste_type]["oids"], label=waste_type)
            if level == [None]:
                return None
            level_b10 = int("".join(reversed(level)), 16)
            results[waste_type] = round(
                level_b10 / self.parm[waste_type]["divider"], 2)
        return results

    def get_last_printer_fatal_errors(self) -> list:
        """
        Return the list of last printer fatal errors in hex format
        (or [None] if error).
        """
        if not self.parm:
            logging.error("EpsonPrinter - invalid API usage")
            return None
        if "last_printer_fatal_errors" not in self.parm:
            return None
        try:
            return self.read_eeprom_many(
                self.parm["last_printer_fatal_errors"],
                label="last_printer_fatal_errors"
            )
        except Exception:
            return None

    def get_cartridge_information(self) -> str:
        """Return list of cartridge properties."""
        response = []
        for i in range(1, 9):
            mib = self.epctrl_snmp_oid("ii", b"\x01" + bytes([i]))  # ".105.105.2.0.1." + str(i)  # 69 69 02 00 01 (ink information)
            logging.debug(
                f"Cartridge {i}:\n"
                f"  ADDRESS: {mib}"
            )
            tag, cartridge = self.fetch_oid_values(
                mib, label="get_cartridge_information"
            )[0]
            logging.debug("  TAG: %s\n  RESPONSE: %s", tag, repr(cartridge))
            if not cartridge:
                continue
            if self.invalid_response(cartridge):
                logging.error(
                    f"Invalid cartridge response: '%s'",
                    repr(cartridge)
                )
                return None
            if cartridge.find(b'ii:NA;') > 0 or cartridge.find(
                    b'@BDC PS\r\n') < 0:
                break
            response.append(cartridge)
        if not response:
            return None
        return self.cartridge_parser(response)
    # End of "get_" methods

    def ink_color(self, number):
        """
        Return a list including the cartridge input number and the related
        name of the ink color (or "unknown color" if not included
        in self.CARTRIDGE_TYPE).
        """
        return [
            number,
            self.CARTRIDGE_TYPE[
                number] if number in self.CARTRIDGE_TYPE else "unknown color",
        ]

    def cartridge_parser(self, cartridges: List[bytes]) -> str:
        """Parse the cartridge properties and decode as much as possible."""
        response = [
            cartridge[cartridge.find(b'@BDC PS\r\n') + 9
                :
                -2 if cartridge[-1] == 12 else -1]
                .decode()
                .split(';')
            for cartridge in cartridges
        ]
        if not response:
            return None
        try:
            cartridges = [
                {i[0]: i[1] for i in map(lambda x: x.split(':'), j)}
                    for j in response
            ]
        except Exception as e:
            logging.error("Cartridge map error: %s", e)
            return None
        if logging.getLogger().level <= logging.DEBUG:
            for i in cartridges:
                logging.debug("Raw cartridge information:")
                for j in i:
                    value = ""
                    if len(i[j]) < 6:
                        try:
                            value = str(int(i[j], 16))
                        except Exception:
                            pass
                    if i[j] == "NAVL":
                        value = "(Not available)"
                    logging.debug(
                        "  %s = %s %s",
                        j.rjust(4), i[j].rjust(4), value.rjust(4)
                    )
        try:
            missing = "Not available"
            return [
                {
                    k: v for k, v in 
                        {
                            "ink_color": self.ink_color(int(i['IC1'], 16))
                                if 'IC1' in i else missing,
                            "ink_quantity": int(i['IQT'], 16)
                                if 'IQT' in i else missing,
                            "production_year": int(i['PDY'], 16) + (
                                1900 if int(i['PDY'], 16) > 80 else 2000)
                                if 'PDY' in i else missing,
                            "production_month": int(i['PDM'], 16)
                                if 'PDM' in i else missing,
                            "data": i.get('SID').strip()
                                if 'SID' in i else missing,
                            "manufacturer": i.get('LOG').strip()
                                if 'LOG' in i else missing,
                        }.items()
                    if v  # exclude items without value
                } if 'II' in i and i['II'] == '03' else {
                    "Ink Information": f"Unknown {i['II']}"
                        if 'II' in i and i['II'] != '00' else missing
                }
                for i in cartridges
            ]
        except Exception as e:
            logging.error("Cartridge value error: %s.\n%s", e, cartridges)
            return None

    def dump_eeprom(self, start: int = 0, end: int = 0xFF) -> dict[int, int]:
        """
        Dump EEPROM data from `start` to `end` (inclusive) in a single
        parallel SNMP batch read.

        Returns a dict mapping each address → int value. If any read fails,
        that address maps to None.
        """
        # Build the list of OIDs
        oids = list(range(start, end + 1))

        # Fire one parallel batch read
        #    read_eeprom(list) now returns List[str|None]
        hex_results = self.read_eeprom(oids, label="dump_eeprom")

        # If the batch call itself errored out (None), fall back or return empty
        if hex_results is None:
            # All failed; return empty or map everything to None
            return {oid: None for oid in oids}

        # Map each hex‐string (or None) to an int (or None)
        d: dict[int, int] = {}
        for oid, hx in zip(oids, hex_results):
            if hx is None:
                d[oid] = None
            else:
                # hx is like "5A" → int("5A",16)
                d[oid] = int(hx, 16)
        return d

    def update_parameter(
        self,
        parameter: str,
        value_list: list,
        dry_run=False
    ) -> bool:
        """
        Update printer parameter by writing value data to EEPROM
        (tested with "serial_number" and "wifi_mac_address").
        """
        if not self.parm:
            logging.error("EpsonPrinter - invalid API usage")
            return None
        if (
            not parameter
            or parameter not in self.parm
            or not self.parm[parameter]
            or not value_list
            or not len(value_list)
            or (
                isinstance(self.parm[parameter], (list, tuple))
                and not all(
                    len(sublist) == len(value_list)
                    for sublist in self.parm[parameter]
                )
            )
            or (
                not isinstance(self.parm[parameter], (list, tuple))
                and len(self.parm[parameter]) != len(value_list)
            )
        ):
            return None
        if dry_run:
            return True
        if isinstance(self.parm[parameter], (list, tuple)):
            for i in self.parm[parameter]:
                for oid, value in zip(i, value_list):
                    if not self.write_eeprom(
                        oid, value, label="update_" + parameter
                    ):
                        return False
                    return True
            return False
        for oid, value in zip(self.parm[parameter], value_list):
            if not self.write_eeprom(oid, value, label="update_" + parameter):
                return False
            return True
        return False

    def epctrl_snmp_oid(self, command, payload):
        """
        Convert END4 EPSON-CTRL messages into OID
        (EPSON’s Remote Mode)
        """
        assert len(command) == 2
        if isinstance(payload, int):
            payload = bytes([payload])
        elif isinstance(payload, list):
            payload = bytes(payload)
        cmd = command.encode() + struct.pack('<H', len(payload)) + payload
        return self.EPSON_CTRL_TO_OID + "." + ".".join(
            str(int(i)) for i in cmd
        )

    def temporary_reset_waste(self, mode=1, dry_run=False) -> bool:
        """
        Thanks to https://codeberg.org/atufi/reinkpy/issues/12#issuecomment-1661250
        """
        serial = self.get_serial_number()
        if not serial:
            return None
        sha1 = hashlib.sha1(serial.encode())
        oid = self.epctrl_snmp_oid(
            "rw",  # This command stands for "reset waste".
            struct.pack('<H', mode) +  # Unknown \x01\x00 (2 bytes); the first byte must be 0x01 to work
            sha1.digest()  # Serial SHA1 hash. Always 20 bytes.
        )
        if dry_run:
            return True
        answer = self.fetch_oid_values(oid, label="temp_reset_waste")[0]
        status = b"rw:01:OK;" in answer[1]
        if not status:
            print(answer)
        return status

    def reset_waste_ink_levels(self, dry_run=False) -> bool:
        """
        Set waste ink levels to the values specified in the configuration.
        """
        if not self.parm:
            logging.error("EpsonPrinter - invalid API usage")
            return None
        if "raw_waste_reset" in self.parm:
            if dry_run:
                return True
            for oid, value in self.parm["raw_waste_reset"].items():
                if not self.write_eeprom(oid, value, label="raw_waste_reset"):
                    return False
            return True
        if "main_waste" not in self.parm:
            return None
        if dry_run:
            return True
        for oid in self.parm["main_waste"]["oids"]:
            if not self.write_eeprom(oid, 0, label="main_waste"):
                return False
        if "borderless_waste" not in self.parm:
            return True
        for oid in self.parm["borderless_waste"]["oids"]:
            if not self.write_eeprom(oid, 0, label="borderless_waste"):
                return False
        return True

    def check_nozzles(self, type=0):
        """
        Print nozzle-check pattern.
        """
        if not self.hostname:
            return None
        status = True
        lpr = LprClient(self.hostname, port="LPR", label="Check nozzles")

        # Sequence list
        nozzle_check = lpr.PRINT_NOZZLE_CHECK  # Issue nozzle-check print pattern
        if type == 1:
            nozzle_check = nozzle_check[:-1] + b'\x10'
        commands = [
            lpr.EXIT_PACKET_MODE,    # Exit packet mode
            lpr.ENTER_REMOTE_MODE,   # Engage remote mode commands
            nozzle_check,
            lpr.EXIT_REMOTE_MODE,    # Disengage remote control
            lpr.JOB_END              # Mark maintenance job complete
        ]
        try:
            lpr.connect()
            resp = lpr.send(b"".join(commands))
        except Exception as e:
            status = False
        finally:
            lpr.disconnect()
        return status

    def print_test_color_pattern(
        self,
        get_pattern=False,
        get_fullpattern=False,
        use_black23=False
    ):
        """
        Print a one-page color test pattern at various quality levels via LPR.
        Optimized for XP-200 and XP-205 models.
        Returns True if the pattern was successfully printed (sending the
            print-out to the host by creating a LPR job), False otherwise.
        If get_pattern is True, returns the ESC/P2 command sequence for the
            patterns as bytes.
        If get_pattern is False and get_fullpattern is True, returns the
            complete pattern as bytes (including ESC/P2 job headers and
            footers).
        """
        status = True
        lpr = LprClient(self.hostname, port="LPR", label="Check nozzles")

        # Transfer Raster image commands (ESC i), Color, Run Length Encoding,
        # 2 bits per pixel, 4 pixels per byte, H: 80 bytes = 320 dots = h 2,26 cm @ 360dpi (320/360*2,54)
        TRI_BLACK = "1b6900010250008000"  # ESC i 0: Black, V: 128 dots/rows (monochrome, 180 dpi) = 128/120*2,54= v 2,7 cm
        TRI_MAGENTA = "1b6901010250002a00"  # ESC i 1: Magenta, V: 42 dots/rows
        TRI_YELLOW = "1b6904010250002a00"  # ESC i 4: Yellow, V: 42 dots/rows dots
        TRI_CYAN = "1b6902010250002a00"  # ESC i 2: Cyan, V: 42 dots/rows
        TRI_BLACK2 = "1b6905010250002a00"  # ESC i 5: black2, V: 42 dots/rows
        TRI_BLACK3 = "1b6906010250002a00"  # ESC i 6: black3, V: 42 dots/rows

        SET_H_POS = "1b28240400"  # ESC ( $ = Set absolute horizontal print position, 4 bytes (n=length, first part)
        SET_V_POS = "1b28760400"  # ESC (v nL nH mL mH, 4 bytes (n=length, first part) = Set relative vertical print position

        USE_MONOCHROME = "1b284b02000001"  # ESC ( K = Monochrome Mode / Color Mode Selection, 01H: Monochrome mode
        USE_COLOR = "1b284b02000000"  # ESC ( K = Monochrome Mode / Color Mode Selection, 00H: Default mode (color mode)

        vsd_code = {  # Variable Sized Droplet
            -1: "00",  # VSD1 1bit or MC1-1 1 bit (for DOS)
            0: "10",  # Economy, Fast Draft
            1: "11",  # VSD1 2bit - fast eco, economy or speed/normal,
            2: "12",  # VSD2 2bit - fine/quality,
            3: "13",  # VSD3 2bit - super fine/high quality,
        }

        # Each sequence has 2 bits per pixel: 00=No, 01=Small, 10=Medium, 11=Large
        # Using Run-Length Encoding (RLE), d9 (217>127) means pattern repeated 257-217=40 times (160 dots per pattern).
        # These allow creating alternating patterns and are also used for solid patterns
        PATTERN_LARGE = "d9ff"  # ff = 11111111 = 11|11|11|11 = Large, 4 dots x 40
        PATTERN_MEDIUM = "d9aa"  # aa = 10101010 = 10|10|10|10 = Medium, 4 dots x 40
        PATTERN_SMALL = "d955"  # 55 = 01010101 = 01|01|01|01 = Small, 4 dots x 40
        PATTERN_NONE = "d900"  # 00 = 00000000 = 00|00|00|00 = No, 4 dots x 40
        PATTERN_NO_DOTS = PATTERN_NONE + PATTERN_NONE  # 320 dots, (4+4) dots x 40

        # Alternating patterns, 640 dots each = 2 hor. lines, one above the other
        PATTERN_LARGE_ALT = PATTERN_LARGE + PATTERN_NO_DOTS + PATTERN_LARGE
        PATTERN_MEDIUM_ALT = PATTERN_MEDIUM + PATTERN_NO_DOTS + PATTERN_MEDIUM
        PATTERN_SMALL_ALT = PATTERN_SMALL + PATTERN_NO_DOTS + PATTERN_SMALL

        # 6 vertically stacked printing segments, each of 4 hor stacked blocks
        printing_segments = [
            {
                "label_sequence": lpr.EXIT_REMOTE_MODE
                    + b'\r\n\r\nEconomy\r\n',
                "vsd": 0,
                "alternating_pattern": PATTERN_LARGE_ALT, 
                "solid_pattern": PATTERN_LARGE, 
            },
            {
                "label_sequence": lpr.INITIALIZE_PRINTER
                    + b"\r\n\n\n\nVSD1 - Medium dot size - Normal\r\n",
                "vsd": 1,
                "alternating_pattern": PATTERN_MEDIUM_ALT, 
                "solid_pattern": PATTERN_MEDIUM, 
            },
            {
                "label_sequence": lpr.INITIALIZE_PRINTER
                    + b"\r\n\n\n\nVSD2 - Medium dot size - Fine\r\n",
                "vsd": 2,
                "alternating_pattern": PATTERN_MEDIUM_ALT, 
                "solid_pattern": PATTERN_MEDIUM, 
            },
            {
                "label_sequence": lpr.INITIALIZE_PRINTER
                    + b"\r\n\n\n\nVSD3 - Large dot size - Super Fine\r\n",
                "vsd": 3,
                "alternating_pattern": PATTERN_LARGE_ALT, 
                "solid_pattern": PATTERN_LARGE, 
            },
            {
                "label_sequence": lpr.INITIALIZE_PRINTER
                    + b"\r\n\n\n\nVSD3 - Medium dot size - Super Fine\r\n",
                "vsd": 3,
                "alternating_pattern": PATTERN_MEDIUM_ALT, 
                "solid_pattern": PATTERN_MEDIUM, 
            },
            {
                "label_sequence": lpr.INITIALIZE_PRINTER
                    + b"\r\n\n\n\nVSD3 - Small dot size - Super Fine\r\n",
                "vsd": 3,
                "alternating_pattern": PATTERN_SMALL_ALT, 
                "solid_pattern": PATTERN_SMALL, 
            },
        ]

        def generate_patterns():
            """
            Generate the complete ESC/P2 command sequence for the patterns.
            """
            command_parts = []
            
            # Define the 4 hor stacked blocks for each vertically stacked segment 
            for segment in printing_segments:  # 6 printing segments

                # Label
                command_parts.append(segment["label_sequence"].hex())

                # Initialization
                command_parts.append(
                    "1b2847010001"  # Select graphics mode
                    + "1b28550500010101a005"  # ESC (U = Sets 360 DPI resolution
                    + "1b28430400c6410000"  # ESC (C = Configures page lenght
                    + "1b28630800ffffffffc6410000"  # ESC (c = Set page format
                    + "1b28530800822e0000c6410000"  # ESC (S = paper dimension specification
                    + "1b28440400" + "68010301"  # ESC (D = raster image resolution, r=360, v=3, h=1; 360/3=120 dpi vertically, 360/1=360 dpi horizontally
                    + "1b2865020000" + vsd_code[segment["vsd"]]  # ESC (e = Select Ink Drop Size
                    + "1b5502"  # ESC U 02H = selects automatic printing direction control
                    + USE_MONOCHROME
                    + SET_V_POS + "00010000" # ESC (v = Set relative vertical print position, 256 units = 4.52 mm
                )

                # First block - black alternating
                command_parts.append(SET_H_POS + "00010000")  # ESC ( $ = Set absolute horizontal print position, 256 = 4,52 mm
                command_parts.append(TRI_BLACK)
                command_parts.append(segment["alternating_pattern"] * 64)  # 64 x 2 = 128 rows = v 2,7 cm

                # Second block - Yellow/Magenta/Cyan alternating
                command_parts.append(USE_COLOR + SET_H_POS + "80060000")  # ESC ( $ = Set absolute horizontal print position, 1664 = 29,35 mm

                command_parts.append(TRI_MAGENTA)
                command_parts.append(segment["alternating_pattern"] * 64)

                command_parts.append(SET_H_POS + "80060000")  # ESC ( $ = Set absolute horizontal print position, 1664 = 29,35 mm        
                command_parts.append(TRI_YELLOW)
                command_parts.append(segment["alternating_pattern"] * 64)

                command_parts.append(SET_H_POS + "80060000")  # ESC ( $ = Set absolute horizontal print position, 1664 = 29,35 mm        
                command_parts.append(TRI_CYAN)
                command_parts.append(segment["alternating_pattern"] * 64)

                # Third block - Black solid
                command_parts.append(USE_MONOCHROME + SET_H_POS + "000c0000")  # ESC ( $ = Set absolute horizontal print position, 3072 = 54,35 mm
                
                command_parts.append(TRI_BLACK)
                command_parts.append(segment["solid_pattern"] * 256)  # 256 x (160 h dots per pattern / 320 h dots per line) = 128 v rows = v 2,7 cm

                # Fourth block - Yellow/Magenta/Cyan solid
                command_parts.append(USE_COLOR + SET_H_POS + "80110000")  # ESC ( $ = Set absolute horizontal print position, 4480 = 79 mm
                
                command_parts.append(TRI_MAGENTA)
                command_parts.append(segment["solid_pattern"] * 256)

                command_parts.append(SET_H_POS + "80110000")  # ESC ( $ = Set absolute horizontal print position, 4480 = 79 mm        
                command_parts.append(TRI_YELLOW)
                command_parts.append(segment["solid_pattern"] * 256)

                command_parts.append(SET_H_POS + "80110000")  # ESC ( $ = Set absolute horizontal print position, 4480 = 79 mm        
                command_parts.append(TRI_CYAN)
                command_parts.append(segment["solid_pattern"] * 256)

                # Fifth block - Black/Black2/Black3 solid
                if use_black23:
                    command_parts.append(USE_COLOR + SET_H_POS + "00170000")  # ESC ( $ = Set absolute horizontal print position, 5888 = 103,8 mm
                    
                    command_parts.append(TRI_BLACK)
                    command_parts.append(segment["solid_pattern"] * 256)

                    command_parts.append(SET_H_POS + "00170000")  # ESC ( $ = Set absolute horizontal print position, 5888 = 103,8 mm
                    command_parts.append(TRI_BLACK2)
                    command_parts.append(segment["solid_pattern"] * 256)

                    command_parts.append(SET_H_POS + "00170000")  # ESC ( $ = Set absolute horizontal print position, 5888 = 103,8 mm
                    command_parts.append(TRI_BLACK3)
                    command_parts.append(segment["solid_pattern"] * 256)
                
                command_parts.append(SET_V_POS + "00030000")  # ESC (v = Set relative vertical print position
                # Relative vertical offset = 768 units = 13.54 mm

            command_parts.append(
                (
                    lpr.INITIALIZE_PRINTER
                    + b"\r\n\n\n\n"
                    + b"Epson Printer Configuration - Print Test Patterns"
                    + b"\r\n"
                ).hex()
            )
            # Join all command parts into final hex string
            return "".join(command_parts)

        if get_pattern:
            return bytes.fromhex(generate_patterns())
        pattern = (
            lpr.INITIALIZE_PRINTER
            + lpr.REMOTE_MODE
            + lpr.PRINT_NOZZLE_CHECK

            + bytes.fromhex(generate_patterns())

            + lpr.INITIALIZE_PRINTER
            + b'\r'
            + lpr.FF
            + lpr.INITIALIZE_PRINTER
            + lpr.REMOTE_MODE
            + lpr.LD
            + lpr.EXIT_REMOTE_MODE
            + lpr.INITIALIZE_PRINTER
            + lpr.REMOTE_MODE
            + lpr.LD
            + lpr.JOB_END
            + lpr.EXIT_REMOTE_MODE
        )

        if get_fullpattern:
            return pattern

        if not self.hostname:
            return None
        try:
            lpr.connect()
            resp = lpr.send(pattern)
        except Exception as e:
            status = False
        finally:
            lpr.disconnect()
        return status

    def clean_nozzles(self, group_index, power_clean=False, has_alt_mode=None):
        """
        Initiates nozzles cleaning routine with optional power clean.
        """
        if not self.hostname:
            return None
        if has_alt_mode and (group_index > has_alt_mode or group_index) < 0:
            return None
        if not has_alt_mode and (group_index > 5 or group_index) < 0:
            return None
        status = True
        lpr = LprClient(self.hostname, port="LPR", label="Clean nozzles")

        group = group_index  # https://github.com/abrasive/x900-otsakupuhastajat/blob/master/emanage.py#L148-L154
        if power_clean:
            group |= 0x10  # https://github.com/abrasive/x900-otsakupuhastajat/blob/master/emanage.py#L220

        # Sequence list (Epson XP-205 207 Series Printing Preferences > Utilty > Clean Heads)
        commands = [
            lpr.EXIT_PACKET_MODE,                            # Exit packet mode
            lpr.ENTER_REMOTE_MODE,                           # Engage remote mode commands
            lpr.set_timer(),                                 # Sync RTC            
            lpr.remote_cmd("CH", b'\x00' + bytes([group])),  # Run print-head cleaning
            lpr.EXIT_REMOTE_MODE,                            # Disengage remote control
            lpr.ENTER_REMOTE_MODE,                           # Prepare for JOB_END
            lpr.JOB_END,                                     # Mark maintenance job complete
            lpr.EXIT_REMOTE_MODE                             # Close sequence
        ]

        if has_alt_mode and group_index == has_alt_mode:
            commands = [
                lpr.INITIALIZE_PRINTER,
                bytes.fromhex("1B 7C 00 06 00 19 07 84 7B 42 02")  # Head cleaning
            ]
        if has_alt_mode and group_index == has_alt_mode and power_clean:
            commands = [
                lpr.INITIALIZE_PRINTER,
                bytes.fromhex("1B 7C 00 06 00 19 07 84 7B 42 0A")  # Ink charge
            ]
        try:
            lpr.connect()
            lpr.send(b"".join(commands))
        except Exception as e:
            logging.error("LPR error: %s", e)
            status = False
        finally:
            lpr.disconnect()
        return status

    def write_first_ti_received_time(
            self, year: int, month: int, day: int) -> bool:
        """Update first TI received time"""
        if not self.parm:
            logging.error("EpsonPrinter - invalid API usage")
            return None
        try:
            msb = self.parm["stats"]["First TI received time"][0]
            lsb = self.parm["stats"]["First TI received time"][1]
        except KeyError:
            logging.info("write_first_ti_received_time: missing parameter")
            return False
        n = (year - 2000) * 16 * 32 + 32 * month + day
        logging.debug(
            "FTRT: %s %s = %s %s",
            hex(n // 256), hex(n % 256), n // 256, n % 256)
        if not self.write_eeprom(msb, n // 256, label="First TI received time"):
            return False
        if not self.write_eeprom(lsb, n % 256, label="First TI received time"):
            return False
        return True

    def write_poweroff_timer(self, mins: int) -> bool:
        """Update power-off timer"""
        if not self.parm:
            logging.error("EpsonPrinter - invalid API usage")
            return None
        try:
            msb = self.parm["stats"]["Power off timer"][0]
            lsb = self.parm["stats"]["Power off timer"][1]
        except KeyError:
            logging.info("write_poweroff_timer: missing parameter")
            return False
        logging.debug(
            "poweroff: %s %s = %s %s",
            hex(mins // 256), hex(mins % 256), mins // 256, mins % 256)
        if not self.write_eeprom(
            msb, mins // 256, label="Write power off timer"
        ):
            return False
        if not self.write_eeprom(
            lsb, mins % 256, label="Write power off timer"
        ):
            return False
        return True

    def list_known_keys(self):
        """ List all known read and write keys for all defined printers. """
        known_keys = []
        for model, chars in self.PRINTER_CONFIG.items():
            if 'write_key' in chars:
                known_keys.append(
                    f"{repr(model).rjust(25)}: "
                    f"{repr(chars['read_key']).rjust(10)} - "
                    f"{repr(chars['write_key'])[1:]}"
                )
            else:
                known_keys.append(
                    f"{repr(model).rjust(25)}: "
                    f"{repr(chars['read_key']).rjust(10)} "
                    f"(unknown write key)"
                )
        return known_keys

    def brute_force_read_key(self, minimum: int = 0x00, maximum: int = 0xFF):
        """Brute force read_key for printer."""
        if not self.parm:
            logging.error("EpsonPrinter - invalid API usage")
            return None
        for x, y in itertools.permutations(range(minimum, maximum + 1), r=2):
            self.parm['read_key'] = [x, y]
            logging.warning(f"Trying {self.parm['read_key']}...")
            val = self.read_eeprom(0x00, label="brute_force_read_key")
            if val is None:
                continue
            return self.parm['read_key']
        return None

    def find_serial_number(self, eeprom_range):
        """
        Detect serial number analyzing eeprom_range addresses
        A valid value for eeprom_range is range(2048)
        """
        # Read the EEPROM data
        hex_bytes = self.read_eeprom_many(
            eeprom_range, label="detect_serial_number"
        )
        if hex_bytes is [None]:
            return hex_bytes, None
        # Convert the hex bytes to characters
        sequence = ''.join(chr(int(byte, 16)) for byte in hex_bytes)
        # Serial number pattern (10 consecutive uppercase letters or digits)
        serial_number_pattern = r'[A-Z0-9]{10}'
        # Find all matches
        return hex_bytes, list(re.finditer(serial_number_pattern, sequence))

    def write_key_list(self, read_key):
        """ Produce a list of distinct write_key prioritizing ones with same read_key """
        write_key_list = []
        for p, v in self.PRINTER_CONFIG.items():
            if (
                'read_key' in v
                and v['read_key'] == read_key
                and 'write_key' in v
                and v['write_key'] not in write_key_list
            ):
                write_key_list.append(v['write_key'])
        for p, v in self.PRINTER_CONFIG.items():
            if (
                'write_key' in v
                and v['write_key'] not in write_key_list
            ):
                write_key_list.append(v['write_key'])
        return write_key_list

    def validate_write_key(self, addr, value, label):
        """ Validate write_key by writing values to the EEPROM """
        if not self.write_eeprom(addr, value + 1, label=label):  # test write
            return None
        ret_value = int(self.read_eeprom(addr), 16)
        if not self.write_eeprom(addr, value, label=label):  # restore previous value
            return None
        if int(self.read_eeprom(addr), 16) != value:
            return None
        return ret_value == value + 1

    def write_sequence_to_string(self, write_sequence):
        """ Convert write key sequence to string """
        try:
            int_sequence = [int(b) for b in write_sequence[0].split(".")]
            return "".join([chr(b-1) for b in int_sequence])
        except Exception:
            return None

    def read_config_file(self, file):
        """
        Read a configuration file including the full log dump of a
        previous operation with '-d' flag and create the internal mib_dict
        dictionary, which is used in place of the SNMP query, simulating them
        instead of accessing the printer via SNMP.
        """
        class NextLine:
            def __init__(self, file):
                self.next_line = None
                self.recursion = 0
                self.file = file

            def readline(self):
                next_line = self.next_line
                if self.next_line != None and self.recursion < 2:
                    self.next_line = None
                    return next_line
                if next_line != None:
                    logginf.error("Recursion error: '%s'", next_line)
                self.next_line = None
                self.recursion = 0
                return next(self.file)

            def pushline(self, line):
                if self.next_line != None:
                    logginf.error(
                        "Line already pushed: '%s', '%s'",
                        self.next_line, line
                    )
                self.next_line = line
                self.recursion += 1
        
        mib_dict = {}
        next_line = NextLine(file)
        process = False
        try:
            while True:
                line = next_line.readline()
                oid = None
                value = None
                process = None
                address_val = None
                response_val = None
                tag_val = None
                response_val_bytes = None
                if line.startswith("PRINTER_STATUS:"):
                    oid = False
                    value = False
                    process = True
                    response_next = True
                if line.startswith("Cartridge "):
                    oid = False
                    value = False
                    process = True
                    response_next = False
                if line.startswith("SNMP_DUMP "):
                    oid = False
                    value = False
                    process = True
                    response_next = False
                if line.startswith("EEPROM_DUMP "):
                    oid = True
                    value = False
                    process = True
                    response_next = False
                if line.startswith("EEPROM_WRITE "):
                    oid = True
                    value = True
                    process = True
                    response_next = False
                if process:
                    # address
                    address_line = next_line.readline()
                    if not address_line.startswith("  ADDRESS: "):
                        logging.error(
                            "Missing ADDRESS: '%s'", address_line.rstrip())
                        next_line.pushline(address_line)
                        continue
                    address_val = address_line[11:].rstrip()
                    if not address_val:
                        logging.error(
                            "Invalid ADDRESS: '%s'", address_line.rstrip())
                        next_line.pushline(address_line)
                        continue
                    # oid
                    if oid:
                        oid_line = next_line.readline()
                        if not oid_line.startswith("  OID: "):
                            logging.error(
                                "Missing OID: '%s'", oid_line.rstrip())
                            next_line.pushline(oid_line)
                            continue
                    # value
                    if value:
                        value_line = next_line.readline()
                        if not value_line.startswith("  VALUE: "):
                            logging.error(
                                "Missing VALUE: '%s'", value_line.rstrip())
                            next_line.pushline(value_line)
                            continue
                    # tag
                    tag_line = next_line.readline()
                    if tag_line.startswith("  TAG: "):
                        tag_val = tag_line[7:].rstrip()
                    if not tag_val:
                        logging.error(
                            "Invalid TAG '%s'", tag_line.rstrip())
                        next_line.pushline(tag_line)
                        continue
                    # response
                    response_line = next_line.readline()
                    if response_line.startswith("  RESPONSE: "):
                        response_val = response_line[12:].rstrip()
                    if not response_val:
                        logging.error(
                            "Invalid RESPONSE '%s'", response_line.rstrip())
                        next_line.pushline(response_line)
                        continue
                    if response_next:
                        dump_hex_str = ""
                        while True:
                            dump_hex = next_line.readline()
                            if not dump_hex.startswith("    "):
                                next_line.pushline(dump_hex)
                                break
                            try:
                                val = bytes.fromhex(dump_hex)
                            except ValueError:
                                next_line.pushline(dump_hex)
                                continue
                            dump_hex_str += dump_hex
                        if not dump_hex_str:
                            logging.error(
                                "Invalid DUMP: '%s'", dump_hex.rstrip())
                            next_line.pushline(dump_hex)
                            continue
                        try:
                            val = bytes.fromhex(dump_hex_str)
                        except ValueError:
                            logging.error(
                                "Invalid DUMP %s", dump_hex_str.rstrip())
                            next_line.pushline(dump_hex)
                            continue
                        if val:
                            mib_dict[address_val] = tag_val, val
                    else:
                        try:
                            response_val_bytes = ast.literal_eval(
                                response_val)
                        except Exception as e:
                            logging.error(
                                "Invalid response %s: %s",
                                response_line.rstrip(),
                                e
                            )
                            next_line.pushline(response_line)
                            continue
                        if response_val_bytes:
                            mib_dict[address_val] = tag_val, response_val_bytes
                        else:
                            logging.error(
                                "Null value for response %s",
                                response_line.rstrip()
                            )
                            next_line.pushline(response_line)
        except StopIteration:
            pass
        if process:
            logging.error("EOF while processing record set")
        self.mib_dict = mib_dict
        return mib_dict

    def write_simdata(self, file):
        """
        Convert the internal mib_dict dictionary into a configuration file
        (named simdata configuration file) compatible with
        https://github.com/etingof/snmpsim/
        """
        tagnum = {
            "OctetString": "4x",
            "TimeTicks": "2",  # 64
            "Integer": "2",
        }
        try:
            for key, (tag, value) in self.mib_dict.items():
                if tag == "OctetString":
                    if isinstance(value, bytes):
                        write_line = f"{key}|{tagnum[tag]}|{value.hex()}\n"
                    else:
                        logging.error(
                            "OctetString is not byte type: key=%s, tag=%s, "
                            "value=%s, type=%s",
                            key, tag, value, type(value)
                        )
                        continue
                else:
                    write_line = f"{key}|{tagnum[tag]}|{value}\n"
                file.write(write_line)
            file.close()
        except Exception as e:
            logging.error("simdata write error: %s", e)
            return False
        return True


def get_printer_models(input_string):
    # Tokenize the string
    tokens = re.split(" |/", input_string)
    if not len(tokens):
        return []

    # Define the words to remove (uppercase, then case insensitive)
    remove_tokens = {"EPSON", "SERIES"}

    # Process tokens
    processed_tokens = []
    non_numeric_part = ""
    pre_model = ""
    for token in tokens:
        upper_token = token.upper()

        # Remove tokens that match remove_tokens
        if any(word == upper_token for word in remove_tokens):
            continue
        if not any(char.isdigit() for char in token):  # no alphanum inside
            pre_model = pre_model + token + " "
            continue
        # Identify the non-numeric part of the first token
        if not token.isnumeric() and not non_numeric_part:
            non_numeric_part = "".join(c for c in token if not c.isdigit())
        # if token is numeric, prepend the non-numeric part
        if token.isnumeric():
            processed_tokens.append(f"{pre_model}{non_numeric_part}{token}")
        else:
            processed_tokens.append(f"{pre_model}{token}")
    if not processed_tokens and pre_model:
        processed_tokens.append(pre_model.strip())
    return processed_tokens


if __name__ == "__main__":
    import argparse
    from pprint import pprint

    def auto_int(x):
        return int(x, 0)

    parser = argparse.ArgumentParser(
        epilog='Epson Printer Configuration via SNMP (TCP/IP)'
    )

    parser.add_argument(
        '-m',
        '--model',
        dest='model',
        action="store",
        help='Printer model. Example: -m XP-205'
        ' (use ? to print all supported models)',
        required=True
    )
    parser.add_argument(
        '-a',
        '--address',
        dest='hostname',
        action="store",
        help='Printer host name or IP address. (Example: -a 192.168.1.87)',
        required=True
    )
    parser.add_argument(
        '-p',
        '--port',
        dest='port',
        type=auto_int,
        default=161,
        action="store",
        help='Printer port (default is 161)'
    )
    parser.add_argument(
        '-i',
        '--info',
        dest='info',
        action='store_true',
        help='Print all available information and statistics (default option)'
    )
    parser.add_argument(
        '-q',
        '--query',
        dest='query',
        action='store',
        type=str,
        nargs=1,
        metavar='QUERY_NAME',
        help='Print specific information.'
        ' (Use ? to list all available queries)'
    )
    parser.add_argument(
        '--reset_waste_ink',
        dest='reset_waste_ink',
        action='store_true',
        help='Reset all waste ink levels to 0'
    )
    parser.add_argument(
        '--temp_reset_waste_ink',
        dest='temporary_reset_waste',
        action='store_true',
        help='Temporary reset waste ink levels'
    )
    parser.add_argument(
        '-d',
        '--debug',
        dest='debug',
        action='store_true',
        help='Print debug information'
    )
    parser.add_argument(
        '--write-first-ti-received-time',
        dest='ftrt',
        type=int,
        help='Change the first TI received time',
        nargs=3,
        metavar=('YEAR', 'MONTH', 'DAY'),
    )
    parser.add_argument(
        '--write-poweroff-timer',
        dest='poweroff',
        type=auto_int,
        help='Update the poweroff timer. Use 0xffff or 65535 to disable it.',
        nargs=1,
        metavar=('MINUTES'),
    )
    parser.add_argument(
        '--dry-run',
        dest='dry_run',
        action='store_true',
        help='Dry-run change operations'
    )
    parser.add_argument(
        '-R',
        '--read-eeprom',
        dest='read_eeprom',
        action='store',
        type=str,
        nargs=1,
        metavar='ADDRESS_SET',
        help='Read the values of a list of printer EEPROM addreses.'
        ' Format is: address [, ...]'
    )
    parser.add_argument(
        '-W',
        '--write-eeprom',
        dest='write_eeprom',
        action='store',
        type=str,
        nargs=1,
        metavar='ADDRESS_VALUE_SET',
        help='Write related values to a list of printer EEPROM addresses.'
        ' Format is: address: value [, ...]'
    )
    parser.add_argument(
        '-e',
        '--eeprom-dump',
        dest='dump_eeprom',
        action='store',
        type=str,
        nargs=2,
        metavar=('FIRST_ADDRESS', 'LAST_ADDRESS'),
        help='Dump EEPROM'
    )
    parser.add_argument(
        "--detect-key",
        dest='detect_key',
        action='store_true',
        help="Detect the read_key via brute force"
    )
    parser.add_argument(
        '-S',
        '--write-sequence-to-string',
        dest='ws_to_string',
        action='store',
        type=str,
        nargs=1,
        metavar='SEQUENCE_STRING',
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
    parser.add_argument(
        '-c',
        "--config",
        dest='config_file',
        type=argparse.FileType('r'),
        help="read a configuration file including the full log dump of a "
             "previous operation with '-d' flag (instead of accessing the "
             "printer via SNMP)",
        default=0,
        nargs=1,
        metavar='CONFIG_FILE'
    )
    parser.add_argument(
        "--simdata",
        dest='simdata_file',
        type=argparse.FileType('a'),
        help="write SNMP dictionary map to simdata file",
        default=0,
        nargs=1,
        metavar='SIMDATA_FILE'
    )
    parser.add_argument(
        '-P',
        "--pickle",
        dest='pickle',
        type=argparse.FileType('rb'),
        help="Load a pickle configuration archive saved by parse_devices.py",
        default=None,
        nargs=1,
        metavar='PICKLE_FILE'
    )
    parser.add_argument(
        '-O',
        "--override",
        dest='override',
        action='store_true',
        help="Replace the default configuration with the one in the pickle "
            "file instead of merging (default is to merge)",
    )
    args = parser.parse_args()

    logging_level = logging.WARNING
    logging_fmt = "%(message)s"
    env_key=os.path.basename(Path(__file__).stem).upper() + '_LOG_CFG'
    path = Path(__file__).stem + '-log.yaml'
    value = os.getenv(env_key, None)
    #print("Configuration file:", path, "| Environment variable:", env_key)
    if value:
        path = value
    if os.path.exists(path):
        with open(path, 'rt') as f:
            config = yaml.safe_load(f.read())
        try:
            logging.config.dictConfig(config)
        except Exception as e:
            logging.basicConfig(level=logging_level, format=logging_fmt)
            logging.critical("Cannot configure logs: %s. %s", e, path)
    else:
        logging.basicConfig(level=logging_level, format=logging_fmt)

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    conf_dict = {}
    if args.pickle:
        try:
            conf_dict = pickle.load(args.pickle[0])
        except Exception as e:
            print("Error while loading the pickle file:", e)
            quit(1)

    printer = EpsonPrinter(
        conf_dict=conf_dict,
        replace_conf=args.override,
        model=args.model,
        hostname=args.hostname,
        port=args.port,
        timeout=args.timeout,
        retries=args.retries,
        dry_run=args.dry_run)
    if args.config_file:
        if not printer.read_config_file(args.config_file[0]):
            print("Error while reading configuration file")
            quit(1)
        args.config_file[0].close()
    if args.simdata_file:
        if not printer.write_simdata(args.simdata_file[0]):
            print("Error while writing simdata file")
            quit(1)
        args.simdata_file[0].close()
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
            print(printer.write_sequence_to_string(args.ws_to_string))
        if args.reset_waste_ink:
            print_opt = True
            if printer.reset_waste_ink_levels():
                print("Reset waste ink levels done.")
            else:
                print("Failed to reset waste ink levels. Check configuration.")
        if args.temporary_reset_waste:
            print_opt = True
            if printer.temporary_reset_waste():
                print("Temporary reset waste ink levels done.")
            else:
                print("Failed to temporarily reset waste ink levels.")
        if args.detect_key:
            print_opt = True
            read_key = printer.brute_force_read_key()
            if read_key:
                print(f"read_key found: {read_key}")
                print("List of known keys:")
                print("\n".join(printer.list_known_keys()))
            else:
                print(f"Could not detect read_key.")
        if args.ftrt:
            print_opt = True
            if printer.write_first_ti_received_time(
                    int(args.ftrt[0]), int(args.ftrt[1]), int(args.ftrt[2])):
                print("Write first TI received time done.")
            else:
                print(
                    "Failed to write first TI received time."
                    " Check configuration."
                )
        if args.poweroff:
            print_opt = True
            if printer.write_poweroff_timer(args.poweroff[0]):
                print(
                    "Write power off timer done ("
                    + str(args.poweroff[0])
                    + " minutes)."
                )
            else:
                print(
                    "Failed to write power off timer."
                    " Check configuration."
                )
        if args.dump_eeprom:
            print_opt = True
            start = int(ast.literal_eval(args.dump_eeprom[0]))
            end   = int(ast.literal_eval(args.dump_eeprom[1]))
            for addr, val in printer.dump_eeprom(start, end).items():
                if val is None:
                    disp_val = "  --"
                else:
                    disp_val = f"{val:#04x}"  # 0x00 … 0xFF
                print(f"EEPROM_ADDR 0x{addr:02X} = {addr:3d}: {disp_val}")
        if args.query:
            print_opt = True
            if ("stats" in printer.parm and
                    args.query[0] in printer.parm["stats"]):
                ret = printer.get_stats(args.query[0])
                if ret:
                    pprint(ret, width=100, compact=True)
                else:
                    print("No information returned. Check printer definition.")
            elif args.query[0] in printer.MIB_INFO.keys():
                ret = printer.get_snmp_info(args.query[0])
                if ret:
                    pprint(ret, width=100, compact=True)
                else:
                    print("No information returned. Check printer definition.")
            else:
                if args.query[0].startswith("get_"):
                    method = args.query[0]
                else:
                    method = "get_" + args.query[0]
                if method in printer.list_methods:
                    ret = printer.__getattribute__(method)()
                    if ret:
                        pprint(ret, width=100, compact=True)
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
                            ", ".join(printer.MIB_INFO.keys()),
                            initial_indent='', subsequent_indent='  '
                        )
                    )
        if args.read_eeprom:
            print_opt = True
            read_list = re.split(r',\s*', args.read_eeprom[0])
            for value in read_list:
                try:
                    addr = int(ast.literal_eval(value))
                    val = printer.read_eeprom(addr, label='read_eeprom')
                    if val is None:
                        print("EEPROM read error.")
                    else:
                        print(
                            f"EEPROM_ADDR {hex(addr).rjust(4)} = "
                            f"{str(addr).rjust(3)}: "
                            f"0x{val.rjust(2)} = {int(val,16)}"
                        )
                except (ValueError, SyntaxError):
                    print("invalid argument for read_eeprom")
                    quit(1)
        if args.write_eeprom:
            print_opt = True
            read_list = re.split(r',\s*|;\s*|\|\s*', args.write_eeprom[0])
            for key_val in read_list:
                key, val = re.split(':|=', key_val)
                try:
                    val_int = ast.literal_eval(val)
                    if not printer.write_eeprom(
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
                pprint(ret, width=100, compact=True)
            else:
                print("No information returned. Check printer definition.")
    except TimeoutError as e:
        print(f"Timeout error: {str(e)}")
    except ValueError as e:
        raise(f"Generic error: {str(e)}")
    except KeyboardInterrupt:
        quit(2)

# epson_print_conf

Epson Printer Configuration tool via SNMP (TCP/IP)

## Features

- Access the Epson printer via SNMP (TCP/IP; printer connected over Wi-Fi)
- Print the advanced status of the printer, with the possibility to restrict the query to specific information
- Other inspection features:
	- Read and write EEPROM addresses
	- Dump a set of EEPROM addresses
	- Reset ink waste
    - Change power off timer
	- Other admin stuffs and debug options
- Command line tool (no GUI)
- Python API interface

The software also provides a configurable printer dictionary, which can be easily extended. There is also a tool to import an extensive Epson printer configuration DB.

## Installation

```
git clone https://github.com/Ircama/epson_print_conf
pip3 install pyyaml
pip3 install pyasn1==0.4.8
pip3 install git+https://github.com/etingof/pysnmp.git
cd epson_print_conf
```

Notes (at the time of writing):

- [before pysnmp, install pyasn1 with version 0.4.8 and not 0.5](https://github.com/etingof/pysnmp/issues/440#issuecomment-1544341598)
- [pull pysnmp from the GitHub master branch, not from PyPI](https://stackoverflow.com/questions/54868134/snmp-reading-from-an-oid-with-three-libraries-gives-different-execution-times#comment96532761_54869361)

This program exploits [pysnmp](https://github.com/etingof/pysnmp), with related [documentation](https://pysnmp.readthedocs.io/).

It is tested with Ubuntu / Windows Subsystem for Linux, Windows.

## Usage

```
usage: epson_print_conf.py [-h] -m MODEL -a HOSTNAME [-p PORT] [-i] [-q QUERY_NAME] [--reset_waste_ink] [-d]
                           [--write-first-ti-received-time YEAR MONTH DAY] [--write-poweroff-timer MINUTES]
                           [--dry-run] [-R ADDRESS_SET] [-W ADDRESS_VALUE_SET]
                           [-e FIRST_ADDRESS LAST_ADDRESS] [--detect-key] [-S SEQUENCE_STRING] [-t TIMEOUT]
                           [-r RETRIES] [-c CONFIG_FILE] [--simdata SIMDATA_FILE]

optional arguments:
  -h, --help            show this help message and exit
  -m MODEL, --model MODEL
                        Printer model. Example: -m XP-205 (use ? to print all supported models)
  -a HOSTNAME, --address HOSTNAME
                        Printer host name or IP address. (Example: -m 192.168.1.87)
  -p PORT, --port PORT  Printer port (default is 161)
  -i, --info            Print all available information and statistics (default option)
  -q QUERY_NAME, --query QUERY_NAME
                        Print specific information. (Use ? to list all available queries)
  --reset_waste_ink     Reset all waste ink levels to 0
  -d, --debug           Print debug information
  --write-first-ti-received-time YEAR MONTH DAY
                        Change the first TI received time
  --write-poweroff-timer MINUTES
                        Update the poweroff timer. Use 0xffff or 65535 to disable it.
  --dry-run             Dry-run change operations
  -R ADDRESS_SET, --read-eeprom ADDRESS_SET
                        Read the values of a list of printer EEPROM addreses. Format is: address [, ...]
  -W ADDRESS_VALUE_SET, --write-eeprom ADDRESS_VALUE_SET
                        Write related values to a list of printer EEPROM addresses. Format is: address: value
                        [, ...]
  -e FIRST_ADDRESS LAST_ADDRESS, --eeprom-dump FIRST_ADDRESS LAST_ADDRESS
                        Dump EEPROM
  --detect-key          Detect the read_key via brute force
  -S SEQUENCE_STRING, --write-sequence-to-string SEQUENCE_STRING
                        Convert write sequence of numbers to string.
  -t TIMEOUT, --timeout TIMEOUT
                        SNMP GET timeout (floating point argument)
  -r RETRIES, --retries RETRIES
                        SNMP GET retries (floating point argument)
  -c CONFIG_FILE, --config CONFIG_FILE
                        read a configuration file including the full log dump of a previous operation with
                        '-d' flag (instead of accessing the printer via SNMP)
  --simdata SIMDATA_FILE
                        write SNMP dictionary map to simdata file

Epson Printer Configuration via SNMP (TCP/IP)
```

Examples:

```bash
# Print the status information (-i is not needed):
python3 epson_print_conf.py -m XP-205 -a 192.168.1.87 -i

# Reset all waste ink levels to 0:
python3 epson_print_conf.py -m XP-205 -a 192.168.1.87 --reset_waste_ink

# Change the first TI received time to 31 December 2016:
python3 epson_print_conf.py -m XP-205 -a 192.168.1.87 --write-first-ti-received-time 2016 12 31

# Change the power off timer to 15 minutes:
python3 epson_print_conf.py -a 192.168.1.87 -m XP-205 --write-poweroff-timer 15

# Detect the read_key via brute force:
python3 epson_print_conf.py -m XP-205 -a 192.168.1.87 --detect-key

# Only print status information:
python3 epson_print_conf.py -m XP-205 -a 192.168.1.87 -q printer_status

# Only print SNMP 'MAC Address' name:
python3 epson_print_conf.py -m XP-205 -a 192.168.1.87 -q 'MAC Address'

# Only print SNMP 'Lang 5' name:
python3 epson_print_conf.py -m XP-205 -a 192.168.1.87 -q 'Lang 5'

# Write value 1 to the EEPROM address 173 and value 0xDE to the EEPROM address 172:
python3 epson_print_conf.py -m XP-205 -a 192.168.1.87 -W 173:1,172:0xde

# Read EEPROM address 173 and EEPROM address 172:
python3 epson_print_conf.py -m XP-205 -a 192.168.1.87 -R 173,172
```

Note: resetting the ink waste counter is just removing a warning; not replacing the tank will make the ink spill.

## Utilities and notes

### parse_devices.py

Within an [issue](https://codeberg.org/atufi/reinkpy/issues/12#issue-716809) in repo https://codeberg.org/atufi/reinkpy there is an interesting [attachment](https://codeberg.org/attachments/147f41a3-a6ea-45f6-8c2a-25bac4495a1d) which reports an extensive XML database of Epson model features.

The program "parse_devices.py" transforms this XML DB into the dictionary that *epson_print_conf.py* can use.

Here is a simple procedure to download that DB and run *parse_devices.py* to search for the XP-205 model and produce the related PRINTER_CONFIG dictionary to the standard output:

```bash
curl -o devices.xml https://codeberg.org/attachments/147f41a3-a6ea-45f6-8c2a-25bac4495a1d
python3 parse_devices.py -m XP-205
```

After generating the related printer configuration, *epson_print_conf.py* shall be manually edited to copy/paste the output of *parse_devices.py* within its PRINTER_CONFIG dictionary.

The `-m` option is mandatory and is used to filter the printer model in scope. If the produced output is not referred to the target model, use part of the model name as a filter (e.g., only the digits, like `parse_devices.py -m 315`) and select the appropriate model from the output.

Program usage:

```
python3 parse_devices.py [-h] -m PRINTER_MODEL [-d] [-t] [-v] [-f] [-e] [-c CONFIG_FILE]

optional arguments:
  -h, --help            show this help message and exit
  -m PRINTER_MODEL, --model PRINTER_MODEL
                        Printer model. Example: -m XP-205
  -d, --debug           Print debug information
  -t, --traverse        Traverse the XML, dumping content related to the printer model
  -v, --verbose         Print verbose information
  -f, --full            Generate additional tags
  -e, --errors          Add last_printer_fatal_errors
  -c CONFIG_FILE, --config CONFIG_FILE
                        use the XML configuration file to generate the configuration

Generate printer configuration from devices.xml
```

The output is better viewed when also installing [black](https://pypi.org/project/black/).

### Other utilities

```
import epson_print_conf
import pprint
printer = epson_print_conf.EpsonPrinter()

# Decode write_key:
printer.reverse_caesar(bytes.fromhex("48 62 7B 62 6F 6A 62 2B"))  # last 8 bytes
'Gazania*'

printer.reverse_caesar(b'Hpttzqjv')
'Gossypiu'

"".join(chr(b + 1) for b in b'Gossypiu')
'Hpttzqjv'

# Decode status:
pprint.pprint(printer.status_parser(bytes.fromhex("40 42 44 43 20 53 54 32 0D 0A ....")))

# Decode the level of ink waste
byte_sequence = "A4 2A"
divider = 62.06  # divider = ink_level / waste_percent
ink_level = int("".join(reversed(byte_sequence.split())), 16)
waste_percent = round(ink_level / divider, 2)

# Print the read key sequence in byte and hex formats:
printer = epson_print_conf.EpsonPrinter(model="ET-2700")
'.'.join(str(x) for x in printer.parm['read_key'])
" ".join('{0:02x}'.format(x) for x in printer.parm['read_key'])

# Print the write key sequence in byte and hex formats:
printer = epson_print_conf.EpsonPrinter(model="ET-2700")
printer.caesar(printer.parm['write_key'])
printer.caesar(printer.parm['write_key'], hex=True).upper()

# Print hex sequence of reading the value of EEPROM address 30 00:
" ".join('{0:02x}'.format(int(x)) for x in printer.eeprom_oid_read_address(oid=0x30).split(".")[15:]).upper()

# Print hex sequence of storing value 00 to EEPROM address 30 00:
" ".join('{0:02x}'.format(int(x)) for x in printer.eeprom_oid_write_address(oid=0x30, value=0x0).split(".")[15:]).upper()

# Print EEPROM write hex sequence of the raw ink waste reset:
for key, value in printer.parm["raw_waste_reset"].items():
    " ".join('{0:02x}'.format(int(x)) for x in printer.eeprom_oid_write_address(oid=key, value=value).split(".")[15:]).upper()
```

Generic query of the status of the printer (regardless of the model):

```
import epson_print_conf
import pprint
printer = epson_print_conf.EpsonPrinter(hostname="192.168.1.87")
pprint.pprint(printer.status_parser(printer.snmp_mib("1.3.6.1.4.1.1248.1.2.2.1.1.1.4.1")[1]))
```

### Byte sequences

Header:

```
1.3.6.1.4.1. [SNMP_OID_ENTERPRISE]
1248. [SNMP_EPSON]

1.2.2.44.1.1.2. [OID_PRV_CTRL]
1.
```

Full header sequence: `1.3.6.1.4.1.1248.1.2.2.44.1.1.2.1.`

Read EEPROM (EPSON-CTRL), after the header:

```
124.124.7.0. [7C 7C 07 00]
<READ KEY (two bytes)>
65.190.160. [41 BE A0]
<LSB EEPROM ADDRESS (one byte)>.<MSB EEPROM ADDRESS (one byte)>
```

Example: `1.3.6.1.4.1.1248.1.2.2.44.1.1.2.1.124.124.7.0.73.8.65.190.160.48.0`

Write EEPROM, after the header:

```
7C 7C 10 00 [124.124.16.0.]
<READ KEY (two bytes)>
42 BD 21 [66.189.33.]
<LSB EEPROM ADDRESS (one byte)>.<MSB EEPROM ADDRESS (one byte)>
<VALUE (one byte)>
<WRITE KEY (eight bytes)>
```

Example: `7C 7C 10 00 49 08 42 BD 21 30 00 1A 42 73 62 6F 75 6A 67 70`

Example of Read EEPROM (@BDC PS):

```
<01> @BDC PS <0d0a> EE:0032AC;
EE: = EEPROM Read
0032 = Memory address
AC = Value
```

## API Interface

### Specification

```python
EpsonPrinter(model, hostname, port, timeout, retries, dry_run)
```

- `model`: printer model
- `hostname`: IP address or network name of the printer
- `port`: SNMP port number (default is 161)
- `timeout`: printer connection timeout in seconds (float)
- `retries`: connection retries if error or timeout occurred
- `dry_run`: boolean (True if write dry-run mode is enabled)

### Exceptions

```
TimeoutError
ValueError
```

(And *pysnmp* exceptions.)

### Sample

```python
import epson_print_conf
import logging

logging.basicConfig(level=logging.DEBUG, format="%(message)s")  # if logging is needed

printer = epson_print_conf.EpsonPrinter(
    model="XP-205", hostname="192.168.1.87")

if not printer.parm:
    print("Unknown printer")
    quit()

stats = printer.stats()
print("stats:", stats)

ret = printer.get_snmp_info()
print("get_snmp_info:", ret)
ret = printer.get_serial_number()
print("get_serial_number:", ret)
ret = printer.get_firmware_version()
print("get_firmware_version:", ret)
ret = printer.get_printer_head_id()
print("get_printer_head_id:", ret)
ret = printer.get_cartridges()
print("get_cartridges:", ret)
ret = printer.get_printer_status()
print("get_printer_status:", ret)
ret = printer.get_ink_replacement_counters()
print("get_ink_replacement_counters:", ret)
ret = printer.get_waste_ink_levels()
print("get_waste_ink_levels:", ret)
ret = printer.get_last_printer_fatal_errors()
print("get_last_printer_fatal_errors:", ret)
ret = printer.get_stats()
print("get_stats:", ret)

printer.reset_waste_ink_levels()
printer.brute_force_read_key()
printer.write_first_ti_received_time(2000, 1, 2)
```

## Output example
Example of advanced printer status with an XP-205 printer:

```python
{'cartridge_information': [{'data': '0D081F172A0D04004C',
                            'ink_color': [1811, 'Black'],
                            'ink_quantity': 76,
                            'production_month': 8,
                            'production_year': 2013},
                           {'data': '15031D06230D080093',
                            'ink_color': [1814, 'Yellow'],
                            'ink_quantity': 69,
                            'production_month': 3,
                            'production_year': 2021},
                           {'data': '150317111905020047',
                            'ink_color': [1813, 'Magenta'],
                            'ink_quantity': 49,
                            'production_month': 3,
                            'production_year': 2021},
                           {'data': '14091716080501001D',
                            'ink_color': [1812, 'Cyan'],
                            'ink_quantity': 29,
                            'production_month': 9,
                            'production_year': 2020}],
 'cartridges': ['18XL', '18XL', '18XL', '18XL'],
 'firmware_version': 'RF11I5 11 May 2018',
 'ink_replacement_counters': {('Black', '1B', 1),
                              ('Black', '1L', 19),
                              ('Black', '1S', 2),
                              ('Cyan', '1B', 1),
                              ('Cyan', '1L', 8),
                              ('Cyan', '1S', 1),
                              ('Magenta', '1B', 1),
                              ('Magenta', '1L', 6),
                              ('Magenta', '1S', 1),
                              ('Yellow', '1B', 1),
                              ('Yellow', '1L', 10),
                              ('Yellow', '1S', 1)},
 'last_printer_fatal_errors': ['08', 'F1', 'F1', 'F1', 'F1', '10'],
 'printer_head_id': '...',
 'printer_status': {'cancel_code': 'No request',
                    'ink_level': [(1, 0, 'Black', 'Black', 76),
                                  (5, 3, 'Yellow', 'Yellow', 69),
                                  (4, 2, 'Magenta', 'Magenta', 49),
                                  (3, 1, 'Cyan', 'Cyan', 29)],
                    'jobname': 'Not defined',
                    'loading_path': 'fixed',
                    'maintenance_box_1': 'not full (0)',
                    'maintenance_box_2': 'not full (0)',
                    'maintenance_box_reset_count_1': 0,
                    'maintenance_box_reset_count_2': 0,
                    'paper_path': 'Cut sheet (Rear)',
                    'ready': True,
                    'status': (4, 'Idle'),
                    'unknown': [('0x24', b'\x0f\x0f')]},
 'serial_number': '...',
 'snmp_info': {'Descr': 'EPSON Built-in 11b/g/n Print Server',
               'EEPS2 firmware version': 'EEPS2 Hard Ver.1.00 Firm Ver.0.50',
               'Emulation 1': 'unknown',
               'Emulation 2': 'ESC/P2',
               'Emulation 3': 'BDC',
               'Emulation 4': 'other',
               'Emulation 5': 'other',
               'Epson Model': 'XP-205 207 Series',
               'IP Address': '192.168.1.87',
               'IPP_URL': 'http://192.168.1.87:631/Epson_IPP_Printer',
               'IPP_URL_path': 'Epson_IPP_Printer',
               'Lang 1': 'unknown',
               'Lang 2': 'ESCPL2',
               'Lang 3': 'BDC',
               'Lang 4': 'D4',
               'Lang 5': 'ESCPR1',
               'MAC Addr': '...',
               'MAC Address': '...',
               'Model': 'EPSON XP-205 207 Series',
               'Model short': 'XP-205 207 Series',
               'Name': '...',
               'Power Off Timer': '0.5 hours',
               'Print input': 'Auto sheet feeder',
               'Total printed pages': '0',
               'UpTime': '00:02:08',
               'WiFi': '...',
               'device_id': 'MFG:EPSON;CMD:ESCPL2,BDC,D4,D4PX,ESCPR1;MDL:XP-205 '
                            '207 Series;CLS:PRINTER;DES:EPSON XP-205 207 '
                            'Series;CID:EpsonRGB;FID:FXN,DPN,WFA,ETN,AFN,DAN;RID:40;'},
 'stats': {'First TI received time': '...',
           'Ink replacement cleaning counter': 78,
           'Maintenance required level of 1st waste ink counter': 94,
           'Maintenance required level of 2nd waste ink counter': 94,
           'Manual cleaning counter': 129,
           'Timer cleaning counter': 4,
           'Total print page counter': 11569,
           'Total print pass counter': 514602,
           'Total scan counter': 4973,
           'Power off timer': 30},
 'waste_ink_levels': {'borderless_waste': 4.72, 'main_waste': 90.8}}
 ```

## Resources

### snmpget (Linux)

Installation:

```
sudo apt-get install snmp
```

Usage:

```
# Read address 173.0
snmpget -v1 -d -c public 192.168.1.87 1.3.6.1.4.1.1248.1.2.2.44.1.1.2.1.124.124.7.0.25.7.65.190.160.173.0

# Read address 172.0
snmpget -v1 -d -c public 192.168.1.87 1.3.6.1.4.1.1248.1.2.2.44.1.1.2.1.124.124.7.0.25.7.65.190.160.172.0

# Write 25 to address 173.0
snmpget -v1 -d -c public 192.168.1.87 1.3.6.1.4.1.1248.1.2.2.44.1.1.2.1.124.124.16.0.25.7.66.189.33.173.0.25.88.98.108.98.117.112.99.106

# Write 153 to address 172.0
snmpget -v1 -d -c public 192.168.1.87 1.3.6.1.4.1.1248.1.2.2.44.1.1.2.1.124.124.16.0.25.7.66.189.33.172.0.153.88.98.108.98.117.112.99.106
```

### References

epson-printer-snmp: https://github.com/Zedeldi/epson-printer-snmp (and https://github.com/Zedeldi/epson-printer-snmp/issues/1)

ReInkPy: https://codeberg.org/atufi/reinkpy/

ReInk: https://github.com/lion-simba/reink (especially https://github.com/lion-simba/reink/issues/1)

reink-net: https://github.com/gentu/reink-net

epson-l4160-ink-waste-resetter: https://github.com/nicootto/epson-l4160-ink-waste-resetter

epson-l3160-ink-waste-resetter: https://github.com/k3dt/epson-l3160-ink-waste-resetter

emanage x900: https://github.com/abrasive/x900-otsakupuhastajat/

### Other programs

- Epson One-Time Maintenance Ink Pad Reset Utility: https://epson.com/Support/wa00369
  - Epson Maintenance Reset Utility: https://epson.com/epsonstorefront/orbeon/fr/us_regular_s03/us_ServiceInk_Pad_Reset/new
  - Epson Ink Pads Reset Utility Terms and Conditions: https://epson.com/Support/wa00370
- Epson Adjustment Program (developed by EPSON)
- WIC-Reset: https://wic-reset.com / https://www.2manuals.com / https://resetters.com (Use at your risk)
- PrintHelp: https://printhelp.info/ (Use at your risk)

### Resources

- https://codeberg.org/attachments/147f41a3-a6ea-45f6-8c2a-25bac4495a1d
- https://codeberg.org/atufi/reinkpy/src/branch/main/reinkpy/epson.toml

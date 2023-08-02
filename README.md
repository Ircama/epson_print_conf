# epson_print_conf
Epson Printer Configuration tool via SNMP (TCP/IP)

## Features
- Access the Epson printer via SNMP (TCP/IP)
- Print advanced printer status, with the possibility to restrict the query to specific information
- Other inspection feattures:
	- Read and write EEPROM addresses
	- Dump a set of EEPROM addresses
	- Reset ink waste
	- Other admin stuff and debug options
- Command line tool (no GUI)
- Python API interface

The software also provides a configurable printer dictionary, which can be easily extended.

## Installation

```
git clone https://github.com/Ircama/epson_print_conf
pip3 install easysnmp
cd epson_print_conf
```

## Usage

```
usage: epson_print_conf.py [-h] -m MODEL -a HOSTNAME [-i] [-q QUERY] [--reset_waste_ink] [--detect-key] [-d]
                           [-e DUMP_EEPROM DUMP_EEPROM] [--dry-run] [--write-first-ti-received-time FTRT FTRT FTRT]
                           [-R READ_EEPROM] [-W WRITE_EEPROM] [-S WS_TO_STRING]

optional arguments:
  -h, --help            show this help message and exit
  -m MODEL, --model MODEL
                        Printer model. Example: -m XP-205 (use ? to print all supported models)
  -a HOSTNAME, --address HOSTNAME
                        Printer host name or IP address. (Example: -m 192.168.1.87)
  -i, --info            Print all available information and statistics (default option)
  -q QUERY, --query QUERY
                        Print specific information. (Use ? to list all available queries)
  --reset_waste_ink     Reset all waste ink levels to 0
  --detect-key          Detect the read_key via brute force
  -d, --debug           Print debug information
  -e DUMP_EEPROM DUMP_EEPROM, --eeprom-dump DUMP_EEPROM DUMP_EEPROM
                        Dump EEPROM (arguments: start, stop)
  --dry-run             Dry-run change operations
  --write-first-ti-received-time FTRT FTRT FTRT
                        Change the first TI received time (arguments: year, month, day)
  -R READ_EEPROM, --read-eeprom READ_EEPROM
                        Read the values of a list of printer EEPROM addreses. Format is: address [, ...]
  -W WRITE_EEPROM, --write-eeprom WRITE_EEPROM
                        Write related values to a list of printer EEPROM addresses. Format is: address: value [, ...]
  -S WS_TO_STRING, --write-sequence-to-string WS_TO_STRING
                        Convert write sequence of numbers to string.

Epson Printer Configuration accessed via SNMP (TCP/IP)
```

Examples:

```
# Print informations (-i is not needed):
python3 epson_print_conf.py -m XP-205 -a 192.168.1.87 -i

# Reset all waste ink levels to 0:
python3 epson_print_conf.py -m XP-205 -a 192.168.1.87 --reset_waste_ink

# Change the first TI received time to 31 December 2016:
python3 epson_print_conf.py -m XP-205 -a 192.168.1.87 --write-first-ti-received-time 2016 12 31

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

## API Interface

```python
import epson_print_conf
printer = epson_print_conf.EpsonPrinter("XP-205", "192.168.1.87")

if not printer.parm:
    print("Unknown printer")
    quit()

stats = printer.stats()
print("stats:", stats)

ret = printer.session.get_snmp_info()
print("get_snmp_info:", ret)
ret = printer.session.get_serial_number()
print("get_serial_number:", ret)
ret = printer.session.get_firmware_version()
print("get_firmware_version:", ret)
ret = printer.session.get_printer_head_id()
print("get_printer_head_id:", ret)
ret = printer.session.get_cartridges()
print("get_cartridges:", ret)
ret = printer.session.get_printer_status()
print("get_printer_status:", ret)
ret = printer.session.get_ink_replacement_counters()
print("get_ink_replacement_counters:", ret)
ret = printer.session.get_waste_ink_levels()
print("get_waste_ink_levels:", ret)
ret = printer.session.get_last_printer_fatal_errors()
print("get_last_printer_fatal_errors:", ret)
ret = printer.session.get_stats()
print("get_stats:", ret)

printer.session.reset_waste_ink_levels()
printer.session.detect_key()
printer.session.write_first_ti_received_time(2000, 1, 2)
```

### Exceptions

```
TimeoutError
ValueError
```

## Output example

```
{'cartridges': ['18XL', '18XL', '18XL', '18XL'],
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
                    'ink_level': [(1, 89, 'Black'),
                                  (5, 77, 'Yellow'),
                                  (4, 59, 'Magenta'),
                                  (3, 40, 'Cyan')],
                    'jobname': 'Not defined',
                    'loading_path': 'fixed',
                    'maintenance_box_0': 'not full (0)',
                    'maintenance_box_1': 'not full (0)',
                    'paper_path': 'Cut sheet (Rear)',
                    'ready': True,
                    'replace_cartridge': '00000001',
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
               'IP Address': '192.168.1.87',
               'Lang 1': 'unknown',
               'Lang 2': 'ESCPL2',
               'Lang 3': 'BDC',
               'Lang 4': 'D4',
               'Lang 5': 'ESCPR1',
               'MAC Address': '...',
               'Model': 'EPSON XP-205 207 Series',
               'Model short': 'XP-205 207 Series',
               'Name': '....',
               'Print counter': '0',
               'Print input': 'Auto sheet feeder',
               'URL': 'http://192.168.1.87:631/Epson_IPP_Printer',
               'URL_path': 'Epson_IPP_Printer',
               'UpTime': '00:57:48',
               'WiFi': '....',
               'device_id': 'MFG:EPSON;CMD:ESCPL2,BDC,D4,D4PX,ESCPR1;MDL:XP-205 207 '
                            'Series;CLS:PRINTER;DES:EPSON XP-205 207 '
                            'Series;CID:EpsonRGB;FID:FXN,DPN,WFA,ETN,AFN,DAN;RID:40;',
               'hex_data': 'A4 EE 57 DE FD 03'},
 'stats': {'First TI received time': '...',
           'Ink replacement cleaning counter': 78,
           'Maintenance required level of 1st waste ink counter': 94,
           'Maintenance required level of 2nd waste ink counter': 94,
           'Manual cleaning counter': 129,
           'Timer cleaning counter': 4,
           'Total print page counter': 11504,
           'Total print pass counter': 510136,
           'Total scan counter': 4967},
 'waste_ink_levels': {'borderless_waste': 4.63, 'main_waste': 90.45}}
 ```

## Resources

### snmpget

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

### Development resources

epson-printer-snmp: https://github.com/Zedeldi/epson-printer-snmp (and https://github.com/Zedeldi/epson-printer-snmp/issues/1)

ReInkPy: https://codeberg.org/atufi/reinkpy/

ReInk: https://github.com/lion-simba/reink (especially https://github.com/lion-simba/reink/issues/1)

reink-net: https://github.com/gentu/reink-net

epson-l4160-ink-waste-resetter: https://github.com/nicootto/epson-l4160-ink-waste-resetter

epson-l3160-ink-waste-resetter: https://github.com/k3dt/epson-l3160-ink-waste-resetter

emanage x900: https://github.com/abrasive/x900-otsakupuhastajat/

### GUI resources

*epson_print_conf* is a Python command line tool, including API.

The following GUIs are available.

- Epson Adjustment Program (developed by EPSON)
- WIC-Reset: https://wic-reset.com / https://www.2manuals.com / https://resetters.com
- PrintHelp: https://printhelp.info/

Use at your risk.

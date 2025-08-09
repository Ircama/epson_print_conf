# epson_print_conf

Epson Printer Configuration tool via SNMP (TCP/IP)

## Product Overview

The Epson Printer Configuration Tool provides an interface for the configuration and monitoring of Epson printers connected via Wi-Fi using the SNMP protocol. A range of features are offered for both end-users and developers.

The software also includes a configurable printer dictionary, which can be easily extended. In addition, it is possible to import and convert external Epson printer configuration databases.

## Key Features

- __SNMP Interface__: Connect and manage Epson printers using SNMP over TCP/IP, supporting Wi-Fi connections (not USB).

    Printers are queried via Simple Network Management Protocol (SNMP) with a set of Object Identifiers (OIDs) used by Epson printers. Some of them are also valid with other printer brands. SNMP is used to manage the EEPROM and read/set specific Epson configuration.

- __Detailed Status Reporting__: Produce a comprehensive printer status report (with options to focus on specific details).

    Epson printers produce a status response in a proprietary "new binary format" named @BDC ST2, including a data structure which is partially undocumented (such messages
    start with `@BDC [SP] ST2 [CR] [LF]` ...). @BDC ST2 is used to convey various aspects of the status of the printer, such as errors, paper status, ink and more. The element fields of this format may vary depending on the printer model. The *Epson Printer Configuration Tool* can decode all element fields found in publicly available Epson Programming Manuals of various printer models (a relevant subset of fields used by the Epson printers).

- __Advanced Maintenance Functions__:

    - Open the Web interface of the printer (via the default browser).

    - Clean Nozzles.
    
      Standard cleaning cycle on the selected nozzle group, allowing to select black/color nozzles.
      
    - Power Clean of the nozzles.

      Uses a higher quantity of ink to perform a deeper cleaning cycle. Power cleaning also consumes more ink and fills the waste ink tank more quickly. It should only be used when normal cleaning is insufficient.

    - Print Test Patterns.

      Execute a set of test printing functions:

      - Standard Nozzle Test – Ask the printer to print its internal predefined pattern.
      - Alternative Nozzle Test – Use an alternative predefined pattern.
      - Color Test Pattern – Print a b/w and color page, optimized for Epson XP-200 series printers.
      - Advance Paper – Move the loaded sheet forward by a specified number of lines without printing.
      - Feed Multiple Sheets – Pass a specified number of sheets through the printer without printing.

    - Temporary reset of the ink waste counter.

      The ink waste counters track the amount of ink discarded during maintenance tasks to prevent overflow in the waste ink pads. Once the counters indicate that one of the printer pads is full, the printer will stop working to avoid potential damage or ink spills. The "Printer status" button includes information showing the levels of the waste ink tanks; specifically, two sections are relevant: "Maintenance box information" ("maintenance_box_...") and "Waste Ink Levels" ("waste_ink_levels"). The former has a counter associated for each tank, which indicates the number of temporary resets performed by the user to temporarily restore a disabled printer.

      The feature to temporarily reset the ink waste counter is effective if the Maintenance box information reports that the Maintenance Box is full; it temporarily bypasses the ink waste tank full warning, which would otherwise disable printing. It is important to know that this setting is reset upon printer reboot (it does not affect the EEPROM) and can be repeated. Each time the Maintenance box status switches from "full" to "not full", the "ink replacement cleaning counter" is increased. A pad maintenance or tank replacement has to be programmed meanwhile.

    - Reset the ink waste counter.

      This feature permanently resets the ink waste counter.

      Resetting the ink waste counter extends the printer operation while a physical pad maintenance or tank replacement is programmed (operation that shall necessarily be pefromed).

    - Adjust the power-off timer (for energy efficiency).

    - Change the _First TI Received Time_,

      The *First TI Received Time* in Epson printers typically refers to the timestamp of the first transmission instruction to the printer. This feature tracks when the printer first operated.

    - Change the printer WiFi MAC address and the printer serial number (typically used in specialized scenarios where specific device identifiers are required).

    - Read and write to EEPROM addresses.

    - Dump and analyze sets of EEPROM addresses.

    - Detect the access key (*read_key* and *write_key*) and some attributes of the printer configuration.

      The GUI includes some features that attempt to detect the attributes of an Epson printer whose model is not included in the configuration; such features can also be used with known printers, to detect additional parameters.

    - Import and export printer configuration datasets in various formats: epson_print_conf pickle, Reinkpy XML, Reinkpy TOML.

    - Interactive Console (API Playground).
    
      The application includes an integrated Interactive Console. It allows Python developers to interact with the application's runtime environment, evaluate expressions, test APIs, and inspect variables. This console acts as a live API Playground, ideal for debugging, printer configuration testing and rapid prototyping.

    - Access various administrative and debugging options.

- __Available Interfaces__:
    - __Graphical User Interface__: [Tcl/Tk](https://en.wikipedia.org/wiki/Tk_(software)) platform-independent GUI with an autodiscovery function that detects printer IP addresses and model names.
    - __Command Line Tool__: For users who prefer command-line interactions, providing the full set of features.
    - __Python API Interface__: For developers to integrate and automate printer management tasks.

Note on the ink waste counter reset feature: resetting the ink waste counter is just removing a lock; not replacing the tank will reduce the print quality and make the ink spill.

## Installation

Install requirements using *requirements.txt*:

```bash
git clone https://github.com/Ircama/epson_print_conf
cd epson_print_conf
pip install -r requirements.txt
```

On Linux, you might also install the tkinter module: `sudo apt install python3-tk`.

This program exploits [pysnmp v7+](https://github.com/lextudio/pysnmp) and [pysnmp-sync-adapter](https://github.com/Ircama/pysnmp-sync-adapter).

To print data to Epson printers via LPR, it also uses the [epson_escp2](https://github.com/Ircama/epson_escp2) ESC/P2 encoder/decoder and the [PyPrintLpr](https://github.com/Ircama/PyPrintLpr/) LPR (RFC 1179) printer client. You can simulate the LPR interface of an Epson printer via `python3 -m pyprintlpr server -a 192.168.178.29 -e 3289,161 -d -s -l 515,9100 -I`.

It is tested with Ubuntu / Windows Subsystem for Linux, Windows.

## Usage

### Running the pre-built GUI executable code

The *epson_print_conf.zip* archive in the [Releases](https://github.com/Ircama/epson_print_conf/releases/latest) folder incudes the *epson_print_conf.exe* executable asset; the ZIP archive is auto-generated by a [GitHub Action](.github/workflows/build.yml). *epson_print_conf.exe* is a Windows GUI that can be directly executed.

### Running the GUI with Python

Run *ui.py* as in this example:

```
python ui.py
```

This GUI runs on any Operating Systems supported by Python (not just Windows), but needs that [Tkinter](https://docs.python.org/3/library/tkinter.html) is installed. While the *Tkinter* package might be generally available by default with recent Python versions for Windows, [it needs a specific installation on other Operating Systems](https://stackoverflow.com/questions/76105218/why-does-tkinter-or-turtle-seem-to-be-missing-or-broken-shouldnt-it-be-part).

GUI usage:

```
usage: ui.py [-h] [-m MODEL] [-a HOSTNAME] [-P PICKLE_FILE] [-O] [-d]

optional arguments:
  -h, --help            show this help message and exit
  -m MODEL, --model MODEL
                        Printer model. Example: -m XP-205
  -a HOSTNAME, --address HOSTNAME
                        Printer host name or IP address. (Example: -a 192.168.1.87)
  -P PICKLE_FILE, --pickle PICKLE_FILE
                        Load a pickle configuration archive saved by parse_devices.py
  -O, --override        Replace the default configuration with the one in the pickle file instead of merging (default is to merge)
  -d, --debug           Print debug information

epson_print_conf GUI
```

## Quick Start on macOS via Docker

Prerequirements: Docker, a VNC client (e.g. TigerVNC, RealVNC, Remmina)

To install TigerVNC Viewer via Homebrew:

```bash
brew install --cask tigervnc-viewer
```

Build the Docker Image:

```bash
git clone https://github.com/Ircama/epson_print_conf
cd epson_print_conf
sudo docker build -t epson_print_conf .
```

Run the Container:

```bash
sudo docker run -p 5990:5990 epson_print_conf
```

or

```
sudo docker run --publish 5990:5990 ircama/epson_print_conf
```

Open your VNC client and connect:

```bash
vncviewer localhost:90
```

(Password: 1234).

## Usage notes

### How to import an external printer configuration DB

With the GUI, the following operations are possible (from the file menu):

- Load a PICKLE configuration file or web URL.

  This operation allows to open a file saved with the GUI ("Save the selected printer configuration to a PICKLE file") or with the *parse_devices.py* utility. In addition to the printer configuration DB, this file includes the last used IP address and printer model in order to simplify the GUI usage.

- Import an XML configuration file or web URL

  This option allows to import the XML configuration file downloaded from <https://codeberg.org/attachments/147f41a3-a6ea-45f6-8c2a-25bac4495a1d>. Alternatively, this option directly accepts the [source Web URL](https://codeberg.org/attachments/147f41a3-a6ea-45f6-8c2a-25bac4495a1d) of this file, incorporating the download operation into the GUI.

- Import a TOML configuration file or web URL

  Similar to the XML import, this option allows to load the TOML configuration file downloaded from <https://codeberg.org/atufi/reinkpy/raw/branch/main/reinkpy/epson.toml> and also accepts the [source Web URL](https://codeberg.org/atufi/reinkpy/raw/branch/main/reinkpy/epson.toml) of this file, incorporating the download operation into the GUI.

Other menu options allow to filter or clean up the configuration list, as well as select a specific printer model and then save data to a PICKLE file.

### How to detect parameters of an unknown printer

- Detect Printers:

  Start by pressing the *Detect Printers* button. This action generates a tree view, which helps in analyzing the device's parameters. The printer model field should automatically populate if detection is successful.

- Detect Access Keys:

  If the printer is not listed in the configuration or is not manageable, press *Detect Access Keys.* This process may take several minutes to complete.

  - If the message *"Could not detect read_key."* appears at the end, it means the printer cannot be controlled with the current software version (refer to "Known Incompatible Models" below).

  - If no errors are reported in the output, proceed by pressing *Detect Configuration.*

- Analyze Results:

  Each of these operations generates both a tree view and a text view. These outputs help determine if an existing configured model closely matches or is identical to the target printer. Use the right mouse button to switch between the two views for easier analysis.

- Important Notes:

  - These processes can take several minutes to complete. Ensure the printer remains powered on throughout the entire operation.
  - To avoid interruptions, consider temporarily disabling the printer's auto power-off timer.

### How to revert a change performed through the GUI

The GUI displays a `[NOTE]` in the status box before performing any change, specifying the current EEPROM values before the rewrite operation. This line can be copied and pasted as is into the text box that appears when the "Write EEPROM" button is pressed; the execution of the related action reverts the changes to their original values.

It is recommended to copy the status history and keep it in a safe place after making changes, so that a reverse operation can be performed when needed.

### Known incompatible models

Some recent firmwares supported by new printers disabled SNMP EEPROM management or changed the access mode (possibly for security reasons).

For the following models there is no known way to read the EEPROM via SNMP protocol using the adopted read/write key and the related algorithm:

- [XP-7100 with firmware version YL25O7 (25 Jul 2024)](https://github.com/Ircama/epson_print_conf/issues/42) (firmware YL11K6 works)
- Possibly [ET-7700](https://github.com/Ircama/epson_print_conf/issues/46)
- [ET-2800](https://github.com/Ircama/epson_print_conf/issues/27)
- [ET-2814](https://github.com/Ircama/epson_print_conf/issues/42#issuecomment-2571587444)
- [ET-2850, ET-2851, ET-2853, ET-2855, ET-2856](https://github.com/Ircama/epson_print_conf/issues/26)
- [ET-4800](https://github.com/Ircama/epson_print_conf/issues/29) with new firmware (older firmware might work)
- [L3250](https://github.com/Ircama/epson_print_conf/issues/35)
- [L3260](https://github.com/Ircama/epson_print_conf/issues/66) with firmware version 05.23.XE21P2
- [L18050](https://github.com/Ircama/epson_print_conf/issues/47)
- [EcoTank ET-2862 with firmware 05.18.XF12OB dated 12/11/2024](https://github.com/Ircama/epson_print_conf/discussions/58) and possibly ET-2860 / 2861 / 2863 / 2865 series.
- [XP-2200 with firmware 06.58.IU05P2](https://github.com/Ircama/epson_print_conf/issues/51)

The button "Temporary Reset Waste Ink Levels" should still work with these printers.

### Using the command-line tool

```
python epson_print_conf.py [-h] -m MODEL -a HOSTNAME [-p PORT] [-i] [-q QUERY_NAME]
                           [--reset_waste_ink] [--temp_reset_waste_ink] [-d]
                           [--write-first-ti-received-time YEAR MONTH DAY]
                           [--write-poweroff-timer MINUTES] [--dry-run] [-R ADDRESS_SET]
                           [-W ADDRESS_VALUE_SET] [-e FIRST_ADDRESS LAST_ADDRESS]
                           [--detect-key] [-S SEQUENCE_STRING] [-t TIMEOUT] [-r RETRIES]
                           [-c CONFIG_FILE] [--simdata SIMDATA_FILE] [-P PICKLE_FILE] [-O]

Optional arguments:
  -h, --help            show this help message and exit
  -m MODEL, --model MODEL
                        Printer model. Example: -m XP-205 (use ? to print all supported
                        models)
  -a HOSTNAME, --address HOSTNAME
                        Printer host name or IP address. (Example: -a 192.168.1.87)
  -p PORT, --port PORT  Printer port (default is 161)
  -i, --info            Print all available information and statistics (default option)
  -q QUERY_NAME, --query QUERY_NAME
                        Print specific information. (Use ? to list all available queries)
  --reset_waste_ink     Reset all waste ink levels to 0
  --temp_reset_waste_ink
                        Temporary reset waste ink levels
  -d, --debug           Print debug information
  --write-first-ti-received-time YEAR MONTH DAY
                        Change the first TI received time
  --write-poweroff-timer MINUTES
                        Update the poweroff timer. Use 0xffff or 65535 to disable it.
  --dry-run             Dry-run change operations
  -R ADDRESS_SET, --read-eeprom ADDRESS_SET
                        Read the values of a list of printer EEPROM addreses. Format is:
                        address [, ...]
  -W ADDRESS_VALUE_SET, --write-eeprom ADDRESS_VALUE_SET
                        Write related values to a list of printer EEPROM addresses. Format
                        is: address: value [, ...]
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
                        read a configuration file including the full log dump of a previous
                        operation with '-d' flag (instead of accessing the printer via SNMP)
  --simdata SIMDATA_FILE
                        write SNMP dictionary map to simdata file
  -P PICKLE_FILE, --pickle PICKLE_FILE
                        Load a pickle configuration archive saved by parse_devices.py
  -O, --override        Replace the default configuration with the one in the pickle file
                        instead of merging (default is to merge)

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

## Creating an executable asset for the GUI

Alternatively to running the GUI via `python ui.py`, it is possible to build an executable file via *pyinstaller*.

Install *pyinstaller* with `pip install pyinstaller`.

The *epson_print_conf.spec* file helps building the executable program. Run it with the following command.

```bash
pip install pyinstaller  # if not yet installed
pyinstaller epson_print_conf.spec -- --default
```

Then run the executable file created in the *dist/* folder, which has the same options of `ui.py`.

It is also possible to automatically load a previously created configuration file that has to be named *epson_print_conf.pickle*, merging it with the program configuration. (See below the *parse_devices.py* utility.) To build the executable program with this file, run the following command:

```bash
pip install pyinstaller  # if not yet installed
curl -o devices.xml https://codeberg.org/attachments/147f41a3-a6ea-45f6-8c2a-25bac4495a1d
python3 parse_devices.py -a 192.168.178.29 -s XP-205 -p epson_print_conf.pickle  # use your default IP address and printer model as default settings for the GUI
pyinstaller epson_print_conf.spec
```

Same procedure using the Reinkpy's *epson.toml* file (in place of *devices.xml*):

```bash
pip install pyinstaller  # if not yet installed
curl -o epson.toml https://codeberg.org/atufi/reinkpy/raw/branch/main/reinkpy/epson.toml
python3 parse_devices.py -Ta 192.168.178.29 -s XP-205 -p epson_print_conf.pickle  # use your default IP address and printer model as default settings for the GUI
pyinstaller epson_print_conf.spec
```

When embedding *epson_print_conf.pickle*, the created program does not have options and starts with the default IP address and printer model defined in the build phase.

As mentioned in the [documentation](https://pyinstaller.org/en/stable/), PyInstaller supports Windows, MacOS X, Linux and other UNIX Operating Systems. It creates an executable file which is only compatible with the operating system that is used to build the asset.

This repository includes a Windows *epson_print_conf.exe* executable file which is automatically generated by a [GitHub Action](.github/workflows/build.yml). It is packaged in a ZIP file named *epson_print_conf.zip* and uploaded into the [Releases](https://github.com/Ircama/epson_print_conf/releases/latest) folder.

## Utilities and notes

### parse_devices.py

Within a [report](https://codeberg.org/atufi/reinkpy/issues/12#issue-716809) in repo <https://codeberg.org/atufi/reinkpy> there is an interesting [attachment](https://codeberg.org/attachments/147f41a3-a6ea-45f6-8c2a-25bac4495a1d) which includes an extensive XML database of Epson model features.

The program *parse_devices.py* transforms this XML DB into the dictionary that *epson_print_conf.py* can use. It is also able to accept the [TOML](https://toml.io/) input format used by [reinkpy](https://codeberg.org/atufi/reinkpy) in [epson.toml](https://codeberg.org/atufi/reinkpy/src/branch/main/reinkpy/epson.toml), if the `-T` option is used.

Here is a simple procedure to download the *devices.xml* DB and run *parse_devices.py* to search for the XP-205 model and produce the related PRINTER_CONFIG dictionary to the standard output:

```bash
curl -o devices.xml https://codeberg.org/attachments/147f41a3-a6ea-45f6-8c2a-25bac4495a1d
python3 parse_devices.py -i -m XP-205
```

Same procedure, processing the *epson.toml* file:

```bash
curl -o epson.toml https://codeberg.org/atufi/reinkpy/raw/branch/main/reinkpy/epson.toml
python3 parse_devices.py -T -i -m XP-205
```

After generating the related printer configuration, *epson_print_conf.py* shall be manually edited to copy/paste the output of *parse_devices.py* within its PRINTER_CONFIG dictionary. Alternatively, the program is able to create a *pickle* configuration file (check the `-p` lowercase option), which the other programs can load (with the `-P` uppercase option and in addition with the optional `-O` flag).

The `-m` option is optional and is used to filter the printer model in scope. If the produced output is not referred to the target model, use part of the model name as a filter (e.g., only the digits, like `parse_devices.py -i -m 315`) and select the appropriate model from the output.

Program usage:

```
usage: parse_devices.py [-h] [-m PRINTER_MODEL] [-T] [-l LINE_LENGTH] [-i] [-d] [-t] [-v] [-f] [-e]
                        [-c CONFIG_FILE] [-s DEFAULT_MODEL] [-a HOSTNAME] [-p PICKLE_FILE] [-I] [-N]
                        [-A] [-G] [-S] [-M]

optional arguments:
  -h, --help            show this help message and exit
  -m PRINTER_MODEL, --model PRINTER_MODEL
                        Filter printer model. Example: -m XP-205
  -T, --toml            Use the Reinkpy TOML input format instead of XML
  -l LINE_LENGTH, --line LINE_LENGTH
                        Set line length of the output (default: 120)
  -i, --indent          Indent output of 4 spaces
  -d, --debug           Print debug information
  -t, --traverse        Traverse the XML, dumping content related to the printer model
  -v, --verbose         Print verbose information
  -f, --full            Generate additional tags
  -e, --errors          Add last_printer_fatal_errors
  -c CONFIG_FILE, --config CONFIG_FILE
                        use the XML or the Reinkpy TOML configuration file to generate the configuration;
                        default is 'devices.xml', or 'epson.toml' if -T is used
  -s DEFAULT_MODEL, --default_model DEFAULT_MODEL
                        Default printer model. Example: -s XP-205
  -a HOSTNAME, --address HOSTNAME
                        Default printer host name or IP address. (Example: -a 192.168.1.87)
  -p PICKLE_FILE, --pickle PICKLE_FILE
                        Save a pickle archive for subsequent load by ui.py and epson_print_conf.py
  -I, --keep_invalid    Do not remove printers without write_key or without read_key
  -N, --keep_names      Do not replace original names with converted names and add printers for all
                        optional names
  -A, --no_alias        Do not add aliases for same printer with different names and remove aliased
                        printers
  -G, --no_aggregate_alias
                        Do not aggregate aliases of printers with same configuration
  -S, --no_same_as      Do not add "same-as" for similar printers with different names
  -M, --no_maint_level  Do not add "Maintenance required levelas" in "stats"

Generate printer configuration from devices.xml or from Reinkpy TOML
```

The program does not provide *printer_head_id* and *Power off timer*.

#### Example to integrate new printers

Suppose ET-4800 ia a printer already defined in the mentioned [attachment](https://codeberg.org/attachments/147f41a3-a6ea-45f6-8c2a-25bac4495a1d) with valid data, that you want to integrate.

```bash
curl -o devices.xml https://codeberg.org/attachments/147f41a3-a6ea-45f6-8c2a-25bac4495a1d
python3 parse_devices.py -m ET-4800 -p epson_print_conf.pickle
python3 ui.py -P epson_print_conf.pickle
```

or (operating *epson.toml*):

```bash
curl -o epson.toml https://codeberg.org/atufi/reinkpy/raw/branch/main/reinkpy/epson.toml
python3 parse_devices.py -T -m ET-4800 -p epson_print_conf.pickle
python3 ui.py -P epson_print_conf.pickle
```

If you also want to create an executable program:

```bash
pyinstaller epson_print_conf.spec
```

### find_printers.py

*find_printers.py* can be executed via `python find_printers.py` and prints the list of the discovered printers to the standard output. It is internally used as a library by *ui.py*.

Output example:

```
[{'ip': '192.168.178.29', 'hostname': 'EPSONDEFD03.fritz.box', 'name': 'EPSON XP-205 207 Series'}]
```

### Other utilities

```python
from epson_print_conf import EpsonPrinter
import pprint
printer = EpsonPrinter()

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
printer = EpsonPrinter(model="ET-2700")
'.'.join(str(x) for x in printer.parm['read_key'])
" ".join('{0:02x}'.format(x) for x in printer.parm['read_key'])

# Print the write key sequence in byte and hex formats:
printer = EpsonPrinter(model="ET-2700")
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

```python
from epson_print_conf import EpsonPrinter
import pprint
printer = EpsonPrinter(hostname="192.168.1.87")
pprint.pprint(printer.status_parser(printer.fetch_snmp_values("1.3.6.1.4.1.1248.1.2.2.1.1.1.4.1")[1]))
```

## EPSON-CTRL commands over SNMP

[Communication between PC and Printer can be done by several transport protocols](https://github.com/lion-simba/reink/blob/master/reink.c#L79C5-L85): ESCP/2, EJL, D4. And in addition SNMP, END4. “D4” (or “Dot 4”) is an abbreviated form of the IEEE-1284.4 specification: it provides a bi-directional, packetized link with multiple logical “sockets”. The two primary Epson-defined channels are:

- EPSON-CTRL
  – Carries printer-control commands, status queries, configuration
  - Structure: 2 lowercase letters + length + payload
  – Also tunneled via END4
  - undocumented commands.

- EPSON-DATA
  – Carries the actual print-job content: raster image streams, font/download data, macros, etc.
  - Allow "Remote Mode" commands, entered and terminated via a special sequence (`ESC (R BC=8 00 R E M O T E 1`, `ESC 00 00 00`); [remote mode commands](https://gimp-print.sourceforge.io/reference-html/x952.html) are partially documented and have a similar structure as EPSON-CTRL (2 letters + length + payload), but the letters are uppercase and cannot be mapped to SNMP.

EPSON-CTRL can be transported over D4, or encapsulated in SNMP OIDs. Some EPSON-CTRL instructions implement a subset of Epson’s Remote Mode protocol, while others are proprietary. Such commands are named "Packet Commands" in the Epson printer Service Manuals and specifically the "EPSON LX-300+II and LX-1170II Service manuals" (old impact dot matrix printers) document "di", "st" and also "||" in the "Packet commands" table.

END4 is a proprietary protocol to transport EPSON-CTRL commands [over the standard print channel](https://codeberg.org/atufi/reinkpy/issues/12#issuecomment-1660026), without using the EPSON-CTRL channel.

OID Header:

```
1.3.6.1.4.1. [SNMP_OID_ENTERPRISE]
1248. [SNMP_EPSON]

1.2.2.44.1.1.2. [OID_PRV_CTRL]
1.
```

Full OID header sequence: `1.3.6.1.4.1.1248.1.2.2.44.1.1.2.1.`

Subsequent digits:

- Two ASCII characters that identify the command (e.g., "st", "ex"). These are command identifiers of the EPSON-CTRL messages (Remote Mode)
- 2-byte little-endian length field (gives the number of bytes in the parameter section that follows)
- payload (a block of bytes that are specific to the command).

The following is the list of EPSON-CTRL commands supported by the XP-205.

Two-bytes|Description | Notes | Parameters
:--:| ---------------------------------------------- | ----------------| -------------
\|\| | EEPROM access | Implemented in this program, the SNMP OID version is not supported by new printer firmwares | (A, B); see examples below
cd | | | (0)
cs |  | | (0 or 1)
cx | | |
di | Get Device ID (identification) ("di" 01H 00H 01H), same as @EJL[SP]ID[CR][LF] | Implemented in this program | (1)
ei | | | (0)
ex | Set Vertical Print Page Line Mode, Roll Paper Mode | - ex BC=6 00 00 00 00 0x14 xx (Set Vertical Print Page Line Mode. xx=00 is off, xx=01 is on. If turned on, this prints vertical trim lines at the left and right margins).<br> - ex BC=6 00 00 00 00 0x05 xx (Set Roll Paper Mode. If xx is 0, roll paper mode is off; if xx is 1, roll paper mode is on).<br> - ex BC=3 00 xx yy (Appears to be a synonym for the SN command described above.) |
fl | Firmware load. Enter recovery mode | |
ht | Horizontal tab | |
ia | List of cartridge types | Implemented in this program | (0)
ii | List cartridge properties | Implemented in this program ("ii\2\0\1\1") | (1 + cartridge number)
ot | Power Off Timer | Implemented in this program | (1, 1)
pe | (paper ?) | | (1)
pj | Pause jobs (?) | |
pm | Select control language ("pm" 02H 00H 00H m1m1=0(ESC/P), 2(IBM 238x Plus emulation) | | (1)
rj | Resume jobs (?)  | |
rp | (serial number ? ) | | (0)
rs | Initialize | | (1)
rw | Reset Waste | Implemented in this program | (1, 0) + [Serial SHA1 hash](https://codeberg.org/atufi/reinkpy/issues/12#issuecomment-1661250) (20 bytes)
st | Get printer status ("st" 01H 00H 01H) | Implemented in this program; se below "ST2 Status Reply Codes" | (1)
ti | Set printer time | ("ti" 08H 00H 00H YYYY MM DD hh mm ss) |
vi | Version Information | Implemented in this program | (0)
xi | | | (1)

escutil.c also mentions [`ri\2\0\0\0`](https://github.com/echiu64/gutenprint/blob/master/src/escputil/escputil.c#L1944) (Attempt to reset ink) in some printer firmwares.

[Other font](https://codeberg.org/KalleMP/reinkpy/src/branch/main/reinkpy/epson/core.py#L22) also mentions `pc:\x01:NA` in some printer firmwares.

Reply of any non supported commands: “XX:;” FF. (XX is the command string being invalid.)

### Examples for EEPROM access

#### Read EEPROM

```
124.124.7.0. [7C 7C 07 00]
<READ KEY (two bytes)>
65.190.160. [41 BE A0]
<LSB EEPROM ADDRESS (one byte)>.<MSB EEPROM ADDRESS (one byte)>
```

- 124.124: "||" = Read EEPROM (EPSON-CTRL)
- 7.0: Two-byte payload length = 7 bytes (7 bytes payload length means two-byte EEPROM address, used in recent printers; old printers supported 6 bytes payload length for a single byte EEPROM address).
- two bytes for the read key (named "R code" in the "EPSON LX-300+II and LX-1170II Service manuals")
- 65: 'A' = read (41H)
- 190: [Take the bitwise NOT of the ASCII value of 'A' = read, then mask to the lowest 8 bits](https://github.com/lion-simba/reink/blob/master/reink.c#L1414). The result is 190 (BEH).
- 160: [Shift the ASCII value of 'A' (read) right by 1 and mask to 7 bits, then OR it with the highest bit of the value shifted left by 7](https://github.com/lion-simba/reink/blob/master/reink.c#L1415). The result is 160 (A0H).
- two bytes for the EEPROM address (one byte if the payload length is 6 bytes)

From the Epson Service manual of LX-300+II and LX-1170II (single byte form):

```
“||” 06H 00H r1 r2 41H BEH A0H d1
r1, r2 means R code. (e.g. r1=A8, r2=5Ah)
d1 : EEPROM address (00h - FFh)
```

SNMP OID example: `1.3.6.1.4.1.1248.1.2.2.44.1.1.2.1.124.124.7.0.73.8.65.190.160.48.0`

EEPROM data reply: “@BDC” SP “PS” CR LF “EE:” <addr> <data> “;” FF.

#### Write EEPROM

- 124.124: "||" = Read EEPROM (EPSON-CTRL)
- 16.0: Two-byte payload length = 16 bytes
- two bytes for the read key
- 66: 'B' = write
- 189: Take the bitwise NOT of the ASCII value of 'B' = write, then mask to the lowest 8 bits. The result is 189.
- 33: Shift the ASCII value of 'B' (write) right by 1 and mask to 7 bits, then OR it with the highest bit of the value shifted left by 7. The result is 33.
- two bytes for the EEPROM address
- one byte for the value
- 8 bytes for the write key

```
7C 7C 10 00 [124.124.16.0.]
<READ KEY (two bytes)>
42 BD 21 [66.189.33.]
<LSB EEPROM ADDRESS (one byte)>.<MSB EEPROM ADDRESS (one byte)>
<VALUE (one byte)>
<WRITE KEY (eight bytes)>
```

SNMP OID example: `7C 7C 10 00 49 08 42 BD 21 30 00 1A 42 73 62 6F 75 6A 67 70`

#### Returned data

Example of Read EEPROM (@BDC PS):

```
<01> @BDC PS <0d0a> EE:0032AC;
EE: = EEPROM Read
0032 = Memory address
AC = Value
```

### Related API

#### epctrl_snmp_oid()

`self.epctrl_snmp_oid(two-char-command, payload)` converts an EPSON-CTRL Remote command into a SNMP OID format suitable for use in SNMP operations.

**Parameters**

* `command` (`str`):
  A two-character string representing the EPSON Remote Mode command.

* `payload` (`int | list[int] | bytes`):
  The payload to send with the command. It can be:

  * An integer, representing a single byte-argument.
  * A list of integers (converted to bytes)
  * A `bytes` object (used as-is)

It returns a SNMP OID string to be used by `self.printer.fetch_oid_values()`.

`self.epctrl_snmp_oid("ei", 0)` is equivalent to `self.epctrl_snmp_oid("ei", [0])` or `self.epctrl_snmp_oid("ei", b'\x00')`.

`self.epctrl_snmp_oid("st", [1, 0, 1])` is equivalent to `self.epctrl_snmp_oid("ei", b'\x01\x00\x01')`.

#### fetch_oid_values()

`self.fetch_oid_values(oid)` fetches the oid value. When oid is a string, it returns a list of a single element consisting of a tuple: data type (generally 'OctetString') and data value in bytes.

To return the value of the OID query: `self.fetch_oid_values(oid)[0][1]`.

### Testing EPSON-CTRL commands

Open the *epson_print_conf* application, set printer model and IP address, test printer connection. Then: Settings > Debug Shell.

The following are examples of instructions to test the EPSON-CTRL commands:

```python
# cs
self.printer.fetch_oid_values(self.printer.epctrl_snmp_oid("cs", 0))[0][1]
self.printer.fetch_oid_values(self.printer.epctrl_snmp_oid("cs", 1))[0][1]

# cd
self.printer.fetch_oid_values(self.printer.epctrl_snmp_oid("cd", 0))[0][1]

# ex
self.printer.fetch_oid_values(self.printer.epctrl_snmp_oid("ex", [0, 0, 0, 0, 25, 0]))[0][1]

from datetime import datetime
now = datetime.now()
data = bytearray()
data = b'\x00'
data += now.year.to_bytes(2, 'big')  # Year
data += bytes([now.month, now.day, now.hour, now.minute, now.second])
self.printer.fetch_oid_values(self.printer.epctrl_snmp_oid("ti", data))[0][1]

# Firmware load. Enter recovery mode
self.printer.fetch_oid_values(self.printer.epctrl_snmp_oid("fl", 1))[0][1]

# ei
self.printer.fetch_oid_values(self.printer.epctrl_snmp_oid("ei", 0))[0][1]

# pe
self.printer.fetch_oid_values(self.printer.epctrl_snmp_oid("pe", 1))[0][1]

# rp (serial number ? )
self.printer.fetch_oid_values(self.printer.epctrl_snmp_oid("rp", 0))[0][1]

# xi (?)
self.printer.fetch_oid_values(self.printer.epctrl_snmp_oid("xi", 1))[0][1]

# Print Meter
self.printer.fetch_oid_values(self.printer.epctrl_snmp_oid("pm", 1))[0][1]

# rs
self.printer.fetch_oid_values(self.printer.epctrl_snmp_oid("rs", 1))[0][1]

# Detect all commands:
ec_sequences = [
    decoded
    for i in range(0x10000)
    if (b := i.to_bytes(2, 'big'))[0] and b[1]
    and (decoded := b.decode('utf-8', errors='ignore')).encode('utf-8') == b
]
for i in ec_sequences:
    if len(i) != 2:
        continue
    r = self.printer.fetch_oid_values(self.printer.epctrl_snmp_oid(i, 0))
    if r[0][1] != b'\x00' + i.encode() + b':;\x0c':
        print(r)
```

## Remote Mode commands

The [PyPrintLpr](https://github.com/Ircama/PyPrintLpr) module is used for sending Epson LPR commands over a LPR connection. This channel does not support receiving payload responses from the printer.

Refer to [Epson Remote Mode commands](https://github.com/Ircama/PyPrintLpr?tab=readme-ov-file#epson-remote-mode-commands) and to https://gimp-print.sourceforge.io/reference-html/x952.html for a description of the known Remote Mode commands.

Check `self.printer.check_nozzles()` and `self.printer.clean_nozzles(0)` for examples of usage.

The following code prints the nozzle-check print pattern (copy and paste the code to the Interactive Console after selecting a printer and related host address):

```python
from pyprintlpr import LprClient
from hexdump2 import hexdump

with LprClient('192.168.1.100', port="LPR", queue='PASSTHRU') as lpr:
    data = (
        lpr.EXIT_PACKET_MODE +    # Exit packet mode
        lpr.ENTER_REMOTE_MODE +   # Engage remote mode commands
        lpr.PRINT_NOZZLE_CHECK +  # Issue nozzle-check print pattern
        lpr.EXIT_REMOTE_MODE +    # Disengage remote control
        lpr.JOB_END               # Mark maintenance job complete
    )
    print("\nDump of data:\n")
    hexdump(data)
    lpr.send(data)
```

## ST2 Status Reply Codes

ST2 Status Reply Codes that are decoded by *epson_print_conf*; they are mentioned in various Epson programming guides:

Staus code | Description
:---------:|-------------
01 | Status code
02 | Error code
03 | Self print code
04 | Warning code
06 | Paper path
07 | Paper mismatch error
0c | Cleaning time information
0d | Maintenance tanks
0e | Replace cartridge information
0f | Ink information
10 | Loading path information
13 | Cancel code
14 | Cutter information
18 | Stacker(tray) open status
19 | Current job name information
1c | Temperature information
1f | Serial
35 | Paper jam error information
36 | Paper count information
37 | Maintenance box information
3d | Printer I/F status
40 | Serial No. information
45 | Ink replacement counter (TBV)
46 | Maintenance_box_replacement_counter (TBV)

Many printers return additional codes whose meanings are unknown and not documented.

## API Interface

### Specification

```python
EpsonPrinter(conf_dict, replace_conf, model, hostname, port, timeout, retries, dry_run)
```

- `conf_dict`: optional configuration file in place of the default PRINTER_CONFIG (optional, default to `{}`)
- `replace_conf`: (optional, default to False) set to True to replace PRINTER_CONFIG with `conf_dict` instead of merging it
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
from epson_print_conf import EpsonPrinter
import logging

logging.basicConfig(level=logging.DEBUG, format="%(message)s")  # if logging is needed

printer = EpsonPrinter(model="XP-205", hostname="192.168.178.29")

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

# Dump all printer configuration parameters
from pprint import pprint
pprint(printer.parm)
```

[black](https://pypi.org/project/black/) way to dump all printer parameters:

```python
import textwrap, black
from epson_print_conf import EpsonPrinter
printer = EpsonPrinter(model="TX730WD", hostname="192.168.178.29")
mode = black.Mode(line_length=200, magic_trailing_comma=False)
print(textwrap.indent(black.format_str(f'"{printer.model}": ' + repr(printer.parm), mode=mode), 8*' '))

# Print status:
print(black.format_str(f'"{printer.model}": ' + repr(printer.stats()), mode=mode))
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

### snmpget

Installation with Linux:

```
sudo apt-get install snmp
```

There are also [binaries for Windows](https://netcologne.dl.sourceforge.net/project/net-snmp/net-snmp%20binaries/5.7-binaries/net-snmp-5.7.0-1.x86.exe?viasf=1) which include snmpget.exe, running with the same arguments.

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

ReInk: <https://github.com/lion-simba/reink> (especially <https://github.com/lion-simba/reink/issues/1>)

epson-printer-snmp: <https://github.com/Zedeldi/epson-printer-snmp> (and <https://github.com/Zedeldi/epson-printer-snmp/issues/1>)

ReInkPy: <https://codeberg.org/atufi/reinkpy/>

reink-net: <https://github.com/gentu/reink-net>

epson-l4160-ink-waste-resetter: <https://github.com/nicootto/epson-l4160-ink-waste-resetter>

epson-l3160-ink-waste-resetter: <https://github.com/k3dt/epson-l3160-ink-waste-resetter>

emanage x900: <https://github.com/abrasive/x900-otsakupuhastajat/>

Reversing Epson printers: <https://github.com/abrasive/epson-reversing/>

escputil.c: https://github.com/echiu64/gutenprint/blob/master/src/escputil/escputil.c#

### Other programs

- Epson One-Time Maintenance Ink Pad Reset Utility: <https://epson.com/Support/wa00369>
  - Epson Maintenance Reset Utility: <https://epson.com/epsonstorefront/orbeon/fr/us_regular_s03/us_ServiceInk_Pad_Reset/new>
  - Epson Ink Pads Reset Utility Terms and Conditions: <https://epson.com/Support/wa00370>
- Epson Adjustment Program (developed by EPSON)
- WIC-Reset: <https://www.wic.support/download/> / <https://www.2manuals.com/> (Use at your risk)
- PrintHelp: <https://printhelp.info/> (Use at your risk)

### Other resources
- <https://github.com/lion-simba/reink/files/14553492/devices.zip>
- <https://codeberg.org/attachments/147f41a3-a6ea-45f6-8c2a-25bac4495a1d>
- <https://codeberg.org/atufi/reinkpy/src/branch/main/reinkpy/epson.toml>

## License

EUPL-1.2 License - See [LICENSE](LICENSE) for details.

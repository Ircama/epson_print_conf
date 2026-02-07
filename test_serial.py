from epson_print_conf import EpsonPrinter
import logging

# Configure logging to see debug output
logging.basicConfig(level=logging.DEBUG)

print("Attempting to get serial number...")
printer = EpsonPrinter(model="ET-2820", hostname="192.168.1.105")

# Try 1: Standard EEPROM read (Likely fails)
try:
    sn = printer.get_serial_number()
    print(f"Method 1 (EEPROM): {sn}")
except Exception as e:
    print(f"Method 1 Failed: {e}")

# Try 2: Device ID (Public)
try:
    di = printer.get_device_identification()
    print(f"Method 2 (Device ID): {di}")
    # Check raw SNMP response for SN if 'di' parsing misses it
    oid = printer.epctrl_snmp_oid("di", 1)
    tag, val = printer.fetch_oid_values(oid)[0]
    print(f"Raw DI: {val}")
except Exception as e:
    print(f"Method 2 Failed: {e}")

from epson_print_conf import EpsonPrinter
import logging
import sys

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Configuration
PRINTER_IP = "192.168.1.105"
PRINTER_MODEL = "ET-2820"
SERIAL_NUMBER = "XAJG087265" # Hardcoded correct serial for this printer

def main():
    print(f"--- Epson ET-2820 Permanent Reset Tool ---")
    print(f"Target: {PRINTER_IP}")
    print(f"Serial: {SERIAL_NUMBER}")
    
    try:
        printer = EpsonPrinter(model=PRINTER_MODEL, hostname=PRINTER_IP)
        
        # Mode 0 = Initialization/Permanent Reset
        # Mode 1 = Temporary Reset
        print(f"\nSending LPR Reset Command (Mode 0)...")
        success = printer.temporary_reset_waste(mode=0, serial=SERIAL_NUMBER)
        
        if success:
            print("\n✅ SUCCESS: Reset command sent to printer.")
            print("Please restart the printer if the error persists.")
        else:
            print("\n❌ FAILURE: Command could not be sent.")
            
    except Exception as e:
        print(f"\n❌ ERROR: {e}")

if __name__ == "__main__":
    main()

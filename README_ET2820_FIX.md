# Epson ET-2820 Waste Ink Reset Fix

## Problem
The Epson ET-2820 (and similar models with newer firmware, e.g., XE19P5) blocks standard SNMP-based waste ink resets.
- **Symptom:** `epson_print_conf.py` fails to read the Serial Number (Auth Error) or fails to write to EEPROM (`NA` response).
- **Result:** Error E11 (Maintenance Box Full) persists.

## Solution
This patched solution uses a "Backdoor" approach:
1.  **Manual Serial Number:** Since the printer hides its serial number from the tool, we hardcode it (`XAJG087265`).
2.  **LPR Transport:** Since SNMP WRITE is blocked, we use the LPR printing protocol to send the "Remote Mode" reset command (`rw`).
3.  **Mode 0:** We use Mode 0 (Initialization) instead of Mode 1 (Temporary) to attempt a permanent fix.

## How to use
Run the dedicated script created for this printer:

```powershell
python reset_ET2820_permanent.py
```

## Files
- `epson_print_conf.py`: Patched library with `ET-2820` support and LPR fallback logic.
- `reset_ET2820_permanent.py`: The script configured with your specific IP and Serial Number.

## Notes
- If you change the printer (new unit), you MUST update the `SERIAL_NUMBER` variable in `reset_ET2820_permanent.py`.
- If the error returns after a firmware update, re-run this script.

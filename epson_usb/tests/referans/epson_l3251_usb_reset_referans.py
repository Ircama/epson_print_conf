#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FROZEN REFERENCE COPY - DO NOT EDIT - see testler/referans/README.md.
# This is epson_l3251_usb_reset.py as it was at revision 6afeb45 (v0.3.0),
# before the protocol core moved into the epson_usb package. It is used only by
# testler/test_eski_yeni_esdeger.py, to prove that the library produces the
# same bytes on the wire as the implementation verified on hardware.
r"""
epson_l3251_usb_reset.py  --  Epson L3251 Waste Ink Pad counter reset (USB)
================================================================================
Reaches the EEPROM over USB with the IEEE 1284.4 (D4) protocol, because the
Wi-Fi/SNMP path is closed in this printer's firmware. Talks to the Windows
printer channel (USBPRINT) directly: NO DRIVER REPLACEMENT (no Zadig) and NO
EXTERNAL DEPENDENCIES (Python's built-in ctypes only).

SAFETY
  * The default mode READS ONLY and takes a full backup. It writes nothing.
  * Resetting requires an explicit  --reset  ; a bank-0 backup is taken first.
  * --restore <file> writes every waste-related cell back from a backup; a bank-0
    safety backup is taken first too, unless  --no-backup  is given.

USAGE
  Read state + take a backup (no writes):  py epson_l3251_usb_reset.py
  RESET the 6 known cells (writes!):       py epson_l3251_usb_reset.py --reset
  RESET the full spec cell set (writes!):  py epson_l3251_usb_reset.py --reset-full
  Firmware "rw" service reset (writes!):   py epson_l3251_usb_reset.py --service-reset
  Restore from a backup:                   py epson_l3251_usb_reset.py --restore <file.json>
  With an explicit device id:               py epson_l3251_usb_reset.py --instance-id "USB\\VID_04B8&..."
  Show the full serial number:              py epson_l3251_usb_reset.py --show-serial
  Print the version:                        py epson_l3251_usb_reset.py --version
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import os
import re
import struct
import sys
import time

__version__ = "0.3.0"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------- #
#  L3250-series EEPROM command parameters                                      #
# --------------------------------------------------------------------------- #
RKEY = [0x4A, 0x36]                                   # read/write model code (74,54)
WKEY = bytes([78, 98, 115, 106, 99, 98, 122, 98])    # "Nbsjcbzb"

# Waste ink counter groups: (addresses, divisor, divisor_verified, label)
#
# BYTE ORDER: each pair is LITTLE-ENDIAN - the first address holds the LOW byte.
# Reading it big-endian (as this tool did until v0.2.0) inflates the value by up
# to 256x and makes every counter look permanently full. Ground truth from this
# printer, decisive because the error state is observable:
#     0x30=0xCC 0x31=0x18 -> LE 6348 = 100.0%  -> printer DID show the error
#     0x30=0x3B 0x31=0x18 -> LE 6203 =  97.7%  -> printer did NOT show it
# Big-endian gives 52248 and 15128 for the same two readings - both "full",
# which cannot explain the error clearing. Little-endian explains it exactly.
#
# The main divisor is corroborated independently: a reporter on
# Ircama/epson_print_conf issue #35 measured 0x18CA = 6346 as exactly 100.00%
# ("the divider for this family is 63.46"). The other two divisors are only
# plausible - they have no such anchor and are printed with a leading "~".
WASTE_COUNTERS = [
    ([0x30, 0x31], 6346, True,  'Main waste pad'),
    ([0x32, 0x33], 3416, False, 'Secondary pad'),
    ([0xFC, 0xFD], 1300, False, 'Borderless/platen pad'),
]
WASTE_ADDRS = [0x30, 0x31, 0x32, 0x33, 0xFC, 0xFD]

# Full reset set for this model group, taken verbatim from the reinkpy spec
# (reinkpy/epson.toml, the rkey=0x364A / wkey="Nbsjcbzb" group, whose model list
# contains L3251). Note that three cells reset to 0x5E, NOT to zero:
#   { addr = [0x1C,0x34,0x35,0x36,0x37,0xFF], reset = [0,0,0,0x5E,0x5E,0x5E] }
#   { addr = [0x2F] }  { addr = [0x30,0x31] }  { addr = [0x32,0x33] }
#   { addr = [0xFC,0xFD] }  { addr = [0xFE] }          (no reset= -> zeros)
FULL_RESET_CELLS = [
    (0x1C, 0x00), (0x34, 0x00), (0x35, 0x00),
    (0x36, 0x5E), (0x37, 0x5E), (0xFF, 0x5E),
    (0x2F, 0x00),
    (0x30, 0x00), (0x31, 0x00),
    (0x32, 0x00), (0x33, 0x00),
    (0xFC, 0x00), (0xFD, 0x00),
    (0xFE, 0x00),
]

# Single cells the same spec calls waste-related but that --reset never touched.
# (address, value the spec resets it to) - shown for context on every read.
EXTRA_WATCH = [
    (0x1C, 0x00), (0x2F, 0x00), (0x34, 0x00), (0x35, 0x00),
    (0x36, 0x5E), (0x37, 0x5E), (0xFE, 0x00), (0xFF, 0x5E),
]

# The main waste counter is MIRRORED. Measured 2026-09-04: ten bordered photo
# pages moved all three of these pairs by exactly +17, in lockstep. This is why
# zeroing 0x30/0x31 alone never survived a power cycle - the firmware restored
# the value from a mirror that was still holding it. 0xC0/0xC1 is NOT in the
# reinkpy spec and is NOT written by any reset path here; it was observed to be
# synced DOWN to zero by the firmware at the first power-on after --reset-full,
# so it is derived rather than authoritative. Shown, never written.
MIRROR_CELLS = [
    ([0x30, 0x31], 'main counter'),
    ([0x34, 0x35], 'mirror A (in the spec reset set)'),
    ([0xC0, 0xC1], 'mirror B (OUTSIDE the spec set, never written here)'),
]

# Every cell any write path can touch. --restore must cover all of them,
# otherwise --reset-full would not be fully undoable from a backup.
RESTORE_ADDRS = sorted(set(WASTE_ADDRS) | set(a for a, _ in FULL_RESET_CELLS))


def build_read_cmd(addr):
    lo, hi = addr & 0xFF, (addr >> 8) & 0xFF
    payload = bytes([RKEY[0], RKEY[1], 0x41, 0xBE, 0xA0, lo, hi])
    return b"\x7c\x7c" + struct.pack("<H", len(payload)) + payload


def build_write_cmd(addr, val):
    lo, hi = addr & 0xFF, (addr >> 8) & 0xFF
    payload = bytes([RKEY[0], RKEY[1], 0x42, 0xBD, 0x21, lo, hi, val & 0xFF]) + WKEY
    return b"\x7c\x7c" + struct.pack("<H", len(payload)) + payload


def build_service_rw_cmd(serial):
    r"""Epson "rw" (reset waste) SERVICE command.

    Frame taken from reinkpy (reinkpy/epson.py, Device.do_rw + Device.encode):
        ctrl(('rw', b'\x00' + hashlib.sha1(serial.encode('ascii')).digest()))
    'rw' is a plain two-letter command, NOT a factory ('|','A'/'B') command, so
    it carries no rkey/opcode prefix - just the name, a little-endian uint16
    length and the payload. Payload is 1 + 20 = 21 bytes.

    reinkpy hashes info['serial_number'], i.e. the USB iSerialNumber STRING
    DESCRIPTOR. A reporter on Ircama/epson_print_conf issue #35 got a ":OK;"
    out of this command using the PLAIN-TEXT serial instead, which is what the
    EEPROM holds here, so the plain serial is tried first. Both are offered.

    Note what this command is: a TEMPORARY reset. The same report states it does
    not survive a power cycle. --reset-full writes EEPROM and does survive, so
    this is a fallback, not the main path.
    """
    payload = b"\x00" + hashlib.sha1(serial.encode("ascii")).digest()
    return b"rw" + struct.pack("<H", len(payload)) + payload


# --------------------------------------------------------------------------- #
#  Win32                                                                       #
# --------------------------------------------------------------------------- #
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
ERROR_IO_PENDING = 997
WAIT_TIMEOUT = 0x102
DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


USBPRINT_GUID = GUID(0x28d78fad, 0x5a12, 0x11d1,
                     (ctypes.c_ubyte * 8)(0xae, 0x5b, 0x00, 0x00, 0xf8, 0x03, 0xa8, 0xc2))


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("InterfaceClassGuid", GUID),
                ("Flags", wt.DWORD), ("Reserved", ctypes.POINTER(ctypes.c_ulong))]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p),
                ("Offset", wt.DWORD), ("OffsetHigh", wt.DWORD), ("hEvent", wt.HANDLE)]


# EF-0: this whole block is Win32-only (ctypes.WinDLL does not exist on other
# platforms - the attribute itself is absent, so even referencing it raises
# AttributeError at import time). Guarded so the pure-byte helpers above
# (build_read_cmd, build_write_cmd, build_service_rw_cmd, the constant
# tables) and the functions below that don't touch these globals until
# called (read_waste, read_extras, hex_decode_serial, mask_serial, ...)
# stay importable on Linux/macOS for CI. main() already exits immediately
# on non-Windows, before any of this is ever used.
if sys.platform == "win32":
    setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    LPDWORD = ctypes.POINTER(wt.DWORD)
    POVERLAPPED = ctypes.POINTER(OVERLAPPED)

    kernel32.CreateFileW.restype = wt.HANDLE
    kernel32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID, wt.DWORD, wt.DWORD, wt.HANDLE]
    kernel32.CreateEventW.restype = wt.HANDLE
    kernel32.CreateEventW.argtypes = [wt.LPVOID, wt.BOOL, wt.BOOL, wt.LPCWSTR]
    kernel32.WriteFile.restype = wt.BOOL
    kernel32.WriteFile.argtypes = [wt.HANDLE, wt.LPCVOID, wt.DWORD, LPDWORD, POVERLAPPED]
    kernel32.ReadFile.restype = wt.BOOL
    kernel32.ReadFile.argtypes = [wt.HANDLE, wt.LPVOID, wt.DWORD, LPDWORD, POVERLAPPED]
    kernel32.WaitForSingleObject.restype = wt.DWORD
    kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    kernel32.GetOverlappedResult.restype = wt.BOOL
    kernel32.GetOverlappedResult.argtypes = [wt.HANDLE, POVERLAPPED, LPDWORD, wt.BOOL]
    kernel32.CancelIo.restype = wt.BOOL
    kernel32.CancelIo.argtypes = [wt.HANDLE]
    kernel32.CloseHandle.restype = wt.BOOL
    kernel32.CloseHandle.argtypes = [wt.HANDLE]
    setupapi.SetupDiGetClassDevsW.restype = wt.HANDLE
    setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wt.LPCWSTR, wt.HWND, wt.DWORD]
    setupapi.SetupDiEnumDeviceInterfaces.restype = wt.BOOL
    setupapi.SetupDiEnumDeviceInterfaces.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p]
    setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wt.BOOL
    setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, LPDWORD, ctypes.c_void_p]
    setupapi.SetupDiDestroyDeviceInfoList.restype = wt.BOOL
    setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wt.HANDLE]


def find_usbprint_paths():
    paths = []
    hdev = setupapi.SetupDiGetClassDevsW(ctypes.byref(USBPRINT_GUID), None, None,
                                         DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if not hdev or hdev == INVALID_HANDLE_VALUE:
        return paths
    try:
        idx = 0
        while True:
            ifdata = SP_DEVICE_INTERFACE_DATA()
            ifdata.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not setupapi.SetupDiEnumDeviceInterfaces(hdev, None, ctypes.byref(USBPRINT_GUID),
                                                        idx, ctypes.byref(ifdata)):
                break
            idx += 1
            req = wt.DWORD(0)
            setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(ifdata), None, 0,
                                                      ctypes.byref(req), None)
            if req.value == 0:
                continue
            buf = ctypes.create_string_buffer(req.value)
            cbsize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            ctypes.memmove(buf, struct.pack("I", cbsize), 4)
            if setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(ifdata), buf,
                                                         req.value, None, None):
                paths.append(ctypes.wstring_at(ctypes.addressof(buf) + 4))
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return paths


# --------------------------------------------------------------------------- #
#  USB device-descriptor serial number (cfgmgr32)                              #
# --------------------------------------------------------------------------- #
# reinkpy's do_rw hashes info['serial_number'], which for a USB device is the
# iSerialNumber STRING DESCRIPTOR - NOT the serial stored in EEPROM. On Windows
# the same string is the last segment of the parent USB device's instance id
# (USB\VID_04B8&PID_XXXX\<serial>). Bus-generated ids contain '&' and are not
# serials, so they are skipped.
# EF-0: same reasoning as the setupapi/kernel32 block above - cfgmgr32 is
# Win32-only too.
CR_SUCCESS = 0


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("ClassGuid", GUID),
                ("DevInst", wt.DWORD), ("Reserved", ctypes.POINTER(ctypes.c_ulong))]


if sys.platform == "win32":
    cfgmgr32 = ctypes.WinDLL("cfgmgr32", use_last_error=True)

    # Re-declare with a typed last parameter; None is still a valid argument, so
    # the existing find_usbprint_paths() calls keep working unchanged.
    setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
        wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, LPDWORD,
        ctypes.POINTER(SP_DEVINFO_DATA)]
    cfgmgr32.CM_Get_Parent.argtypes = [ctypes.POINTER(wt.DWORD), wt.DWORD, ctypes.c_ulong]
    cfgmgr32.CM_Get_Parent.restype = ctypes.c_ulong
    cfgmgr32.CM_Get_Device_IDW.argtypes = [wt.DWORD, wt.LPWSTR, ctypes.c_ulong, ctypes.c_ulong]
    cfgmgr32.CM_Get_Device_IDW.restype = ctypes.c_ulong


def _looks_like_serial(seg):
    seg = (seg or "").strip()
    if not seg or "&" in seg or not (4 <= len(seg) <= 32):
        return False
    return all(c.isalnum() or c in "-_" for c in seg)


def _device_id(devinst):
    buf = ctypes.create_unicode_buffer(512)
    if cfgmgr32.CM_Get_Device_IDW(devinst, buf, 512, 0) != CR_SUCCESS:
        return None
    return buf.value


def usb_serial_candidates():
    """Serial strings the Windows USB stack reports for the Epson device."""
    out = []

    def add(v):
        if v and v not in out:
            out.append(v)

    hdev = setupapi.SetupDiGetClassDevsW(ctypes.byref(USBPRINT_GUID), None, None,
                                         DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if not hdev or hdev == INVALID_HANDLE_VALUE:
        return out
    try:
        idx = 0
        while True:
            ifdata = SP_DEVICE_INTERFACE_DATA()
            ifdata.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not setupapi.SetupDiEnumDeviceInterfaces(hdev, None, ctypes.byref(USBPRINT_GUID),
                                                        idx, ctypes.byref(ifdata)):
                break
            idx += 1
            req = wt.DWORD(0)
            setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(ifdata), None, 0,
                                                      ctypes.byref(req), None)
            if req.value == 0:
                continue
            buf = ctypes.create_string_buffer(req.value)
            cbsize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            ctypes.memmove(buf, struct.pack("I", cbsize), 4)
            info = SP_DEVINFO_DATA()
            info.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(ifdata), buf,
                                                             req.value, None, ctypes.byref(info)):
                continue
            path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
            if "VID_04B8" not in path.upper():
                continue
            parts = path.split("#")
            if len(parts) > 2 and _looks_like_serial(parts[2]):
                add(parts[2])
            dev = info.DevInst
            for _ in range(3):                       # walk up: interface -> device
                parent = wt.DWORD(0)
                if cfgmgr32.CM_Get_Parent(ctypes.byref(parent), dev, 0) != CR_SUCCESS:
                    break
                dev = parent.value
                did = _device_id(dev) or ""
                if not did.upper().startswith("USB\\"):
                    break
                seg = did.split("\\")[-1]
                if _looks_like_serial(seg):
                    add(seg)
                    break
    except Exception as e:
        print('  (USB serial lookup failed: %s)' % e)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return out


def candidate_paths(instance_id=None):
    cands = list(find_usbprint_paths())
    # device instance id from the user or the environment variable (else: auto-discovery only)
    iid = instance_id or os.environ.get("EPSON_INSTANCE_ID")
    if iid:
        cands.append(r"\\?\%s#{28d78fad-5a12-11d1-ae5b-0000f803a8c2}" % iid.replace("\\", "#"))
    expanded = []
    for p in cands:
        expanded.append(p)
        for mi in ("mi_00", "mi_01", "mi_02"):
            expanded.append(re.sub(r"mi_0\d", mi, p, flags=re.IGNORECASE))
    seen, out = set(), []
    for p in expanded:
        if "VID_04B8" not in p.upper():
            continue
        k = p.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    out.sort(key=lambda p: (0 if "MI_01" in p.upper() else 1))
    return out


def open_device(path):
    h = kernel32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE,
                             FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                             OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
    if not h or h == INVALID_HANDLE_VALUE:
        raise OSError('CreateFile failed: WinErr %s' % ctypes.get_last_error())
    return h


def _ov_io(func, h, data_or_len, timeout_ms, reading):
    ov = OVERLAPPED()
    ov.hEvent = kernel32.CreateEventW(None, True, False, None)
    try:
        nbytes = wt.DWORD(0)
        if reading:
            buf = ctypes.create_string_buffer(data_or_len)
            ok = func(h, buf, data_or_len, ctypes.byref(nbytes), ctypes.byref(ov))
        else:
            buf = ctypes.create_string_buffer(data_or_len, len(data_or_len))
            ok = func(h, buf, len(data_or_len), ctypes.byref(nbytes), ctypes.byref(ov))
        if not ok:
            err = ctypes.get_last_error()
            if err == ERROR_IO_PENDING:
                if kernel32.WaitForSingleObject(ov.hEvent, timeout_ms) == WAIT_TIMEOUT:
                    kernel32.CancelIo(h)
                    return None
                got = wt.DWORD(0)
                if not kernel32.GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(got), True):
                    return None
                nbytes = got
            else:
                raise OSError('I/O error WinErr %s' % err)
        return buf.raw[:nbytes.value] if reading else nbytes.value
    finally:
        kernel32.CloseHandle(ov.hEvent)


def write_all(h, data, timeout_ms=3000):
    return _ov_io(kernel32.WriteFile, h, data, timeout_ms, False)


def read_some(h, maxlen=1024, timeout_ms=2000):
    return _ov_io(kernel32.ReadFile, h, maxlen, timeout_ms, True)


# --------------------------------------------------------------------------- #
#  D4 (IEEE 1284.4) - packet-aligned reading                                   #
# --------------------------------------------------------------------------- #
CMD_ENTER_D4 = b"\x00\x00\x00\x1b\x01@EJL 1284.4\n@EJL\n@EJL\n"


class D4:
    def __init__(self, h):
        self.h = h
        self.buf = b""

    def _fill(self, timeout_ms):
        c = read_some(self.h, 1024, timeout_ms)
        if c:
            self.buf += c
            return True
        return False

    def drain(self, ms=300):
        while read_some(self.h, 1024, ms):
            pass
        self.buf = b""

    def send(self, psid, ssid, payload, credit=1, control=0):
        pkt = struct.pack(">BBHBB", psid, ssid, 6 + len(payload), credit, control) + payload
        write_all(self.h, pkt)

    def recv(self, timeout_ms=2500):
        while len(self.buf) < 6:
            if not self._fill(timeout_ms):
                return None
        psid, ssid, length, credit, control = struct.unpack(">BBHBB", self.buf[:6])
        if length < 6:
            self.buf = self.buf[6:]
            return (psid, ssid, length, credit, control, b"")
        while len(self.buf) < length:
            if not self._fill(timeout_ms):
                break
        payload = self.buf[6:length]
        self.buf = self.buf[length:]
        return (psid, ssid, length, credit, control, payload)


# --------------------------------------------------------------------------- #
#  D4 session: send a command / read the reply over the EPSON-CTRL channel     #
# --------------------------------------------------------------------------- #
class D4Session:
    def __init__(self, path):
        self.h = open_device(path)
        self.d = D4(self.h)
        self.rev = 0x20

    def close(self):
        try:
            kernel32.CloseHandle(self.h)
        except Exception:
            pass

    def connect(self):
        self.d.drain(300)
        write_all(self.h, CMD_ENTER_D4)
        time.sleep(0.2)
        self.d.recv(2500)                                   # enter reply
        # Init: 0x20 -> result 0x02 & rev 0x10 -> retry with 0x10
        rev, ok = 0x20, False
        for _ in range(3):
            self.d.send(0, 0, bytes([0x00, rev]), credit=1)
            r = self.d.recv(2500)
            pl = r[5] if r else b""
            if len(pl) >= 3 and pl[0] == 0x80:
                if pl[1] == 0x00:
                    ok = True
                    break
                if pl[2] and pl[2] != rev:
                    rev = pl[2]
                    continue
            break
        if not ok:
            raise IOError('D4 Init failed (the printer did not answer D4)')
        self.rev = rev
        # OpenChannel EPSON-CTRL socket 2 (rev 0x10 -> initCredit field included)
        if rev == 0x10:
            oc = struct.pack(">BBBHHHH", 0x01, 0x02, 0x02, 0x0100, 0x0100, 0x0000, 0x0000)
        else:
            oc = struct.pack(">BBBHHH", 0x01, 0x02, 0x02, 0x0100, 0x0100, 0x0000)
        self.d.send(0, 0, oc, credit=1)
        rep = self.d.recv(2500)
        pl = rep[5] if rep else b""
        if not (len(pl) >= 2 and pl[0] == 0x81 and pl[1] == 0x00):
            raise IOError('OpenChannel failed: %r' % (pl,))

    def _credit_request(self):
        'Take send-credit for the host (FROM the printer).'
        if self.rev == 0x10:
            cr = struct.pack(">BBBHH", 0x04, 0x02, 0x02, 0x0080, 0xFFFF)
        else:
            cr = struct.pack(">BBBH", 0x04, 0x02, 0x02, 0x0008)
        self.d.send(0, 0, cr, credit=1)
        for _ in range(4):
            r = self.d.recv(1500)
            if r is None:
                break
            if r[5] and r[5][0] == 0x84:
                break

    def cmd(self, payload, tries=14):
        'Send one command on the EPSON-CTRL channel and return the data reply.'
        self._credit_request()                                  # host -> send credit
        self.d.send(0, 0, struct.pack(">BBBH", 0x03, 0x02, 0x02, 0x0008), credit=1)  # reply credit for the printer
        self.d.recv(1200)                                       # CreditReply (ignored)
        self.d.send(0x02, 0x02, payload, credit=8)              # command
        for _ in range(tries):
            p = self.d.recv(2000)
            if p is None:
                continue
            if p[0] == 0x02 and p[5]:                           # data from the EPSON-CTRL channel
                return p[5]
        return None

    def read_eeprom(self, addr):
        resp = self.cmd(build_read_cmd(addr))
        if not resp:
            return None
        m = re.search(rb"EE:([0-9A-Fa-f]{6})", resp)
        if not m:
            return None
        h = m.group(1).decode()
        ra = int(h[0:4], 16)
        val = int(h[4:6], 16)
        if ra != addr:
            return None
        return val

    def write_eeprom(self, addr, val):
        resp = self.cmd(build_write_cmd(addr, val))
        return bool(resp) and (b":OK;" in resp)

    def service_rw(self, serial):
        'Run the Epson "rw" (reset waste) service command. Returns the raw reply.'
        return self.cmd(build_service_rw_cmd(serial), tries=20)


# --------------------------------------------------------------------------- #
#  High-level operations                                                       #
# --------------------------------------------------------------------------- #
def read_waste(sess):
    """Print the counter values, decoded little-endian (see the table above).

    The main pad's divisor is corroborated; the other two are marked "~".
    """
    print('\n  Waste ink counters:')
    out = []
    for addrs, div, verified, label in WASTE_COUNTERS:
        vals = []
        for a in addrs:
            v = sess.read_eeprom(a)
            vals.append(v)
        if None in vals:
            print('    - %-26s: READ FAILED (%r)' % (label, vals))
            out.append((label, None, None))
            continue
        raw = sum(v << (8 * i) for i, v in enumerate(vals))     # little-endian
        pct = (raw / div) * 100.0
        mark = '' if verified else '~'
        note = '' if verified else '  (divisor not corroborated)'
        flag = '   <-- FULL' if (verified and pct >= 100.0) else ''
        print('    - %-26s: %s%6.2f%%   raw=%-6d%s%s' % (label, mark, pct, raw, note, flag))
        out.append((label, raw, pct))
    return out


def read_extras(sess):
    """Show the spec's other waste-related cells and whether they sit at the
    value the spec resets them to. --reset never touched any of these."""
    print('\n  Other waste-related cells from the same spec (not written by --reset):')
    out = {}
    for a, target in EXTRA_WATCH:
        v = sess.read_eeprom(a)
        out[a] = v
        if v is None:
            note = '   READ FAILED'
        elif v == target:
            note = '   (at the spec reset value)'
        else:
            note = '   <-- NOT at the spec reset value (%d)' % target
        print('    - 0x%02X: %s%s' % (a, ('%3d' % v) if v is not None else '  ?', note))
    print('\n  Mirrors of the main counter (read-only; they should agree):')
    seen = []
    for addrs, label in MIRROR_CELLS:
        vals = [sess.read_eeprom(a) for a in addrs]
        if None in vals:
            print('    - %-16s 0x%02X/0x%02X: READ FAILED' % (label, addrs[0], addrs[1]))
            continue
        val = sum(v << (8 * i) for i, v in enumerate(vals))
        seen.append(val)
        print('    - 0x%02X/0x%02X  %-46s %d' % (addrs[0], addrs[1], label, val))
    if len(seen) > 1 and len(set(seen)) > 1:
        print('    !! The mirrors DISAGREE. A reset that leaves one of them behind will')
        print('       be undone at the next power-on. Use --reset-full, not --reset.')
    return out


def read_serial(sess):
    try:
        chars = []
        for a in range(0x0644, 0x064E):
            v = sess.read_eeprom(a)
            if v and 32 <= v < 127:
                chars.append(chr(v))
        return "".join(chars).strip()
    except Exception:
        return '(unreadable)'


def mask_serial(serial):
    """Show only the last 4 characters; empty/unreadable values pass through unchanged."""
    if not serial or serial == '(unreadable)':
        return serial
    if len(serial) <= 4:
        return '*' * len(serial)
    return '*' * (len(serial) - 4) + serial[-4:]


def backup_bank0(sess):
    print('\n  Taking a full bank-0 EEPROM backup (0x00-0xFF)...')
    cells = {}
    for a in range(0x00, 0x100):
        v = sess.read_eeprom(a)
        cells["%02X" % a] = v
        if a % 32 == 31:
            print('    ...0x%02X done' % a)
    ok = sum(1 for v in cells.values() if v is not None)
    print('    %d/256 cells read.' % ok)
    return cells


def save_backup_file(cells):
    """Write a bank-0 backup next to the script (not the caller's CWD) and print its absolute path."""
    ts = time.strftime("%Y%m%d_%H%M%S")
    bkp = "epson_backup_bank0_%s.json" % ts
    bkp_path = os.path.join(SCRIPT_DIR, bkp)
    with open(bkp_path, "w", encoding="utf-8") as f:
        json.dump({"time": ts, "bank0": cells}, f, indent=2)
    print('  Backup saved: %s' % bkp_path)
    return bkp_path


def do_reset(sess):
    print('\n  >>> RESET: writing 0 to the waste counter cells...')
    all_ok = True
    for a in WASTE_ADDRS:
        ok = sess.write_eeprom(a, 0)
        after = sess.read_eeprom(a)
        status = "OK" if (ok and after == 0) else 'FAILED (read back=%r)' % after
        print("    - 0x%04X <- 0   [%s]" % (a, status))
        all_ok &= (ok and after == 0)
    return all_ok


def do_full_reset(sess):
    """Write the FULL cell set from the reinkpy spec for this model group.

    --reset only ever wrote six cells. The spec lists fourteen, and three of
    them reset to 0x5E rather than to zero. Cells the partial reset never
    touched are a candidate explanation for the main pad counter reappearing
    after a power cycle.
    """
    print('\n  >>> FULL RESET: writing the reinkpy spec values to %d cells...'
          % len(FULL_RESET_CELLS))
    all_ok = True
    for a, v in FULL_RESET_CELLS:
        before = sess.read_eeprom(a)
        ok = sess.write_eeprom(a, v)
        after = sess.read_eeprom(a)
        good = bool(ok) and after == v
        print('    - 0x%04X  %s -> %-3d   [%s]'
              % (a, ('%3d' % before) if before is not None else '  ?', v,
                 "OK" if good else 'FAILED (read back=%r)' % after))
        all_ok &= good
    return all_ok


def hex_decode_serial(v):
    """Decode an ASCII-hex serial blob back to text, dropping NUL padding.

    Returns None when the string is not plain hex.
    """
    try:
        if not v or len(v) % 2 or not all(c in "0123456789abcdefABCDEF" for c in v):
            return None
        t = bytes.fromhex(v).replace(b"\x00", b"").decode("ascii")
        return t if (t and t.isprintable()) else None
    except Exception:
        return None


def serial_candidates(sess, override=None, show=False):
    """Ordered list of strings to try as the "rw" hash input.

    reinkpy hashes info['serial_number'], the USB iSerialNumber STRING
    DESCRIPTOR; a report on epson_print_conf issue #35 instead used the
    plain-text serial and got ":OK;", so the plain one is tried first.
    MEASURED on this printer (2026-09-04): the two sources do NOT agree -
    Shapes only, illustrated with a made-up serial - never the real one:
        EEPROM 0x0644-0x064D : ABCD012345            (plain text, 10 chars)
        USB parent instance  : 414243443031323300    (ASCII-hex of "ABCD0123"
                                                      plus a trailing 00 byte)
    Windows does not preserve the descriptor's letter case (symbolic links come
    back lower case, SetupAPI ids upper case), so both cases are tried. Which
    string the firmware actually hashes is UNVERIFIED, hence a candidate list
    rather than a single guess. --serial forces one string and skips the rest.
    """
    def fmt(v):
        return (v if show else mask_serial(v)) or '(none)'

    eeprom = read_serial(sess)
    usb = usb_serial_candidates()
    print('\n  Serial sources:')
    print('    - EEPROM (0x0644-0x064D) : %s' % fmt(eeprom))
    print('    - USB descriptor         : %s'
          % (', '.join(fmt(u) for u in usb) if usb else '(none found)'))
    if override:
        print('    -> using --serial from the command line (nothing else is tried)')
        return [override]

    cands = []

    def add(v, why):
        if v and all(v != c[0] for c in cands):
            cands.append((v, why))

    if eeprom and eeprom != '(unreadable)':
        add(eeprom, 'EEPROM plain-text serial')
    for u in usb:
        add(hex_decode_serial(u), 'USB descriptor, hex-decoded')
    for u in usb:
        add(u.upper(), 'USB descriptor, upper case')
        add(u.lower(), 'USB descriptor, lower case')
    if not cands:
        return []
    print('    -> %d candidate(s), tried in this order:' % len(cands))
    for i, (v, why) in enumerate(cands, 1):
        print('       %d. %-22s (%s)' % (i, fmt(v), why))
    return [c[0] for c in cands]


def do_service_reset(sess, serials, show=False):
    """Run the Epson "rw" service command (firmware level).

    Reference: reinkpy Device.do_rw. reinkpy's own docstring is unsure what the
    command does ('for "reset waste"?'), so every raw reply is printed verbatim
    instead of being interpreted. Candidates are tried until one reply contains
    ":OK;".
    """
    if not serials:
        print('\n  !! No serial number available - cannot build the "rw" command.')
        return False
    print('\n  >>> SERVICE COMMAND "rw" (firmware level)')
    for i, sn in enumerate(serials, 1):
        try:
            digest = hashlib.sha1(sn.encode("ascii")).hexdigest()
        except Exception as e:
            print('    [%d/%d] skipped (not ASCII): %s' % (i, len(serials), e))
            continue
        print('    [%d/%d] serial=%-22s sha1=%s'
              % (i, len(serials), (sn if show else mask_serial(sn)), digest))
        resp = sess.service_rw(sn)
        if resp is None:
            print('          no reply (timed out)')
            continue
        print('          raw reply: %r' % resp)
        if b":OK;" in resp:
            print('          -> ACCEPTED (reply contains ":OK;")')
            return True
        print('          -> not accepted')
    print('    -> No candidate was clearly accepted. Judge from the raw replies above.')
    return False


def resolve_input_path(path):
    """A bare filename (no directory component) is looked up in the CWD first, then next to the script."""
    if os.path.isfile(path):
        return path
    if not os.path.dirname(path):
        candidate = os.path.join(SCRIPT_DIR, path)
        if os.path.isfile(candidate):
            return candidate
    return path


def do_restore(sess, path):
    path = resolve_input_path(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    cells = data.get("bank0", {})
    print('\n  Restoring from backup: %s' % path)
    n, missing = 0, []
    for a in RESTORE_ADDRS:
        key = "%02X" % a
        if key not in cells or cells[key] is None:
            missing.append(key)
            continue
        if sess.write_eeprom(a, int(cells[key])):
            print("    - 0x%04X <- %d" % (a, cells[key]))
            n += 1
    print('    %d/%d cells restored.' % (n, len(RESTORE_ADDRS)))
    if missing:
        print('    !! not present in this backup: %s' % ', '.join(missing))


# --------------------------------------------------------------------------- #
def connect_any(instance_id=None):
    paths = candidate_paths(instance_id)
    last = None
    for p in paths:
        try:
            s = D4Session(p)
        except OSError as e:
            last = e
            continue
        try:
            s.connect()
            return s, p
        except Exception as e:
            last = e
            s.close()
    raise IOError('Could not establish a D4 session. Last error: %s' % last)


def main():
    if sys.platform != "win32":
        print('Windows only.')
        sys.exit(1)
    ap = argparse.ArgumentParser(description='Epson L3251 waste ink pad counter reset over USB (D4)')
    ap.add_argument("--reset", action="store_true", help='RESET the six known counter cells (writes!)')
    ap.add_argument("--reset-full", action="store_true",
                     help='RESET the FULL cell set from the reinkpy spec (%d cells, three of them to 0x5E; writes!)'
                          % len(FULL_RESET_CELLS))
    ap.add_argument("--service-reset", action="store_true",
                     help='Run the Epson "rw" command - a TEMPORARY reset that does not survive a power cycle (writes!)')
    ap.add_argument("--serial", metavar='SN',
                     help='Serial string to hash for --service-reset (overrides auto-detection)')
    ap.add_argument("--restore", metavar='FILE', help='Write every waste-related cell back from a backup JSON')
    ap.add_argument("--no-backup", action="store_true", help='Do NOT take a backup before writing')
    ap.add_argument("--instance-id", metavar="IID",
                     default=os.environ.get("EPSON_INSTANCE_ID"),
                     help='Device instance id (example: USB\\VID_04B8&PID_118A&MI_00\\<INSTANCE>). If omitted, only automatic discovery is used.')
    ap.add_argument("--show-serial", action="store_true", help='Print the full serial number instead of the masked form')
    ap.add_argument("--version", action="version", version="%(prog)s " + __version__)
    args = ap.parse_args()

    print("=" * 70)
    print('  EPSON L3251  Waste Ink Pad  USB/D4 counter reset  v%s' % __version__)
    print("=" * 70)

    try:
        sess, path = connect_any(args.instance_id)
    except Exception as e:
        print('\n  !! Could not connect:', e)
        print('  Is the printer connected over USB and powered on? Another program may be holding it.')
        sys.exit(2)

    print('  Connected (USB/D4, revision 0x%02X).' % sess.rev)
    serial = read_serial(sess)
    print('  Serial:', serial if args.show_serial else mask_serial(serial))

    try:
        if args.restore:
            read_waste(sess)
            read_extras(sess)
            if args.no_backup:
                print('\n  --no-backup given: skipping the safety backup before restore.')
            else:
                cells = backup_bank0(sess)
                save_backup_file(cells)
            do_restore(sess, args.restore)
            print('\n  After restore:')
            read_waste(sess)
            read_extras(sess)
            return

        writing = args.reset or args.reset_full or args.service_reset
        read_waste(sess)
        read_extras(sess)

        if not writing:
            print('\n  (READ-ONLY mode - nothing was written.)')
            if not args.no_backup:
                cells = backup_bank0(sess)
                save_backup_file(cells)
            print('\n  Add --reset, --reset-full or --service-reset to write.')
            return

        if args.reset and args.reset_full:
            print('\n  !! --reset and --reset-full are mutually exclusive. Pick one.')
            sys.exit(2)

        # --- write path ---
        if not args.no_backup:
            cells = backup_bank0(sess)
            save_backup_file(cells)

        ok = True
        if args.reset_full:
            ok &= do_full_reset(sess)
        elif args.reset:
            ok &= do_reset(sess)
        if args.service_reset:
            sns = serial_candidates(sess, args.serial, args.show_serial)
            ok &= do_service_reset(sess, sns, args.show_serial)

        print('\n  State after the write:')
        read_waste(sess)
        read_extras(sess)
        if ok:
            print('\n  DONE. Power the printer OFF and ON with its own button, then run this'
                  '\n  script again in read-only mode and compare the values.')
        else:
            print('\n  WARNING: at least one step did not report success; check the output above.')
    finally:
        sess.close()


if __name__ == "__main__":
    main()

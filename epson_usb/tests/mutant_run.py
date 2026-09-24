#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The mutant proof: the suite must go red when the library lies.

A test suite that passes proves nothing about what it would catch. This script
breaks one line of the library at a time -- in the two places where a *wrong*
version of the code is a plausible mistake rather than a random one -- runs the
suite in a separate process, and requires it to fail. Then it puts the file back
exactly as it was.

Targets:

1. ``epson_usb/eeprom.py``: ``decode_counter()``, little-endian sum turned into
   a big-endian one. That is the mistake the project chased for a session (it
   made a 100 % counter read as 97 %, and the printer's own error state is what
   settled it), so the suite must notice.
2. ``epson_usb/epson_ctrl.py``: ``eeprom_write_payload()``, the two address
   bytes swapped. The frame would still look well-formed and the printer would
   answer, so only a test that checks *which* address was written catches it.

Not a target here: the waste-counter divisor. It is model knowledge, it lives in
the client (``epson_l3250.py`` in the source project), and the source project's
own mutant run covers it -- this library has no model tables to mutate.

The files are read and written as **bytes**: the package is LF-only (see the
README), and a text-mode rewrite on Windows would silently convert every line of
the file. Each file is restored from the bytes read before the mutation, and the
script fails if a restore does not match.

Hardware: none. Network: none. A real printer: never touched.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent

TARGETS = [
    {
        "id": "waste-decode",
        "file": "epson_usb/eeprom.py",
        "what": "decode_counter(): little-endian -> big-endian (the historical bug)",
        "original": b"    return sum(v << (8 * i) for i, v in enumerate(values))\n",
        "mutant": (
            b"    return sum(v << (8 * (len(values) - 1 - i))"
            b" for i, v in enumerate(values))"
            b"  # MUTANT (waste-decode): big-endian, on purpose\n"
        ),
    },
    {
        "id": "write-frame",
        "file": "epson_usb/epson_ctrl.py",
        "what": "eeprom_write_payload(): the address bytes (lo, hi) -> (hi, lo)",
        "original": b"        + bytes([lo, hi, int(value)])\n",
        "mutant": (
            b"        + bytes([hi, lo, int(value)])"
            b"  # MUTANT (write-frame): address bytes swapped\n"
        ),
    },
]


def run_suite():
    """Run the package's own suite in a separate process; True when green."""
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover",
         "-s", "epson_usb/tests", "-t", "."],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = result.stdout.decode("utf-8", "replace")
    return result.returncode == 0, output.strip().splitlines()[-1:] or [""]


def main() -> int:
    failures = []
    print("baseline: the suite must be green before anything is mutated")
    green, tail = run_suite()
    print("  %s %s" % ("OK " if green else "RED", tail[0]))
    if not green:
        print("FAIL: the suite is not green to begin with")
        return 1

    for target in TARGETS:
        path = REPO_ROOT / target["file"]
        original_bytes = path.read_bytes()
        if original_bytes.count(target["original"]) != 1:
            print("SKIP %s: the line to mutate is not there (found %d)"
                  % (target["id"], original_bytes.count(target["original"])))
            failures.append(target["id"])
            continue
        print("%s: %s" % (target["id"], target["what"]))
        try:
            path.write_bytes(
                original_bytes.replace(target["original"], target["mutant"])
            )
            green, tail = run_suite()
        finally:
            # Bytes, and from the copy read before the mutation: the file must
            # come out of this byte for byte, or the repository is left dirty.
            path.write_bytes(original_bytes)
        restored = path.read_bytes() == original_bytes
        print("  mutant: %s | restored: %s"
              % ("red (caught)" if not green else "GREEN (blind spot!)",
                 "yes" if restored else "NO"))
        print("  %s" % tail[0])
        if green or not restored:
            failures.append(target["id"])

    if failures:
        print("FAIL: %s" % ", ".join(failures))
        return 1
    print("OK: every mutant was caught, every file restored")
    return 0


if __name__ == "__main__":
    sys.exit(main())

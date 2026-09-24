"""EEPROM value conventions: how a number is stored across cells.

This module exists for one reason: **byte order**. Everything else about a
counter -- which addresses it occupies, what its 100% value is, whether the
firmware locks it -- is per-model knowledge and belongs to the caller. The byte
order, on the other hand, is a property of the printer's EEPROM layout, and
getting it wrong is silent: the tool still reads a number, it just reads the
wrong one.

Each counter is a little-endian integer spread over consecutive cells: the
first address holds the *low* byte. The evidence, from an L3251 on 2026-09-04,
is decisive because the printer's error state is observable:

===========  =========  ============  =============  =======================
``0x30``     ``0x31``   big endian    little endian  printer showed error?
===========  =========  ============  =============  =======================
``0xCC``     ``0x18``   52248 (823%)  **6348 (100.0%)**  **yes**
``0x3B``     ``0x18``   15128 (238%)  **6203 (97.7%)**   **no**
===========  =========  ============  =============  =======================

Big-endian calls both readings "full" and cannot explain the error clearing.

The historical standalone tool decoded this in two separate places, so a
mutated big-endian copy could stay green in one of them. Here there is exactly
one function, :func:`decode_counter`, and ``epson_usb/tests/mutant_run.py``
proves that flipping it (or the write frame's byte order) turns the whole suite
red. Run it with ``python epson_usb/tests/mutant_run.py``.
"""

from __future__ import annotations

from typing import Sequence

__all__ = ["decode_counter", "percentage"]


def decode_counter(values: Sequence[int]) -> int:
    """Combine cell values into one integer, **little-endian**.

    ``values`` are in address order, so the first element is the low byte:

    >>> decode_counter([0x3B, 0x18])     # 0x30=0x3B, 0x31=0x18
    6203
    >>> decode_counter([])
    0
    """
    return sum(v << (8 * i) for i, v in enumerate(values))


def percentage(raw: int, divider: float) -> float:
    """Percentage of a counter's limit, where ``divider`` is the 100% value.

    ``divider`` is per-model data supplied by the caller. Note the unit: an
    Epson counter whose full value is 6346 has a divider of 6346 here, while
    ``epson_print_conf`` stores "percent per unit" in the same slot (63.46) and
    divides by it. Converting between the two is the caller's job; see
    ``epson_l3250.print_conf_params`` in this repository for how, and
    ``CounterGroup.percent_per_unit`` for why the difference matters.
    """
    if not divider:
        raise ValueError("divider must be non-zero")
    return (raw / divider) * 100.0

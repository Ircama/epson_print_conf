# Benchmarking Python SNMP Libraries for Epson Printer Communication

This document compares pure Python SNMP libraries, with the goal of performing unauthenticated, sequential SNMPv1 queries to a single Epson printer.

The approach to use libraries implemented entirely in Python has the goal to avoid the complexity and overhead of wrappers around native libraries, while maintaining acceptable performance.

For the use case of this repository, that is interfacing with Epson printers, synchronous SNMP simplifies development and maintenance without compromising performance.

Compared libraries and architectures:

- Ilya Etingof’s [etingof/pysnmp](https://github.com/etingof/pysnmp) project (unmaintained) in synchronous mode,
- [pysnmplib](https://github.com/pysnmp/pysnmp) in synchronous mode,
- [pysnmp v5.1](https://github.com/lextudio/pysnmp/) synchronous mode,
- [pysnmp v7.1](https://github.com/lextudio/pysnmp/) asynchronous mode,
- [pysnmp v7.1 with pysnmp-sync-adapter](https://github.com/Ircama/pysnmp-sync-adapter) synchronous wrapper,
- [pysnmp v7.1 with pysnmp-sync-adapter and cluster_varbinds](https://github.com/Ircama/pysnmp-sync-adapter#cluster_varbinds) for highest performances,
- raw socket SNMPv1 implementation (synchronous mode).
- Pure python implementation using the [asn1](https://github.com/andrivet/python-asn1) and the default socket libraries.
- [py-snmp-sync](https://github.com/Ircama/py-snmp-sync) synchronous client implemented over PySNMP.

The comparison exploits a trivial benchmark that performs 100 SNMPv1 GET requests of the same OID to the same printer, measuring total execution time. The used OID is `1.3.6.1.2.1.25.3.2.1.3.1` (`sysName`).

Benchmark results of this use case show that the legacy synchronous backend `pysnmp.hlapi.v1arch` from [etingof/pysnmp](https://github.com/etingof/pysnmp) delivers performance comparable to the most efficient asynchronous implementations.

The current codebase of epson_print_conf still relies on this unmaintained `etingof/pysnmp`, specifically its `v1arch` synchronous HLAPI, which remains performant due to:

- A streamlined architecture that avoids per-request SNMP engine instantiation
- Minimal overhead in dispatching SNMP requests

However, `etingof/pysnmp` is not published on PyPI. For PyPI-based distribution and dependency management, a switch to a maintained variant such as [`pysnmp`](https://pypi.org/project/pysnmp) or [`pysnmplib`](https://pypi.org/project/pysnmplib) would be necessary.

Earlier versions of `pysnmp` supported both synchronous and asynchronous APIs. In contrast, recent versions (v7+) have removed synchronous support in favor of an asyncio-only architecture. While this enables more scalable and resource-efficient SNMP operations, it introduces significant migration complexity for legacy codebases built around blocking SNMPv1 workflows.

A naïve approach to restoring synchronous behavior, e.g., by wrapping each async call in `asyncio.run()`, leads to severe performance degradation. This pattern repeatedly creates and tears down the asyncio event loop and transport stack, incurring massive overhead.

To mitigate this, several approaches have been explored:

* [`pysnmp-sync-adapter`](https://github.com/Ircama/pysnmp-sync-adapter): a lightweight compatibility layer wrapping `pysnmp.hlapi.v1arch.asyncio` and `pysnmp.hlapi.v3arch.asyncio` with blocking equivalents (e.g., `get_cmd_sync`). It reuses the asyncio event loop and transport targets, avoiding per-call overhead and achieving optimal performance while maintaining a synchronous API.

* [`py-snmp-sync`](https://github.com/Ircama/py-snmp-sync): offers high performance by bypassing the asyncio-based API entirely. Instead, it directly uses the lower-level shared components of `pysnmp` that support both sync and async execution. It implements a custom `SyncUdpTransportTarget` based on raw sockets. However, it currently supports only a specialized form of `get_cmd`, limiting general HLAPI compatibility.

* A separate low-level implementation using ASN.1 and sockets directly is also tested. This approach shows excellent performance for the `get_cmd` request/response pattern but is significantly more complex to maintain and does not support the full SNMP operation set.

Each approach offers trade-offs between generality, maintainability, and performance. For applications requiring full HLAPI compatibility with minimal refactoring, `pysnmp-sync-adapter` is a practical and efficient choice. For tightly optimized use cases the raw variants can provide superior throughput.

Optimal performance is achieved using the `cluster_varbinds` utility from `pysnmp-sync-adapter`, which provides possibly the simplest synchronous interface and includes optimized parallel processing which wraps `asyncio` under the hood.

---

## Code used for the benchmarks and results

### Usage of https://github.com/etingof/pysnmp

```python
# Usage of https://github.com/etingof/pysnmp

# pip uninstall pysnmplib
# pip uninstall pysnmp
# pip install pyasn1==0.4.8
# pip install git+https://github.com/etingof/pysnmp.git@master#egg=pysnmp

import platform
import time
import sys
from pysnmp.hlapi.v1arch import *

def snmp_get(*snmp_conf):
    for errorIndication, errorStatus, errorIndex, varBinds in getCmd(
        *snmp_conf, ('1.3.6.1.2.1.25.3.2.1.3.1', None)
    ):
        if errorIndication:
            return f"Error: {errorIndication}"
        elif errorStatus:
            return f"{errorStatus.prettyPrint()} at {errorIndex}"
        elif len(varBinds) != 1:
            return f"varBinds error: {len(varBinds)}"
        elif len(list(varBinds[0])) != 2:
            return f"varBinds[0] error: {len(list(varBinds[0]))}"
        return varBinds[0][1]

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python script.py <target-ip>")
        sys.exit(1)

    start_time = time.time()

    snmp_conf = (
        SnmpDispatcher(),
        CommunityData('public', mpModel=0),
        UdpTransportTarget((sys.argv[1], 161)),
    )
    for i in range(100):
        response = snmp_get(*snmp_conf)
        print(response)

    print("--- %s seconds ---" % (time.time() - start_time))
    # --- 0.8790323734283447 seconds ---
    # --- 0.866567850112915 seconds ---
    # --- 0.8512802124023438 seconds ---
    # --- 0.8214724063873291 seconds ---
```

### Usage of https://github.com/pysnmp/pysnmp

```python
# Usage of https://github.com/pysnmp/pysnmp

# pip uninstall pysnmp
# pip install pyasn1==0.4.8
# pip install pysnmplib

# Alternative working library: pip install pysnmp==5.1.0 (https://docs.lextudio.com/snmp/)

import platform
import time
import sys
from pysnmp.hlapi import *

def snmp_get(*snmp_conf):
    for errorIndication, errorStatus, errorIndex, varBinds in getCmd(
        *snmp_conf, ObjectType(ObjectIdentity('1.3.6.1.2.1.25.3.2.1.3.1'))
    ):
        if errorIndication:
            return f"Error: {errorIndication}"
        elif errorStatus:
            return f"{errorStatus.prettyPrint()} at {errorIndex}"
        elif len(varBinds) != 1:
            return f"varBinds error: {len(varBinds)}"
        elif len(list(varBinds[0])) != 2:
            return f"varBinds[0] error: {len(list(varBinds[0]))}"
        return varBinds[0][1]

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python script.py <target-ip>")
        sys.exit(1)

    start_time = time.time()

    snmp_conf = (
        SnmpEngine(),
        CommunityData('public', mpModel=0),
        UdpTransportTarget((sys.argv[1], 161)),
        ContextData(),
    )
    for i in range(100):
        response = snmp_get(*snmp_conf)
        print(response)

    print("--- %s seconds ---" % (time.time() - start_time))

    # --- 1.0873637199401855 seconds ---
    # --- 1.0969550609588623 seconds ---
```

### Usage of https://github.com/lextudio/pysnmp 7.1 simulating sync behaviour (inefficient)

```python
# Usage of https://github.com/lextudio/pysnmp 7.1
# Simulate sync behaviour via asyncio.run() (extremely inefficient and slow mode)

# pip uninstall pysnmplib
# pip uninstall pyasn1==0.4.8
# pip uninstall pysnmp # git+https://github.com/etingof/pysnmp.git@master#egg=pysnmp
# pip install pysnmp

import platform
import asyncio
import sys
import time
from pysnmp.hlapi.v1arch.asyncio import *  # synchronous mode is not allowed

async def snmp_get(community_data, transport_target):
    errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
        SnmpDispatcher(),  # It cannot be initialized once and then reused!
        community_data,
        transport_target,
        ObjectType(ObjectIdentity('1.3.6.1.2.1.25.3.2.1.3.1')),  # Model
        lookupMib=False,
        lexicographicMode=False,
    )

    if errorIndication:
        return f"Error: {errorIndication}"
    elif errorStatus:
        return f"{errorStatus.prettyPrint()} at {errorIndex}"
    elif len(varBinds) != 1:
        return f"varBinds error: {len(varBinds)}"
    elif len(list(varBinds[0])) != 2:
        return f"varBinds[0] error: {len(list(varBinds[0]))}"
    return varBinds[0][1]

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python script.py <target-ip>")
        sys.exit(1)

    if platform.system()=='Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    start_time = time.time()

    community_data = CommunityData("public", mpModel=0)
    transport_target = asyncio.run(
        UdpTransportTarget.create((sys.argv[1], 161))
    )
    for i in range(100):
        response = asyncio.run(snmp_get(community_data, transport_target))
        print(response)

    print("--- %s seconds ---" % (time.time() - start_time))

    # --- 13.862501621246338 seconds ---
    # --- 13.586702585220337 seconds ---
    # --- 13.565954208374023 seconds ---
```

### Usage of https://github.com/lextudio/pysnmp in async mode

```python
# Usage of https://github.com/lextudio/pysnmp
# Using asyncio.gather() for 100 asynch tasks. Single ObjectType in get_cmd

# pip uninstall pysnmplib
# pip uninstall pysnmp # git+https://github.com/etingof/pysnmp.git@master#egg=pysnmp
# pip install pysnmp

import platform
import asyncio
import sys
import time
from pysnmp.hlapi.v1arch.asyncio import *

async def snmp_get(dispatcher, community_data, transport_target):
    errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
        dispatcher,
        community_data,
        transport_target,
        ObjectType(ObjectIdentity('1.3.6.1.2.1.25.3.2.1.3.1')),
        lookupMib=False,
        lexicographicMode=False,
    )
    if errorIndication:
        return f"Error: {errorIndication}"
    elif errorStatus:
        return f"{errorStatus.prettyPrint()} at {errorIndex}"
    elif len(varBinds) != 1:
        return f"varBinds error: {len(varBinds)}"
    elif len(list(varBinds[0])) != 2:
        return f"varBinds[0] error: {len(list(varBinds[0]))}"
    return varBinds[0][1]

async def main(target_ip):
    # Reuse dispatcher and target
    dispatcher = SnmpDispatcher()
    community_data = CommunityData("public", mpModel=0)
    transport_target = await UdpTransportTarget.create((target_ip, 161))

    tasks = [
        snmp_get(dispatcher, community_data, transport_target)
        for _ in range(100)
    ]
    results = await asyncio.gather(*tasks)

    for r in results:
        print(r)
    print("--- %s seconds ---" % (time.time() - start_time))

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python script.py <target-ip>")
        sys.exit(1)

    if platform.system()=='Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    start_time = time.time()
    asyncio.run(main(sys.argv[1]))

    # --- 1.4966695308685303 seconds ---
    # --- 1.4908103942871094 seconds ---
    # --- 1.4765450954437256 seconds ---
    # --- 1.4733057022094727 seconds ---
```

### Usage of https://github.com/lextudio/pysnmp maximizing performance

```python
# Usage of https://github.com/lextudio/pysnmp
# Multiple ObjectType in get_cmd
# Using asyncio.gather() for 10 asynch tasks, each including a PDU of 10 OIDs.

# pip uninstall pysnmplib
# pip uninstall pysnmp # git+https://github.com/etingof/pysnmp.git@master#egg=pysnmp
# pip install pysnmp

import platform
import asyncio
import sys
import time
from pysnmp.hlapi.v3arch.asyncio import *

async def snmp_get(dispatcher, community_data, transport_target):
    object_types = [
        ObjectType(
            ObjectIdentity('1.3.6.1.2.1.25.3.2.1.3.1')
        ) for _ in range(10)
    ]
    """
Note: we cannot put too many data into a single PDU due to a protocol-level
limit, otherwise we get the SNMP error "tooBig" like "tooBig at 54", that
indicates that the SNMP response PDU exceeds the maximum size supported by the
agent or the transport (typically 484 bytes by default for UDP). For this
reason, to get the 100 queries benckmark, we build a taks of 10 requests, each
including 10 queries.
    """

    errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
        dispatcher,
        community_data,
        transport_target,
        ContextData(),
        *object_types,
        lookupMib=False
    )

    if errorIndication:
        return [f"Error: {errorIndication}"]
    elif errorStatus:
        return [f"{errorStatus.prettyPrint()} at {errorIndex}"]
    
    return [val.prettyPrint() for _, val in varBinds]

async def main(target_ip):
    dispatcher = SnmpEngine()
    community_data = CommunityData("public", mpModel=0)
    transport_target = await UdpTransportTarget.create((target_ip, 161))

    tasks = [
        snmp_get(dispatcher, community_data, transport_target)
        for _ in range(10)
    ]
    results = await asyncio.gather(*tasks)

    for r in results:
        for i in r:
            print(i)

    print("--- %s seconds ---" % (time.time() - start_time))

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python script.py <target-ip>")
        sys.exit(1)

    if platform.system() == 'Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    start_time = time.time()
    asyncio.run(main(sys.argv[1]))

    # --- 0.47261977195739746 seconds ---
    # --- 0.47225403785705566 seconds ---
    # --- 0.4908156394958496 seconds ---
```

### Usage of https://github.com/Ircama/pysnmp-sync-adapter

```python
# pip uninstall pysnmplib
# pip install pysnmp-sync-adapter

import sys
import time
import asyncio
import platform
from pysnmp.hlapi.v1arch.asyncio import *
from pysnmp_sync_adapter import (
    get_cmd_sync, next_cmd_sync, set_cmd_sync, bulk_cmd_sync,
    walk_cmd_sync, bulk_walk_cmd_sync, create_transport
)

def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py <host>")
        sys.exit(1)

    if platform.system()=='Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    host = sys.argv[1]
    oid_str = '1.3.6.1.2.1.25.3.2.1.3.1'
    community = 'public'

    # Pre-create the engine once
    dispatcher = SnmpDispatcher()

    # Pre-create the transport once
    transport = create_transport(UdpTransportTarget, (host, 161), timeout=1)

    # Pre-create oid and CommunityData once
    auth_data = CommunityData(community, mpModel=0)
    oid_t = ObjectType(ObjectIdentity(oid_str))

    start = time.time()
    for _ in range(100):
        try:
            error_ind, error_status, error_index, var_binds = get_cmd_sync(
                dispatcher,
                auth_data,
                transport,
                oid_t
            )
            if error_ind:
                raise RuntimeError(f"SNMP error: {error_ind}")
            elif error_status:
                raise RuntimeError(
                    f'{error_status.prettyPrint()} at {error_index and var_binds[int(error_index) - 1][0] or "?"}'
                )
            else:
                for oid, val in var_binds:
                    print(val.prettyPrint())
        except Exception as e:
            print("Request failed:", e)

    print(f"--- {time.time() - start:.3f} seconds ---")

if __name__ == '__main__':
    main()

# --- 1.217 seconds ---
# --- 1.290 seconds ---
# --- 1.234 seconds ---
```

### https://github.com/Ircama/pysnmp-sync-adapter#cluster_varbinds over PySNMP.

This simple approach offers the best performances among all tests.

```python
# pip uninstall pysnmplib
# pip install pysnmp-sync-adapter

import sys
import time
import asyncio
import platform
from pysnmp.hlapi.v1arch.asyncio import *
from pysnmp_sync_adapter import (
    parallel_get_sync, create_transport, cluster_varbinds
)

def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py <host>")
        sys.exit(1)

    if platform.system()=='Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    host = sys.argv[1]
    oid_str = '1.3.6.1.2.1.25.3.2.1.3.1'
    community = 'public'

    # Pre-create the engine once
    dispatcher = SnmpDispatcher()

    # Pre-create the transport once
    transport = create_transport(UdpTransportTarget, (host, 161), timeout=1)

    # Pre-create CommunityData once
    auth_data = CommunityData(community, mpModel=0)
    oid_t = ObjectType(ObjectIdentity(oid_str))

    # Create 100 queries using optimized PDU composition
    wrapped_queries = [ObjectType(ObjectIdentity(oid_str)) for _ in range(100)]
    wrapped_queries = cluster_varbinds(wrapped_queries, max_per_pdu=10)

    start = time.time()
    for error_ind, error_status, error_index, var_binds in parallel_get_sync(
        dispatcher,
        auth_data,
        transport,
        queries=wrapped_queries
    ):
        if error_ind:
            print(f"SNMP error: {error_ind}")
            quit()
        elif error_status:
            print(f'{error_status.prettyPrint()} at {error_index and var_binds[int(error_index) - 1][0] or "?"}')
            quit()
        else:
            for oid, val in var_binds:
                print(val.prettyPrint())

    print(f"--- {time.time() - start:.3f} seconds ---")

if __name__ == '__main__':
    main()

# --- 0.410 seconds ---
# --- 0.424 seconds ---
# --- 0.360 seconds ---
# --- 0.423 seconds ---
```

### Usage of the oneliner package, being deprecated in newer versions of pysnmp

```python
# Usage of the oneliner package, being deprecated in newer versions of pysnmp

# pip uninstall pysnmp
# pip uninstall pysnmplib
# pip install pysnmp==5.1.0
# pip install pyasn1==0.4.8

import platform
import time
import sys
from pysnmp.entity.rfc3413.oneliner import cmdgen

if len(sys.argv) < 2:
    print("Usage: python script.py <hostname>")
    sys.exit(1)

host = sys.argv[1]

# Create these objects outside the loop for better performance
cmd_gen = cmdgen.CommandGenerator()
transport = cmdgen.UdpTransportTarget((host, 161), timeout=5, retries=1)
oid = '1.3.6.1.2.1.25.3.2.1.3.1'
oid_tuple = tuple(int(part) for part in oid.split('.'))
comm_data = cmdgen.CommunityData('public', mpModel=0)

start_time = time.time()

for i in range(100):
    # Execute the command directly in the loop for better performance
    error_indication, error_status, error_index, var_binds = cmd_gen.getCmd(
        comm_data,
        transport,
        oid_tuple
    )
    
    if error_indication:
        print(f"Error: {error_indication}")
    elif error_status:
        print(f"{error_status.prettyPrint()} at {error_index}")
    elif len(var_binds) != 1:
        print(f"varBinds error: {len(var_binds)}")
    else:
        print(var_binds[0][1])

print("--- %s seconds ---" % (time.time() - start_time))

# --- 1.1897211074829102 seconds ---
# --- 1.0130093097686768 seconds ---
```

### Raw Python implementation of the SNMPv1 protocol

```python
# Pure Python implementation of the SNMPv1 basic GetRequest/GetResponse
# protocol with the sole usage of the default socket library.

# Code Complexity: Very High
# Performance: excellent
# Protocol Compliance: manual
# Maintenance: Error-Prone

import socket
import time
import sys

def encode_length(length):
    if length < 0x80:
        return bytes([length])
    else:
        num_bytes = (length.bit_length() + 7) // 8
        encoded = []
        for _ in range(num_bytes):
            encoded.append(length & 0xff)
            length >>= 8
        encoded = bytes(encoded[::-1])
        return bytes([0x80 | num_bytes]) + encoded

def encode_base128(n):
    if n == 0:
        return bytes([0])
    bytes_list = []
    while n > 0:
        bytes_list.insert(0, n & 0x7f)
        n >>= 7
    for i in range(len(bytes_list) - 1):
        bytes_list[i] |= 0x80
    return bytes(bytes_list)

def encode_oid(oid_str):
    parts = list(map(int, oid_str.split('.')))
    if len(parts) < 2:
        raise ValueError("OID must have at least two components")
    first = parts[0] * 40 + parts[1]
    encoded = bytes([first])
    for n in parts[2:]:
        encoded += encode_base128(n)
    return b'\x06' + encode_length(len(encoded)) + encoded

def encode_integer(value):
    if value == 0:
        return b'\x02\x01\x00'
    byte_count = (value.bit_length() + 7) // 8
    bytes_val = value.to_bytes(byte_count, 'big', signed=False)
    return b'\x02' + encode_length(len(bytes_val)) + bytes_val

def construct_snmp_get_request(oid, community='public', request_id=1):
    version = b'\x02\x01\x00'
    community_enc = b'\x04' + encode_length(len(community)) + community.encode()
    oid_enc = encode_oid(oid)
    null = b'\x05\x00'
    var_bind = b'\x30' + encode_length(len(oid_enc) + len(null)) + oid_enc + null
    var_bindings = b'\x30' + encode_length(len(var_bind)) + var_bind
    pdu_content = (
        encode_integer(request_id) +
        encode_integer(0) +
        encode_integer(0) +
        var_bindings
    )
    pdu = b'\xa0' + encode_length(len(pdu_content)) + pdu_content
    snmp_message = (
        b'\x30'
        + encode_length(len(version) + len(community_enc) + len(pdu))
        + version
        + community_enc
        + pdu
    )
    return snmp_message

def parse_snmp_response(data):
    def parse_length(data, index):
        length_byte = data[index]
        index += 1
        if length_byte < 0x80:
            return (length_byte, index)
        else:
            num_bytes = length_byte & 0x7f
            length = 0
            for _ in range(num_bytes):
                length = (length << 8) | data[index]
                index += 1
            return (length, index)
    
    index = 0
    if data[index] != 0x30:
        raise ValueError("Expected SEQUENCE")
    index += 1
    length, index = parse_length(data, index)
    if data[index] != 0x02:
        raise ValueError("Expected version INTEGER")
    index += 1
    version_length, index = parse_length(data, index)
    index += version_length
    if data[index] != 0x04:
        raise ValueError("Expected community OCTET STRING")
    index += 1
    community_length, index = parse_length(data, index)
    index += community_length
    if data[index] != 0xa2:
        raise ValueError("Expected GetResponse PDU")
    index += 1
    pdu_length, index = parse_length(data, index)
    pdu_data = data[index:index+pdu_length]
    index += pdu_length
    pdu_index = 0
    if pdu_data[pdu_index] != 0x02:
        raise ValueError("Expected request-id INTEGER")
    pdu_index += 1
    req_id_len, pdu_index = parse_length(pdu_data, pdu_index)
    pdu_index += req_id_len
    if pdu_data[pdu_index] != 0x02:
        raise ValueError("Expected error-status INTEGER")
    pdu_index += 1
    err_status_len, pdu_index = parse_length(pdu_data, pdu_index)
    pdu_index += err_status_len
    if pdu_data[pdu_index] != 0x02:
        raise ValueError("Expected error-index INTEGER")
    pdu_index += 1
    err_index_len, pdu_index = parse_length(pdu_data, pdu_index)
    pdu_index += err_index_len
    if pdu_data[pdu_index] != 0x30:
        raise ValueError("Expected variable-bindings SEQUENCE")
    pdu_index += 1
    var_bindings_len, pdu_index = parse_length(pdu_data, pdu_index)
    var_bindings = pdu_data[pdu_index:pdu_index+var_bindings_len]
    pdu_index += var_bindings_len
    var_index = 0
    if var_bindings[var_index] != 0x30:
        raise ValueError("Expected variable-binding entry SEQUENCE")
    var_index += 1
    entry_len, var_index = parse_length(var_bindings, var_index)
    entry_data = var_bindings[var_index:var_index+entry_len]
    var_index += entry_len
    entry_idx = 0
    if entry_data[entry_idx] != 0x06:
        raise ValueError("Expected OID")
    entry_idx += 1
    oid_len, entry_idx = parse_length(entry_data, entry_idx)
    entry_idx += oid_len
    value_tag = entry_data[entry_idx]
    entry_idx += 1
    value_len, entry_idx = parse_length(entry_data, entry_idx)
    value_bytes = entry_data[entry_idx:entry_idx+value_len]
    if value_tag == 0x04:
        return value_bytes.decode()
    elif value_tag == 0x02:
        return int.from_bytes(value_bytes, 'big', signed=True)
    else:
        return value_bytes

def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py <hostname>")
        sys.exit(1)
    host = sys.argv[1]
    oid = '1.3.6.1.2.1.25.3.2.1.3.1'
    request_id = 1
    start_time = time.time()
    for _ in range(100):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)
        request = construct_snmp_get_request(oid, 'public', request_id)
        try:
            sock.sendto(request, (host, 161))
            response, _ = sock.recvfrom(65536)
            value = parse_snmp_response(response)
            print(value)
        except Exception as e:
            print(f"Error: {e}")
        finally:
            sock.close()
        request_id += 1
    print("--- %s seconds ---" % (time.time() - start_time))

def main_performance():
    if len(sys.argv) < 2:
        print("Usage: python script.py <hostname>")
        sys.exit(1)
        
    host = sys.argv[1]
    oid = '1.3.6.1.2.1.25.3.2.1.3.1'
    request_id = 1
    start_time = time.time()

    # Create socket once and reuse it
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1)  # Timeout applies to all operations

    try:
        for _ in range(100):
            request = construct_snmp_get_request(oid, 'public', request_id)
            try:
                # Send and receive using the same socket
                sock.sendto(request, (host, 161))
                response, _ = sock.recvfrom(65536)
                value = parse_snmp_response(response)
                print(value)
            except socket.timeout:
                print("Error: Request timed out")
            except Exception as e:
                print(f"Error: {e}")
            finally:
                request_id += 1
    finally:
        sock.close()  # Close socket once at the end

    print("--- %s seconds ---" % (time.time() - start_time))

if __name__ == '__main__':
    main_performance()
    # --- 0.7888898849487305 seconds ---
    # --- 0.7544982433319092 seconds ---
    # --- 0.7131996154785156 seconds ---
```

### Pure python implementation using the asn1 and the default socket libraries.

```python
# Pure python implementation using the asn1 and the default socket libraries.

# pip install asn1

# Code Complexity: low
# Performance: excellent
# Protocol Compliance: decent
# Maintenance: decent

import socket
import time
import sys
import logging
import asn1

def main_performance():
    if len(sys.argv) < 2:
        print("Usage: python script.py <hostname>")
        sys.exit(1)
        
    host = sys.argv[1]
    oid = '1.3.6.1.2.1.25.3.2.1.3.1'
    request_id = 1
    start_time = time.time()

    # Create and reuse the socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1)

    try:
        for _ in range(100):
            # Encode the SNMP GetRequest using asn1 library
            encoder = asn1.Encoder()
            encoder.start()
            
            # Main SNMP message sequence
            encoder.enter(asn1.Numbers.Sequence)
            encoder.write(0, asn1.Numbers.Integer)  # SNMP version 0 (v1)
            encoder.write(b'public', asn1.Numbers.OctetString)  # community

            # GetRequest PDU (context-specific tag 0)
            encoder.enter(0, cls=asn1.Classes.Context)  # Generate 0xA0
            encoder.write(request_id, asn1.Numbers.Integer)
            encoder.write(0, asn1.Numbers.Integer)  # error-status
            encoder.write(0, asn1.Numbers.Integer)  # error-index
            
            # Variable bindings sequence
            encoder.enter(asn1.Numbers.Sequence)
            encoder.enter(asn1.Numbers.Sequence)  # Single var-bind
            encoder.write(oid, asn1.Numbers.ObjectIdentifier)  # OID
            encoder.write(None, asn1.Numbers.Null)  # Null value
            encoder.leave()  # Exit var-bind
            encoder.leave()  # Exit variable bindings
            
            encoder.leave()  # Exit PDU
            encoder.leave()  # Exit main sequence
            
            request = encoder.output()
            logging.debug("REQ: %s", request.hex(' '))

            # Send request
            sock.sendto(request, (host, 161))
            
            try:
                # Receive and decode response
                response, _ = sock.recvfrom(65536)
                logging.debug("RES: %s", response.hex(' '))
                decoder = asn1.Decoder()
                decoder.start(response)
                #_, value = decoder.read(); print("DECODED", value); continue

                # Decode top-level sequence
                decoder.enter()
                _, version = decoder.read()
                _, community = decoder.read()
                
                # Verify GetResponse PDU (context-specific tag 2)
                tag = decoder.peek()
                if tag.cls != asn1.Classes.Context or tag.nr != 2:  # if decoder.peek().nr != 0xA2:
                    raise ValueError("Expected GetResponse PDU")
                decoder.enter()  # Enter PDU content
                
                # Read response fields
                _, resp_id = decoder.read()
                _, error_status = decoder.read()
                _, error_index = decoder.read()
                logging.debug(
                    "version: %s, community: %s, resp_id: %s,"
                    " error_status: %s, error_index: %s",
                    version, community, resp_id, error_status, error_index
                )
                
                # Process variable bindings
                decoder.enter()
                decoder.enter()  # var-bind sequence
                _, resp_oid = decoder.read()
                value_type, value = decoder.read()
                
                # Handle different value types
                if value_type == asn1.Numbers.OctetString:
                    decoded_value = value.decode('utf-8')
                elif value_type == asn1.Numbers.Integer:
                    decoded_value = value
                else:
                    decoded_value = value  # Fallback to raw bytes
                
                print("decoded_value:", decoded_value)
                
            except (asn1.Error, ValueError) as e:
                print(f"Decoding error: {e}")

            request_id += 1

    finally:
        sock.close()

    print(f"--- {time.time() - start_time} seconds ---")

if __name__ == '__main__':
    main_performance()

# --- 1.0287363529205322 seconds ---
# --- 0.937241792678833 seconds ---
# --- 1.0431180000305176 seconds ---
```

### https://github.com/Ircama/py-snmp-sync over PySNMP.

```python
# pip uninstall pysnmplib
# pip install py-snmp-sync

import sys
import time
from py_snmp_sync import (
    SyncUdpTransportTarget, sync_get_cmd, ObjectIdentity, CommunityData
)

def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py <host>")
        sys.exit(1)

    host = sys.argv[1]
    oid_str = '1.3.6.1.2.1.25.3.2.1.3.1'
    community = 'public'

    # Pre-create the transport once
    target = SyncUdpTransportTarget((host, 161))

    # Pre-create oid and CommunityData once
    auth_data = CommunityData(community, mpModel=0)
    oid = ObjectIdentity(oid_str)

    start = time.time()
    for _ in range(100):
        try:
            error_ind, error_status, error_index, var_binds = sync_get_cmd(
                CommunityData("public", mpModel=0),
                target,
                oid
            )
            if error_ind:
                raise RuntimeError(f"SNMP error: {error_ind}")
            elif error_status:
                raise RuntimeError(
                    f'{error_status.prettyPrint()} at {error_index and var_binds[int(error_index) - 1][0] or "?"}'
                )
            else:
                for _, val in var_binds:
                    print(val.prettyPrint())
        except Exception as e:
            print("Request failed:", e)

    print(f"--- {time.time() - start:.3f} seconds ---")

if __name__ == '__main__':
    main()

# --- 1.125 seconds ---
# --- 1.197 seconds ---
# --- 1.145 seconds ---
```

--------------------------------------------------------------------------------

## EPSON SNMP Protocol analysis

The EPSON printer uses **SNMPv1** with basic read-only community string authentication and no security features. It implements standard and proprietary MIBs.

- Simple Network Management Protocol Version 1.
- No encryption (SNMPv1 has no security beyond community strings).
- Community string: `public` sent in cleartext (default for read-only access in SNMPv1).
- UDP port 161 (defaultfor SNMP agents). Connectionless, lightweight communication.

### Full decoding of the SNMP request

Full decoding of the SNMP request for the OID `1.3.6.1.2.1.25.3.2.1.3.1`.

#### Raw Bytes of the Request (hex):

```
30 29 02 01 00 04 06
70 75 62 6c 69 63                                       [Public]
a0 1c 02 01 26 02 01 00 02 01 00 30 11 30 0f 06 0b
2b 06 01 02 01 19 03 02 01 03 01                        [1.3.6.1.2.1.25.3.2.1.3.1]
05 00

0)  30 29
2)  02 01 00
5)  04 06 70 75 62 6c 69 63                             [Public]
11) a0 1c
13) 02 01 26
16) 02 01 00
19) 02 01 00
22) 30 11
24) 30 0f
26) 06 0b 2b 06 01 02 01 19 03 02 01 03 01              [1.3.6.1.2.1.25.3.2.1.3.1]
39) 05 00
```

String                    |Hex representation
--------------------------|-----------------------------------
Public                    | 70 75 62 6c 69 63
1.3.6.1.2.1.25.3.2.1.3.1  | 2b 06 01 02 01 19 03 02 01 03 01

SNMPv1 PDU Tags:
- 0xA0: GetRequest
- 0xA1: GetNextRequest
- 0xA2: GetResponse
- 0xA3: SetRequest
- 0xA4: Trap

```
SNMP Message (SEQUENCE, 41 bytes)
├─ Version (INTEGER): 0 (SNMPv1)
├─ Community (OCTET STRING): "public"
└─ GetRequest-PDU (0xA0, 28 bytes = 0x1C)
   ├─ Request-ID (INTEGER): 38 (0x26)
   ├─ Error-Status (INTEGER): 0 (noError)
   ├─ Error-Index (INTEGER): 0
   └─ Variable-Bindings (SEQUENCE, 17 bytes = 0x11)
      └─ VarBind (SEQUENCE, 15 bytes = 0x0f)
         ├─ OID (OBJECT IDENTIFIER): 1.3.6.1.2.1.25.3.2.1.3.1
         └─ Value (NULL) (no value)
```

#### Request Breakdown (SNMPv1 Structure):

1. **SNMP Message (SEQUENCE)**: `30 29`  
   - Tag: `0x30` (SEQUENCE)  
   - Length: `0x29` (41 bytes total for the entire message).

2. **SNMP Version (INTEGER)**: `02 01 00`  
   - Tag: `0x02` (INTEGER)  
   - Length: `0x01` (1 byte)  
   - Value: `0x00` (SNMPv1).

3. **Community String (OCTET STRING)**: `04 06 70 75 62 6c 69 63`  
   - Tag: `0x04` (OCTET STRING)  
   - Length: `0x06` (6 bytes)  
   - Value: `70 75 62 6c 69 63` ("public" in ASCII).

4. **GetRequest-PDU**: `a0 1c`  
   - Tag: `0xA0` (SNMPv1 GetRequest)  
   - Length: `0x1C` (28 bytes for the PDU contents).

5. **Request-ID (INTEGER)**: `02 01 26`  
   - Tag: `0x02` (INTEGER)  
   - Length: `0x01` (1 byte)  
   - Value: `0x26` (request ID = 38).

6. **Error-Status (INTEGER)**: `02 01 00`  
   - Tag: `0x02` (INTEGER)  
   - Length: `0x01` (1 byte)  
   - Value: `0x00` (noError).

7. **Error-Index (INTEGER)**: `02 01 00`  
   - Tag: `0x02` (INTEGER)  
   - Length: `0x01` (1 byte)  
   - Value: `0x00` (no error index).

8. **Variable-Bindings (SEQUENCE)**: `30 11`  
   - Tag: `0x30` (SEQUENCE)  
   - Length: `0x11` (17 bytes).

    - **VarBind Entry (SEQUENCE)**: `30 0f`  
      - Tag: `0x30` (SEQUENCE)  
      - Length: `0x0f` (15 bytes).

        - **OID (OBJECT IDENTIFIER)**: `06 0b 2b 06 01 02 01 19 03 02 01 03 01`  
          - Tag: `0x06` (OID)  
          - Length: `0x0B` (11 bytes)  
          - Encoded OID: `2b 06 01 02 01 19 03 02 01 03 01`  
            - Decoded: `1.3.6.1.2.1.25.3.2.1.3.1` (matches your target OID).

        - **Value (NULL)**: `05 00`  
          - Tag: `0x05` (NULL)  
          - Length: `0x00` (no value).

### Full decoding of the SNMPv1 response

Full decoding of the SNMP response for the OID `1.3.6.1.2.1.25.3.2.1.3.1` returning `EPSON XP-205 207 Series`.

#### Raw Bytes of the Response (hex):

```plaintext
30 40 02 01 00 04 06
70 75 62 6c 69 63                                                       [Public]
a2 33 02 01 01 02 01 00 02 01 00 30 28 30 26 06 0b
2b 06 01 02 01 19 03 02 01 03 01                                        [1.3.6.1.2.1.25.3.2.1.3.1], 11 bytes
04 17
45 50 53 4f 4e 20 58 50 2d 32 30 35 20 32 30 37 20 53 65 72 69 65 73    [EPSON XP-205 207 Series], 23 bytes

0)  30 40
2)  02 01 00
5)  04 06 70 75 62 6c 69 63                                             [Public]
13) a2 33
15) 02 01 01
18) 02 01 00
21) 02 01 00
24) 30 28
26) 30 26
28) 06 0b 2b 06 01 02 01 19 03 02 01 03 01                              [1.3.6.1.2.1.25.3.2.1.3.1], 13 bytes
41) 04 17 45 50 53 4f 4e 20 58 50 2d 32 30 35 20 32 30 37 20 53 65 72 69 65 73    [EPSON XP-205 207 Series], 25 bytes
```

String                    |Hex representation
--------------------------|-----------------------------------
Public                    | 70 75 62 6c 69 63
1.3.6.1.2.1.25.3.2.1.3.1  | 2b 06 01 02 01 19 03 02 01 03 01
EPSON XP-205 207 Series   | 45 50 53 4f 4e 20 58 50 2d 32 30 35 20 32 30 37 20 53 65 72 69 65 73

SNMPv1 PDU Tags:
- 0xA0: GetRequest
- 0xA1: GetNextRequest
- 0xA2: GetResponse
- 0xA3: SetRequest
- 0xA4: Trap

```
SNMP Message (SEQUENCE, 64 bytes)
├─ Version (INTEGER): 0 (SNMPv1)
├─ Community (OCTET STRING): "public"
└─ GetResponse-PDU (0xA2, 51 bytes)
   ├─ Request-ID (INTEGER): 100
   ├─ Error-Status (INTEGER): 0 (noError)
   ├─ Error-Index (INTEGER): 0
   └─ Variable-Bindings (SEQUENCE, 40 bytes = 0x28)
      └─ VarBind (SEQUENCE, 38 bytes = 0x26)
         ├─ OID (OBJECT IDENTIFIER): 1.3.6.1.2.1.25.3.2.1.3.1
         └─ Value (OCTET STRING): "EPSON XP-205 207 Series"
```

#### Response Breakdown (SNMPv1 Structure):

1. **SNMP Message Header**:
   - **Tag**: `0x30` (SEQUENCE)
   - **Length**: `0x40` (64 bytes total)

2. **SNMP Version**:
   - **Tag**: `0x02` (INTEGER)
   - **Length**: `0x01` (1 byte)
   - **Value**: `0x00` → SNMPv1

3. **Community String**:
   - **Tag**: `0x04` (OCTET STRING)
   - **Length**: `0x06` (6 bytes)
   - **Value**: `70 75 62 6c 69 63` → "public"

4. **GetResponse-PDU**:
   - **Tag**: `0xA2` (SNMPv1 GetResponse)
   - **Length**: `0x33` (51 bytes)

5. **Request-ID**:
   - **Tag**: `0x02` (INTEGER)
   - **Length**: `0x01` (1 byte)
   - **Value**: `0x01` → 1

6. **Error-Status**:
   - **Tag**: `0x02` (INTEGER)
   - **Length**: `0x01` (1 byte)
   - **Value**: `0x00` → noError

7. **Error-Index**:
   - **Tag**: `0x02` (INTEGER)
   - **Length**: `0x01` (1 byte)
   - **Value**: `0x00` → no error index

8. **Variable-Bindings**:
   - **Tag**: `0x30` (SEQUENCE)
   - **Length**: `0x28` (40 bytes)
   - **VarBind Entry**:
     - **Tag**: `0x30` (SEQUENCE)
     - **Length**: `0x26` (38 bytes)
     - **OID**:
       - **Tag**: `0x06` (OBJECT IDENTIFIER)
       - **Length**: `0x0B` (11 bytes)
       - **Encoded OID**: `2B 06 01 02 01 19 03 02 01 03 01`
         - Decoded: `1.3.6.1.2.1.25.3.2.1.3.1`
     - **Value**:
       - **Tag**: `0x04` (OCTET STRING)
       - **Length**: `0x17` (23 bytes)
       - **Value**: `45 50 53 4F 4E 20 58 50 2D 32 30 35 20 32 30 37 20 53 65 72 69 65 73` → "EPSON XP-205 207 Series"

#### sysName

The OID `1.3.6.1.2.1.25.3.2.1.3.1` is part of the **Host Resources MIB** (`HOST-RESOURCES-MIB`), defined in RFC 2790 and returns the sysName.

Here's the breakdown:

```
1.3.6.1.2.1.25.3.2.1.3.1
│ │ │ │ │ │ │  │ │ │ │ └─ sysName, index of the hrDevice entry (1st device)
│ │ │ │ │ │ │  │ │ │ └─── hrDeviceDescr 
│ │ │ │ │ │ │  │ │ └───── hrDeviceEntry
│ │ │ │ │ │ │  │ └─────── hrDeviceTable
│ │ │ │ │ │ │  └───────── hrDevice
│ │ │ │ │ │ └──────────── host, hostResourcesMibModule
│ │ │ │ │ └────────────── mib-2, mib mgmt
│ │ │ │ └──────────────── Mgmt
│ │ │ └────────────────── Internet
│ │ └──────────────────── DOD
│ └────────────────────── identified-organization, org, iso-identified-organization
└──────────────────────── ISO
```

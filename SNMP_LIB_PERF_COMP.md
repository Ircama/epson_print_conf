# Benchmarking Python SNMP Libraries for Epson Printer Communication

This document compares pure Python SNMP libraries, with the goal of performing unauthenticated, sequential SNMPv1 queries to a single Epson printer.

We aim to use libraries implemented entirely in Python to avoid the complexity and overhead of wrappers around native libraries, while maintaining acceptable performance.

For our use case, that is interfacing with Epson printers, synchronous SNMP simplifies development and maintenance without compromising performance.

We compared:

- Ilya Etingof’s [etingof/pysnmp](https://github.com/etingof/pysnmp) project (unmaintained) in synchronous mode,
- [pysnmplib](https://github.com/pysnmp/pysnmp) in synchronous mode,
- [lextudio](https://github.com/lextudio/pysnmp/) v5.1 synchronous mode,
- [lextudio](https://github.com/lextudio/pysnmp/) v7.1 asynchronous mode,
- raw socket SNMPv1 implementation (synchronous mode).

To compare implementations, we developed a trivial benchmark that performs 100 SNMPv1 GET requests of the same OID to the same printer, measuring total execution time. We used OID `1.3.6.1.2.1.25.3.2.1.3.1` (`sysName`).

Benchmark results show that older libraries with reduced abstraction layers tend to offer better performance and simpler, more readable code with fewer lines: the legacy synchronous backend `pysnmp.hlapi.v1arch` from [etingof/pysnmp](https://github.com/etingof/pysnmp) performs on par with the most efficient asynchronous implementation. In contrast, newer versions such as `pysnmp.hlapi` from [pysnmplib](https://github.com/pysnmp/pysnmp) or `pysnmp==5.1.0` from [lextudio](https://docs.lextudio.com/snmp/) introduce approximately 40% performance overhead compared to `v1arch`.

In our current codebase, we use the unmaintained `etingof/pysnmp`, specifically the `v1arch` synchronous mode, which performs well due to:

* A streamlined architecture (e.g., no SNMP engine instantiation per request)
* Minimal overhead in request dispatch

However, `etingof/pysnmp` is not available on PyPI. To support PyPI installation, we would need to switch to a newer version such as `pysnmp` or `pysnmplib`.

Older versions of `pysnmp` supported both synchronous and asynchronous modes. However, recent versions have removed synchronous support, leaving only asynchronous interfaces. This evolution mirrors broader industry tensions between legacy compatibility and modern performance demands. While `pysnmp` v7+'s async-only architecture theoretically enables better resource utilization, it imposes significant refactoring costs for traditional SNMPv1 workflows.

The most suboptimal implementation strategy for sequential SNMPv1 operations involves forcibly adapting asynchronous pysnmp architectures to synchronous workflows through repeated asyncio.run() invocations. This anti-pattern incurs catastrophic performance degradation due to fundamental resource management failures:

- Event loop thrashing due to each iteration, that recreates and destroys the entire asyncio infrastructure; calling `asyncio.run()` 100 times results in excessive overhead, as each iteration initializes and tears down the event loop.
- Protocol engine reinitialization, where essential SNMP components get recreated per-request, like `SnmpDispatcher()`.
- Concurrency opportunity cost, that forces sequential execution despite async capabilities: sequential use of async code negates the benefits of concurrency and parallelism.

The evaluations reported below reveal a stark contrast between implementation strategies using `pysnmp 7.1`. The simulated synchronous approach (artificially forcing async-to-sync behavior through sequential `asyncio.run()` calls) required 13.5-13.8 seconds for 100 requests. By comparison, a native asynchronous implementation using identical library versions completed the same workload in 0.47-0.49 seconds, demonstrating a 28× throughput improvement.

This performance disparity comes with significant architectural consequences, as the examples can show.

## Code used for the benchmarks

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
# pip uninstall pysnmplib
# pip install pyasn1==0.4.8

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

### Usage of https://github.com/lextudio/pysnmp 7.1 simulating sync behaviour

```python
# Usage of https://github.com/lextudio/pysnmp 7.1
# Simulate sync behaviour in an extremely inefficient and slow mode

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
# Same as mytest4, but single ObjectType in get_cmd

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
# Max performance (same as mytest3, but multiple ObjectType in get_cmd)

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

### Raw Python implementation of the SNMPv protocol

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

## EPSON SNMP Protocol analysis

The EPSON printer uses **SNMPv1** with basic read-only community string authentication and no security features. It implements standard and proprietary MIBs.

- Simple Network Management Protocol Version 1.
- No encryption (SNMPv1 has no security beyond community strings).
- Community string: `public` sent in cleartext (default for read-only access in SNMPv1).
- UDP port 161 (defaultfor SNMP agents). Connectionless, lightweight communication.

### Full decoding of the SNMP request

Full decoding of the SNMP request for the OID `1.3.6.1.2.1.25.3.2.1.3.1`.

#### Raw Bytes (hex):

```
0)  30 29
2)  02 01 00
5)  04 06 70 75 62 6c 69 63
11) a0 1c
13) 02 01 26
16) 02 01 00
19) 02 01 00
22) 30 11
24) 30 0d
26) 06 0b 2b 06 01 02 01 19 03 02 01 03 01
39) 05 00
```

#### Breakdown (SNMPv1 Structure):

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

    - **VarBind Entry (SEQUENCE)**: `30 0d`  
      - Tag: `0x30` (SEQUENCE)  
      - Length: `0x0D` (13 bytes).

      - **OID (OBJECT IDENTIFIER)**: `06 0b 2b 06 01 02 01 19 03 02 01 03 01`  
        - Tag: `0x06` (OID)  
        - Length: `0x0B` (11 bytes)  
        - Encoded OID: `2b 06 01 02 01 19 03 02 01 03 01`  
          - Decoded: `1.3.6.1.2.1.25.3.2.1.3.1` (matches your target OID).

      - **Value (NULL)**: `05 00`  
        - Tag: `0x05` (NULL)  
        - Length: `0x00` (no value).

### Full decoding of the SNMPv1 response

```plaintext
SNMP Message (SEQUENCE, 64 bytes)
├─ Version (INTEGER): 0 (SNMPv1)
├─ Community (OCTET STRING): "public"
└─ GetResponse-PDU (0xA2, 51 bytes)
   ├─ Request-ID (INTEGER): 100
   ├─ Error-Status (INTEGER): 0 (noError)
   ├─ Error-Index (INTEGER): 0
   └─ Variable-Bindings (SEQUENCE, 40 bytes)
      └─ VarBind (SEQUENCE, 38 bytes)
         ├─ OID (OBJECT IDENTIFIER): 1.3.6.1.2.1.25.3.2.1.3.1
         └─ Value (OCTET STRING): "EPSON XP-205 207 Series"
```

#### Step-by-Step Breakdown:

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
   - **Value**: `0x64` → 100

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

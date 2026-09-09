import logging
import os
import socket
import subprocess
import threading
import warnings

from epson_print_conf import EpsonPrinter

# suppress pysnmp warnings
warnings.filterwarnings("ignore", category=SyntaxWarning)

# common printer ports
PRINTER_PORTS = [9100, 515, 631]


def _get_local_ips():
    """
    Return the list of local IP addresses of the active network interfaces.

    socket.gethostbyname_ex(socket.gethostname()) fails on Debian/Ubuntu
    hosts, where /etc/hosts maps the system hostname to 127.0.1.1: in that
    case only the loopback address is returned and the subnet scan never
    visits any reachable IP. To cope with this, query the kernel routing
    table via a UDP socket connection to a public address (RFC 1918
    documentation address; no packet is actually sent by connect() on a
    UDP socket). Fall back to gethostbyname_ex() when the routing trick
    does not work (e.g., no route or no DNS resolution available).
    """
    ips = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 1))  # no data is sent (UDP)
            primary_ip = sock.getsockname()[0]
        if primary_ip and not primary_ip.startswith("127."):
            ips.append(primary_ip)
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    return ips


class PrinterScanner:

    def check_printer(self, ip, port):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            sock.connect((ip, port))
            sock.close()
            return True
        except socket.error:
            return False

    def get_printer_name(self, ip):
        printer = EpsonPrinter(hostname=ip)
        try:
            printer_info = printer.get_snmp_info("Model")
            return printer_info["Model"]
        except:
            return None

    def scan_ip(self, ip):
        for port in PRINTER_PORTS:
            if self.check_printer(ip, port):
                try:
                    hostname = socket.gethostbyaddr(ip)[0]
                except socket.herror:
                    hostname = "Unknown"

                return {
                    "ip": ip,
                    "hostname": hostname,
                }
        return None

    def get_all_printers(self, ip_addr="", local=False):
        if ip_addr:
            result = self.scan_ip(ip_addr)
            if result:
                result["name"] = self.get_printer_name(result['ip'])
                return [result]
        local_device_ip_list = _get_local_ips()
        if local:
            return local_device_ip_list  # IP list
        if not local_device_ip_list:
            logging.error("Cannot determine any local IP address; "
                          "specify the printer IP address explicitly.")
            return []
        printers = []
        for local_device_ip in local_device_ip_list:
            if ip_addr and not local_device_ip.startswith(ip_addr):
                continue
            base_ip = local_device_ip[:local_device_ip.rfind('.') + 1]
            ips=[f"{base_ip}{i}" for i in range(1, 255)]
            threads = []

            def worker(ip):
                result = self.scan_ip(ip)
                if result:
                    printers.append(result)

            for ip in ips:
                thread = threading.Thread(target=worker, args=(ip,))
                threads.append(thread)
                thread.start()

            for thread in threads:
                thread.join()

        for i in printers:
            i["name"] = self.get_printer_name(i['ip'])
        return printers


if __name__ == "__main__":
    import sys
    ip = ""
    if len(sys.argv) > 1:
        ip = sys.argv[1]
    scanner = PrinterScanner()
    print(scanner.get_all_printers(ip))

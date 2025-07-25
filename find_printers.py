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
        local_device_ip_list = socket.gethostbyname_ex(socket.gethostname())[2]
        if local:
            return local_device_ip_list  # IP list
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

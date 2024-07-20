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

    def ping(self, host):
        result = subprocess.run(['ping', '-n', '1', host], stdout=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        return 'Reply from' in result.stdout.decode('utf-8')

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
        if self.ping(ip):
            for port in PRINTER_PORTS:
                if self.check_printer(ip, port):
                    try:
                        hostname = socket.gethostbyaddr(ip)[0]
                    except socket.herror:
                        hostname = "Unknown"

                    printer_name = self.get_printer_name(ip)
                    if printer_name:
                        return {"ip": ip, "hostname": hostname, "name": printer_name}
                    else:
                        return {"ip": ip, "hostname": hostname, "name": "Unknown"}
        return None
    def get_all_printers(self):
        local_device_ip_list = socket.gethostbyname_ex(socket.gethostname())[2]
        for local_device_ip in local_device_ip_list:
            base_ip = local_device_ip[:local_device_ip.rfind('.') + 1]
            ips=[f"{base_ip}{i}" for i in range(1, 255)]
            printers = []
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

        return printers


if __name__ == "__main__":
    scanner = PrinterScanner()
    print(scanner.get_all_printers())

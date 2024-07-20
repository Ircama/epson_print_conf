import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
import threading
import ipaddress
from epson_print_conf import EpsonPrinter
from find_printers import PrinterScanner
from pprint import pformat

class EpsonPrinterUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Epson Printer Configuration")
        self.geometry("450x400")
        
        # configure the main window to be resizable
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        
        # main Frame
        main_frame = ttk.Frame(self, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)
        
        # printer model selection
        model_frame = ttk.LabelFrame(main_frame, text="Printer Model", padding="10")
        model_frame.grid(row=0, column=0, pady=10, sticky=(tk.W, tk.E))
        model_frame.columnconfigure(1, weight=1)
        
        self.model_var = tk.StringVar()
        ttk.Label(model_frame, text="Select Printer Model:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.model_dropdown = ttk.Combobox(model_frame, textvariable=self.model_var)
        self.model_dropdown['values'] = sorted(list(EpsonPrinter.PRINTER_CONFIG.keys()))
        self.model_dropdown.grid(row=0, column=1, pady=5, padx=5, sticky=(tk.W, tk.E))
        
        # IP address entry
        ip_frame = ttk.LabelFrame(main_frame, text="Printer IP Address", padding="10")
        ip_frame.grid(row=1, column=0, pady=10, sticky=(tk.W, tk.E))
        ip_frame.columnconfigure(1, weight=1)
        
        self.ip_var = tk.StringVar()
        ttk.Label(ip_frame, text="Enter Printer IP Address:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.ip_entry = ttk.Entry(ip_frame, textvariable=self.ip_var)
        self.ip_entry.grid(row=0, column=1, pady=5, padx=5, sticky=(tk.W, tk.E))
        
        # buttons
        button_frame = ttk.Frame(main_frame, padding="10")
        button_frame.grid(row=2, column=0, pady=10, sticky=(tk.W, tk.E))
        button_frame.columnconfigure((0, 1, 2), weight=1)
        
        self.detect_button = ttk.Button(button_frame, text="Detect Printers", command=self.start_detect_printers)
        self.detect_button.grid(row=0, column=0, padx=5, pady=5, sticky=(tk.W, tk.E))
        
        self.status_button = ttk.Button(button_frame, text="Print Status", command=self.print_status)
        self.status_button.grid(row=0, column=1, padx=5, pady=5, sticky=(tk.W, tk.E))
        
        self.reset_button = ttk.Button(button_frame, text="Reset Waste Ink Levels", command=self.reset_waste_ink)
        self.reset_button.grid(row=0, column=2, padx=5, pady=5, sticky=(tk.W, tk.E))
        
        # status display
        status_frame = ttk.LabelFrame(main_frame, text="Status", padding="10")
        status_frame.grid(row=3, column=0, pady=10, sticky=(tk.W, tk.E, tk.N, tk.S))
        status_frame.columnconfigure(0, weight=1)
        status_frame.rowconfigure(0, weight=1)
        
        self.status_text = ScrolledText(status_frame, height=10, width=50, wrap=tk.WORD)
        self.status_text.grid(row=0, column=0, pady=5, padx=5, sticky=(tk.W, tk.E, tk.N, tk.S))
    
    def print_status(self):
        model = self.model_var.get()
        ip_address = self.ip_var.get()
        if not model or not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, "[ERROR] Please select a printer model and enter a valid IP address.\n")
            return
        printer = EpsonPrinter(model=model, hostname=ip_address)

        try:
            self.status_text.insert(tk.END, f"[INFO] {pformat(printer.stats())}\n")
        except Exception as e:
            self.status_text.insert(tk.END, f"[ERROR] {e}\n")
        
    def reset_waste_ink(self):
        model = self.model_var.get()
        ip_address = self.ip_var.get()
        if not model or not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, "[ERROR] Please select a printer model and enter a valid IP address.\n")
            return
        printer = EpsonPrinter(model=model, hostname=ip_address)
        try:
            printer.reset_waste_ink_levels()
            self.status_text.insert(tk.END, "[INFO] Waste ink levels have been reset.\n")
        except Exception as e:
            self.status_text.insert(tk.END, f"[ERROR] {e}\n")
    
    def start_detect_printers(self):
        self.status_text.insert(tk.END, "[INFO] Detecting printers... (this might take a while)\n")
        self.detect_button.config(state=tk.DISABLED) # disable button while processing
        
        # run printer detection in new thread, as it can take a while
        threading.Thread(target=self.detect_printers).start()
    
    def detect_printers(self):
        printer_scanner=PrinterScanner()
        try:
            printers = printer_scanner.get_all_printers()
            if len(printers) > 0:
                for printer in printers:
                    self.status_text.insert(tk.END, f"[INFO] {printer['name']} found at {printer['ip']} (hostname: {printer['hostname']})\n")
            else:
                self.status_text.insert(tk.END, "[WARN] No printers found.\n")
        except Exception as e:
            self.status_text.insert(tk.END, f"[ERROR] {e}\n")
        finally:
            self.detect_button.config(state=tk.NORMAL) # enable button after processing

    def _is_valid_ip(self,ip):
        try:
            ip = ipaddress.ip_address(ip)
            return True
        except ValueError:
            return False

if __name__ == "__main__":
    app = EpsonPrinterUI()
    app.mainloop()

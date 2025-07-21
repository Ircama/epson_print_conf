#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Epson Printer Configuration via SNMP (TCP/IP) - GUI
"""

import os
import sys
import re
import threading
import ipaddress
import inspect
from datetime import datetime
import traceback
import logging
import webbrowser
import pickle

from code import InteractiveConsole
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import black
import tkinter as tk
from tkinter import ttk, Menu
from tkinter.scrolledtext import ScrolledText
import tkinter.font as tkfont
from tkcalendar import DateEntry  # Ensure you have: pip install tkcalendar
from tkinter import simpledialog, messagebox, filedialog

import pyperclip
from epson_print_conf import EpsonPrinter, get_printer_models
from pyprintlpr import LprClient
from parse_devices import generate_config_from_toml, generate_config_from_xml, normalize_config
from find_printers import PrinterScanner
from text_console import TextConsole


VERSION = "7.0.0"

NO_CONF_ERROR = (
    " Please select a printer model and a valid IP address,"
    " or press 'Detect Printers'.\n"
)

CONFIRM_MESSAGE = (
            "EEPROM update - Confirm Action",
            "Please copy and save the codes in the [NOTE] shown on the screen."
            " They can be used to restore the initial configuration"
            " in case of problems.\n\n"
            "Are you sure you want to proceed?"
)


class EpcTextConsole(TextConsole):

    show_about_message = (
        "Epson Printer Configuration Interactive Console (API Playground)."
    )

    def show_help(self):
        """Open a separate window with help text."""
        help_window = tk.Toplevel(self)
        help_window.title("Help")
        help_window.geometry("1000x400")

        # Add a scrollbar and text widget
        scrollbar = tk.Scrollbar(help_window)
        scrollbar.pack(side="right", fill="y")

        help_text = tk.Text(
            help_window, wrap="word", yscrollcommand=scrollbar.set
        )
        help_text.tag_configure("title", foreground="purple")
        help_text.tag_configure("section", foreground="blue")

        help_text.insert(
            tk.END,
            f'Welcome to the {self.show_about_message}\n\n',
            "title"
        )
        help_text.insert(
            tk.END,
            'Features:\n\n',
            "section"
        )
        help_text.insert(
            tk.END,
            (
                "- Clear Console: Clears all text in the console.\n"
                "- History: Open a separate window showing the list of"
                " successfully executed commands (browse the command history).\n"
                "- Context Menu: Right-click for cut, copy, paste, or clear.\n\n"
            )
        )
        help_text.insert(
            tk.END,
            'Keyboard Shortcuts from the main window:\n\n',
            "section"
        )
        help_text.insert(
            tk.END,
            (
                "- F7: Open the Interactive Console (API Playground).\n\n"
            )
        )
        help_text.insert(
            tk.END,
            'Tokens:\n\n',
            "section"
        )
        help_text.insert(
            tk.END,
            (
                "self: EpsonPrinterUI self\n"
                "master: TextConsole widget\n"
                "kw: kw dictionary ({'width': 50, 'wrap': 'word'})\n"
                "local: TextConsole self\n\n"
            )
        )
        help_text.insert(
            tk.END,
            'Examples of commands:\n\n',
            "section"
        )
        help_text.insert(
            tk.END,
            (
                "self.printer.model\n"
                "self.printer.reverse_caesar(b'Hpttzqjv')\n"
                'self.printer.reverse_caesar(bytes.fromhex("48 62 7B 62 6F 6A 62 2B"))\n'
                'import pprint;pprint.pprint(self.printer.status_parser(self.printer.fetch_snmp_values("1.3.6.1.4.1.1248.1.2.2.1.1.1.4.1")[1]))\n'
                "self.printer.read_eeprom_many([0])\n"
                "self.printer.read_eeprom(0)\n"
                "self.printer.reset_waste_ink_levels()\n"
                "self.printer.fetch_snmp_values(self.printer.eeprom_oid_read_address(0))\n"
                "self.printer.fetch_snmp_values('1.3.6.1.4.1.1248.1.2.2.44.1.1.2.1.124.124.7.0.25.7.65.190.160.0.0')\n"
                'self.printer.fetch_oid_values(self.printer.epctrl_snmp_oid("vi", 0))\n'
                "self.get_ti_date(cursor=True)\n"
            )
        )
        help_text.config(state="disabled")  # Make the text read-only
        help_text.pack(fill="both", expand=True)
        scrollbar.config(command=help_text.yview)


class MultiLineInputDialog(simpledialog.Dialog):
    def __init__(self, parent, title=None, text=""):
        self.text=text
        super().__init__(parent, title)

    def body(self, frame):
        # Add a label with instructions
        self.label = tk.Label(frame, text=self.text)
        self.label.pack(pady=5)

        # Create a Text widget for multiline input
        self.textbox = tk.Text(frame, height=5, width=50)
        self.textbox.configure(font=("TkDefaultFont"))
        self.textbox.pack()
        return self.textbox

    def apply(self):
        # Get the input from the Text widget
        self.result = self.textbox.get("1.0", tk.END).strip()


class ToolTip:
    def __init__(
        self,
        widget,
        text="widget info",
        wrap_length=10,
        destroy=True
    ):
        self.widget = widget
        self.text = text
        self.wrap_length = wrap_length
        self.tooltip_window = None

        # Check and remove existing bindings if they exist
        if destroy:
            self.remove_existing_binding("<Enter>")
            self.remove_existing_binding("<Leave>")
            self.remove_existing_binding("<Button-1>")

        # Set new bindings
        widget.bind("<Enter>", self.enter, "+")  # Show the tooltip on hover
        widget.bind("<Leave>", self.leave, "+")  # Hide the tooltip on leave
        widget.bind("<Button-1>", self.leave, "+")  # Hide tooltip on mouse click

    def remove_existing_binding(self, event):
        # Check if there's already a binding for the event
        if self.widget.bind(event):
            self.widget.unbind(event)  # Remove the existing binding

    def enter(self, event=None):
        if self.tooltip_window or not self.text:
            return
        x, y, width, height = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 20
        y += self.widget.winfo_rooty() + 20
        self.tooltip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)

        # Calculate the position for the tooltip
        screen_width = self.widget.winfo_screenwidth()
        screen_height = self.widget.winfo_screenheight()

        tw.geometry(f"+{x}+{y + height + 2}")  # Default position below the widget

        label = tk.Label(
            tw,
            text=self.wrap_text(self.text),
            justify="left",
            background="LightYellow",
            relief="solid",
            borderwidth=1,
        )
        label.pack(ipadx=1)

        # Check if the tooltip goes off the screen
        tw.update_idletasks()  # Ensures the tooltip size is calculated
        tw_width = tw.winfo_width()
        tw_height = tw.winfo_height()

        if x + tw_width > screen_width:  # If tooltip goes beyond screen width
            x = screen_width - tw_width - 5
        if (y + height + tw_height > screen_height):  # If tooltip goes below screen height
            y = y - tw_height - height - 2  # Position above the widget
        tw.geometry(f"+{x}+{y}")

    def leave(self, event=None):
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None

    def wrap_text(self, text):
        words = text.split()
        lines = []
        current_line = []
        for word in words:
            if len(current_line) + len(word.split()) <= self.wrap_length:
                current_line.append(word)
            else:
                lines.append(" ".join(current_line))
                current_line = [word]
        if current_line:
            lines.append(" ".join(current_line))
        return "\n".join(lines)


class BugFixedDateEntry(DateEntry):
    """
    Fixes a bug on the calendar that does not accept mouse selection with Linux
    Fixes a drop down bug when the DateEntry widget is not focused
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def drop_down(self):
        self.focus_set()  # Set focus to the DateEntry widget
        super().drop_down()
        if self._top_cal is not None and not self._calendar.winfo_ismapped():
            self._top_cal.lift()


class EpsonPrinterUI(tk.Tk):
    def __init__(
        self,
        model: str = None,
        hostname: str = None,
        conf_dict = {},
        replace_conf=False
    ):
        def plain_fn(event, fn_handler):
            if event.state:  # Shift | Control | Alt
                return
            fn_handler()

        try:
            super().__init__()
        except Exception as e:
            logging.critical("Cannot start program: %s", e)
            quit()
        self.title("Epson Printer Configuration - v" + VERSION)
        self.geometry("500x500")
        if self.call('tk', 'windowingsystem') == "x11":
            self.minsize(600, 600)
        else:
            self.minsize(550, 600)
        self.printer_scanner = PrinterScanner()
        self.ip_list = []
        self.ip_list_cycle = None
        self.conf_dict = conf_dict
        self.replace_conf = replace_conf
        self.text_dump = ""
        self.mode = black.Mode(line_length=200, magic_trailing_comma=False)
        self.printer = None

        # configure the main window to be resizable
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # Setup the menu
        menubar = Menu(self)
        self.config(menu=menubar)

        # Create File menu
        file_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        LOAD_LABEL_NAME = "%s printer configuration file or web URL..."
        LOAD_LABEL_TITLE = "Select a %s printer configuration file, or enter a Web URL"
        LOAD_LABEL_TYPE = "%s files"
        file_menu.add_command(
            label=LOAD_LABEL_NAME % "Load a PICKLE",
            command=lambda: self.load_from_file(
                file_type={
                    "title": LOAD_LABEL_TITLE % "PICKLE",
                    "filetypes": [
                        (LOAD_LABEL_TYPE % "PICKLE", "*.pickle"),
                        ("All files", "*.*")
                    ]
                },
                type=0
            )
        )
        file_menu.add_command(
            label=LOAD_LABEL_NAME % "Import a XML",
            command=lambda: self.load_from_file(
                file_type={
                    "title": LOAD_LABEL_TITLE % "XML",
                    "filetypes": [
                        (LOAD_LABEL_TYPE % "XML", "*.xml"),
                        ("All files", "*.*")
                    ]
                },
                type=1
            )
        )
        file_menu.add_command(
            label=LOAD_LABEL_NAME % "Import a TOML",
            command=lambda: self.load_from_file(
                file_type={
                    "title": LOAD_LABEL_TITLE % "TOML",
                    "filetypes": [
                        (LOAD_LABEL_TYPE % "TOML", "*.toml"),
                        ("All files", "*.*")
                    ]
                },
                type=2
            )
        )
        file_menu.add_command(
            label="Save the selected printer configuration to a PICKLE file...",
            command=self.save_to_file
        )
        file_menu.add_command(label="Quit Application", command=self.quit)

        # Create Help menu
        help_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Settings", menu=help_menu)

        help_menu.add_command(label="Show printer parameters of the selected model", command=self.printer_config)
        help_menu.entryconfig("Show printer parameters of the selected model", accelerator="F2")

        help_menu.add_command(label="Show printer keys of the selected model", command=self.key_values)
        help_menu.entryconfig("Show printer keys of the selected model", accelerator="F3")

        help_menu.add_command(label="Keep only selected printer configuration", command=self.keep_printer_conf)
        help_menu.entryconfig("Keep only selected printer configuration", accelerator="F5")

        help_menu.add_command(label="Clear printer list", command=self.clear_printer_list)
        help_menu.entryconfig("Clear printer list", accelerator="F6")

        help_menu.add_command(label="Interactive Console (API Playground)", command=self.tk_console)
        help_menu.entryconfig("Interactive Console (API Playground)", accelerator="F7")

        help_menu.add_command(label="Remove selected printer configuration", command=self.remove_printer_conf)
        help_menu.entryconfig("Remove selected printer configuration", accelerator="F8")

        help_menu.add_command(label="Get next local IP addresss", command=lambda: self.next_ip(0))
        help_menu.entryconfig("Get next local IP addresss", accelerator="F9")

        # Create Help menu
        help_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="Usage guide", command=self.open_help_browser)
        help_menu.add_command(label="Program Information", command=self.show_program_info)

        # Setup frames
        FRAME_PAD = 10
        PAD = (3, 0)
        PADX = 4
        PADY = 5

        # main Frame
        main_frame = ttk.Frame(self, padding=FRAME_PAD)
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(5, weight=1)  # Number of rows
        row_n = 0

        # [row 0] Container frame for the two LabelFrames Power-off timer and TI Received Time
        model_ip_frame = ttk.Frame(main_frame, padding=PAD)
        model_ip_frame.grid(row=row_n, column=0, pady=PADY, sticky=(tk.W, tk.E))
        model_ip_frame.columnconfigure(0, weight=1)  # Allow column to expand
        model_ip_frame.columnconfigure(1, weight=1)  # Allow column to expand

        # BOX printer model selection
        model_frame = ttk.LabelFrame(
            model_ip_frame, text="Printer Model", padding=PAD
        )
        model_frame.grid(
            row=0, column=0, pady=PADY, padx=(0, PADX), sticky=(tk.W, tk.E)
        )
        model_frame.columnconfigure(0, weight=0)
        model_frame.columnconfigure(1, weight=1)

        # Model combobox
        self.model_var = tk.StringVar()
        if (
            "internal_data" in conf_dict
            and "default_model" in conf_dict["internal_data"]
        ):
            self.model_var.set(conf_dict["internal_data"]["default_model"])
        if model:
            self.model_var.set(model)
        ttk.Label(model_frame, text="Model:").grid(
            row=0, column=0, sticky=tk.W, padx=PADX
        )
        self.model_dropdown = ttk.Combobox(
            model_frame, textvariable=self.model_var, state="readonly"
        )
        self.model_dropdown["values"] = sorted(EpsonPrinter(
            conf_dict=self.conf_dict,
            replace_conf=self.replace_conf
        ).valid_printers)
        self.model_dropdown.grid(
            row=0, column=1, pady=PADY, padx=PADX, sticky=(tk.W, tk.E)
        )
        ToolTip(
            self.model_dropdown,
            "Select the model of the printer, or press 'Detect Printers'."
            " Special features are allowed via F2, F3, F5, F6, F8, F9.\n"
        )
        self.bind_all("<F2>", lambda e: plain_fn(e, self.printer_config))
        self.bind_all("<F3>", lambda e: plain_fn(e, self.key_values))
        self.bind_all("<F5>", lambda e: plain_fn(e, self.keep_printer_conf))
        self.bind_all("<F6>", lambda e: plain_fn(e, self.clear_printer_list))
        self.bind_all("<F7>", lambda e: plain_fn(e, self.tk_console))
        self.bind_all("<F8>", lambda e: plain_fn(e, self.remove_printer_conf))

        # BOX IP address
        ip_frame = ttk.LabelFrame(
            model_ip_frame, text="Printer IP Address", padding=PAD
        )
        ip_frame.grid(
            row=0, column=1, pady=PADY, padx=(PADX, 0), sticky=(tk.W, tk.E)
        )
        ip_frame.columnconfigure(0, weight=0)
        ip_frame.columnconfigure(1, weight=1)

        # IP address entry
        self.ip_var = tk.StringVar()
        if (
            "internal_data" in conf_dict
            and "hostname" in conf_dict["internal_data"]
        ):
            self.ip_var.set(conf_dict["internal_data"]["hostname"])
        if hostname:
            self.ip_var.set(hostname)
        ttk.Label(ip_frame, text="IP Address:").grid(
            row=0, column=0, sticky=tk.W, padx=PADX
        )
        self.ip_entry = ttk.Entry(ip_frame, textvariable=self.ip_var)
        self.ip_entry.grid(
            row=0, column=1, pady=PADY, padx=PADX, sticky=(tk.W, tk.E)
        )
        self.ip_entry.bind_all("<F9>", self.next_ip)
        ToolTip(
            self.ip_entry,
            "Enter the IP address, or press 'Detect Printers'"
            " (you can also enter part of the IP address"
            " to speed up the detection),"
            " or press F9 more times to get the next local IP address,"
            " which can then be edited"
            " (by removing the last part before pressing 'Detect Printers').",
        )

        # Create a custom style for the button to center the text
        style = ttk.Style()
        style.configure("Centered.TButton", justify='center', anchor="center")

        # [row 1] Container frame for the two LabelFrames Power-off timer and TI Received Time
        row_n += 1
        container_frame = ttk.Frame(main_frame, padding=PAD)
        container_frame.grid(
            row=row_n, column=0, pady=PADY, sticky=(tk.W, tk.E)
        )
        container_frame.columnconfigure(0, weight=1)  # Allow column to expand
        container_frame.columnconfigure(1, weight=1)  # Allow column to expand

        # BOX Power-off Timer (minutes)
        po_timer_frame = ttk.LabelFrame(
            container_frame, text="Power-off Timer (minutes)", padding=PAD
        )
        po_timer_frame.grid(
            row=0, column=0, pady=PADY, padx=(0, PADX), sticky=(tk.W, tk.E)
        )
        po_timer_frame.columnconfigure(0, weight=0)  # Button column on the left
        po_timer_frame.columnconfigure(1, weight=1)  # Entry column
        po_timer_frame.columnconfigure(2, weight=0)  # Button column on the right

        # Configure validation command for numeric entry
        validate_cmd = self.register(self.validate_number_input)

        # Power-off timer (minutes) - Get Button
        button_width = 7
        self.get_po_minutes = ttk.Button(
            po_timer_frame,
            text="Get",
            width=button_width,
            command=self.get_po_mins,
        )
        self.get_po_minutes.grid(
            row=0, column=0, padx=PADX, pady=PADY, sticky=tk.W
        )

        # Power-off timer (minutes) - minutes Entry
        self.po_timer_var = tk.StringVar()
        self.po_timer_entry = ttk.Entry(
            po_timer_frame,
            textvariable=self.po_timer_var,
            validate="all",
            validatecommand=(validate_cmd, "%P"),
            width=6,
            justify="center",
        )
        self.po_timer_entry.grid(
            row=0, column=1, pady=PADY, padx=PADX, sticky=(tk.W, tk.E)
        )
        ToolTip(
            self.po_timer_entry,
            "Enter a number of minutes.",
            destroy=False
        )

        # Power-off timer (minutes) - Set Button
        self.set_po_minutes = ttk.Button(
            po_timer_frame,
            text="Set",
            width=button_width,
            command=self.set_po_mins,
        )
        self.set_po_minutes.grid(
            row=0, column=2, padx=PADX, pady=PADY, sticky=tk.E
        )

        # BOX TI Received Time (date)
        ti_received_frame = ttk.LabelFrame(
            container_frame, text="TI Received Time (date)", padding=PAD
        )
        ti_received_frame.grid(
            row=0, column=1, pady=PADY, padx=(PADX, 0), sticky=(tk.W, tk.E)
        )
        ti_received_frame.columnconfigure(0, weight=0)  # Button column on the left
        ti_received_frame.columnconfigure(1, weight=1)  # Calendar column
        ti_received_frame.columnconfigure(2, weight=0)  # Button column on the right

        # TI Received Time - Get Button
        self.get_ti_received = ttk.Button(
            ti_received_frame,
            text="Get",
            width=button_width,
            command=self.get_ti_date,
        )
        self.get_ti_received.grid(
            row=0, column=0, padx=PADX, pady=PADY, sticky=tk.W
        )

        # TI Received Time - Calendar Widget
        self.date_entry = BugFixedDateEntry(
            ti_received_frame, date_pattern="yyyy-mm-dd"
        )
        self.date_entry.grid(
            row=0, column=1, padx=PADX, pady=PADY, sticky=(tk.W, tk.E)
        )
        self.date_entry.delete(0, "end")  # blank the field removing the current date
        ToolTip(
            self.date_entry,
            "Enter a valid date with format YYYY-MM-DD.",
            destroy=False
        )

        # TI Received Time - Set Button
        self.set_ti_received = ttk.Button(
            ti_received_frame,
            text="Set",
            width=button_width,
            command=self.set_ti_date,
        )
        self.set_ti_received.grid(
            row=0, column=2, padx=PADX, pady=PADY, sticky=tk.E
        )

        # [row 2] Container frame for the two LabelFrames WiFi MAC address and printer serial number
        row_n += 1
        container_frame = ttk.Frame(main_frame, padding=PAD)
        container_frame.grid(
            row=row_n, column=0, pady=PADY, sticky=(tk.W, tk.E)
        )
        container_frame.columnconfigure(0, weight=1)  # Allow column to expand
        container_frame.columnconfigure(1, weight=1)  # Allow column to expand

        # BOX WiFi MAC Address (6 alphanumeric digits optionally separated by dash)
        mac_addr_frame = ttk.LabelFrame(
            container_frame, text="WiFi MAC Address", padding=PAD
        )
        mac_addr_frame.grid(
            row=0, column=0, pady=PADY, padx=(0, PADX), sticky=(tk.W, tk.E)
        )
        mac_addr_frame.columnconfigure(0, weight=0)  # Button column on the left
        mac_addr_frame.columnconfigure(1, weight=1)  # Entry column
        mac_addr_frame.columnconfigure(2, weight=0)  # Button column on the right

        # Configure validation command for MAC address
        validate_mac_addr = (self.register(self.validate_mac_address), '%P')

        # WiFi MAC Address - Get Button
        button_width = 7
        self.get_mac_addr = ttk.Button(
            mac_addr_frame,
            text="Get",
            width=button_width,
            command=self.get_mac_address,
        )
        self.get_mac_addr.grid(
            row=0, column=0, padx=PADX, pady=PADY, sticky=tk.W
        )

        # WiFi MAC Address - Entry
        self.mac_addr_var = tk.StringVar()
        self.mac_addr_entry = ttk.Entry(
            mac_addr_frame,
            textvariable=self.mac_addr_var,
            validate="all",
            validatecommand=(validate_mac_addr, "%P"),
            width=22,  # Full MAC address with separators
            justify="center",
        )
        self.mac_addr_entry.grid(
            row=0, column=1, pady=PADY, padx=PADX, sticky=(tk.W, tk.E)
        )
        ToolTip(
            self.mac_addr_entry,
            "Enter Enter a valid MAC address"
            " (6 hex octets optionally separated by dash).",
            destroy=False
        )

        # WiFi MAC Address - Set Button
        self.set_mac_addr = ttk.Button(
            mac_addr_frame,
            text="Set",
            width=button_width,
            command=self.set_mac_address,
        )
        self.set_mac_addr.grid(
            row=0, column=2, padx=PADX, pady=PADY, sticky=tk.E
        )

        # BOX Serial number (10 characters)
        ser_num_frame = ttk.LabelFrame(
            container_frame, text="Printer Serial Number", padding=PAD
        )
        ser_num_frame.grid(
            row=0, column=1, pady=PADY, padx=(0, PADX), sticky=(tk.W, tk.E)
        )
        ser_num_frame.columnconfigure(0, weight=0)  # Button column on the left
        ser_num_frame.columnconfigure(1, weight=1)  # Entry column
        ser_num_frame.columnconfigure(2, weight=0)  # Button column on the right

        # Configure validation command for the printer serial number
        validate_ser_num = (self.register(self.validate_ser_number), '%P')

        # Printer Serial Number - Get Button
        button_width = 7
        self.get_ser_num = ttk.Button(
            ser_num_frame,
            text="Get",
            width=button_width,
            command=self.get_ser_number,
        )
        self.get_ser_num.grid(
            row=0, column=0, padx=PADX, pady=PADY, sticky=tk.W
        )

        # Printer Serial Number - Entry
        self.ser_num_var = tk.StringVar()
        self.ser_num_entry = ttk.Entry(
            ser_num_frame,
            textvariable=self.ser_num_var,
            validate="all",
            validatecommand=(validate_ser_num, "%P"),
            width=14,  # 10 characters
            justify="center",
        )
        self.ser_num_entry.grid(
            row=0, column=1, pady=PADY, padx=PADX, sticky=(tk.W, tk.E)
        )
        ToolTip(
            self.ser_num_entry,
            "Enter Enter a valid printer serial number"
            " (10 uppercase or numeric characters).",
            destroy=False
        )

        # Printer Serial Number - Set Button
        self.set_ser_num = ttk.Button(
            ser_num_frame,
            text="Set",
            width=button_width,
            command=self.set_ser_number,
        )
        self.set_ser_num.grid(
            row=0, column=2, padx=PADX, pady=PADY, sticky=tk.E
        )

        # [row 3] Query Buttons
        row_n += 1
        button_frame = ttk.Frame(main_frame, padding=PAD)
        button_frame.grid(row=row_n, column=0, pady=PADY, sticky=(tk.W, tk.E))
        button_frame.columnconfigure((0, 1, 2, 3, 4), weight=1)  # expand columns

        # Query Printer Status
        self.status_button = ttk.Button(
            button_frame, text="Printer\nStatus",
            command=self.printer_status,
            style="Centered.TButton"
        )
        self.status_button.grid(
            row=0, column=0, padx=PADX, pady=PADY, sticky=(tk.W, tk.E)
        )

        # Query list of cartridge types
        self.web_interface_button = ttk.Button(
            button_frame,
            text="Printer\nWeb interface",
            command=self.web_interface,
            style="Centered.TButton"
        )
        self.web_interface_button.grid(
            row=0, column=1, padx=PADX, pady=PADX, sticky=(tk.W, tk.E)
        )

        # Clean nozzles
        self.clean_nozzles_button = ttk.Button(
            button_frame,
            text="Clean\nNozzles",
            command=self.clean_nozzles,
            style="Centered.TButton"
        )
        self.clean_nozzles_button.grid(
            row=0, column=2, padx=PADX, pady=PADX, sticky=(tk.W, tk.E)
        )

        # Detect configuration values
        self.detect_configuration_button = ttk.Button(
            button_frame,
            text="Detect\nConfiguration",
            command=self.detect_configuration,
            style="Centered.TButton"
        )
        self.detect_configuration_button.grid(
            row=0, column=3, padx=PADX, pady=PADX, sticky=(tk.W, tk.E)
        )

        # Temporary Reset Waste Ink Levels
        self.temp_reset_ink_waste_button = ttk.Button(
            button_frame,
            text="Temporary Reset\nWaste Ink Levels",
            command=self.temp_reset_waste_ink,
            style="Centered.TButton"
        )
        self.temp_reset_ink_waste_button.grid(
            row=0, column=4, padx=PADX, pady=PADX, sticky=(tk.W, tk.E)
        )

        # [row 4] Tweak Buttons
        row_n += 1
        tweak_frame = ttk.Frame(main_frame, padding=PAD)
        tweak_frame.grid(row=row_n, column=0, pady=PADY, sticky=(tk.W, tk.E))
        tweak_frame.columnconfigure((0, 1, 2, 3, 4, 5), weight=1)  # expand columns

        # Detect Printers
        self.detect_button = ttk.Button(
            tweak_frame,
            text="Detect\nPrinters",
            command=self.start_detect_printers,
            style="Centered.TButton"
        )
        self.detect_button.grid(
            row=0, column=0, padx=PADX, pady=PADX, sticky=(tk.W, tk.E)
        )

        # Detect Access Keys
        self.detect_access_key_button = ttk.Button(
            tweak_frame,
            text="Detect\nAccess Keys",
            command=self.detect_access_key,
            style="Centered.TButton"
        )
        self.detect_access_key_button.grid(
            row=0, column=1, padx=PADX, pady=PADX, sticky=(tk.W, tk.E)
        )

        # Print test
        self.print_tests_button = ttk.Button(
            tweak_frame,
            text="Print\nTests",
            command=self.print_tests,
            style="Centered.TButton"
        )
        self.print_tests_button.grid(
            row=0, column=2, padx=PADX, pady=PADX, sticky=(tk.W, tk.E)
        )

        # Read EEPROM
        self.read_eeprom_button = ttk.Button(
            tweak_frame,
            text="Read\nEEPROM",
            command=self.read_eeprom,
            style="Centered.TButton"
        )
        self.read_eeprom_button.grid(
            row=0, column=3, padx=PADX, pady=PADX, sticky=(tk.W, tk.E)
        )

        # Write EEPROM
        self.write_eeprom_button = ttk.Button(
            tweak_frame,
            text="Write\nEEPROM",
            command=self.write_eeprom,
            style="Centered.TButton"
        )
        self.write_eeprom_button.grid(
            row=0, column=4, padx=PADX, pady=PADX, sticky=(tk.W, tk.E)
        )

        # Reset Waste Ink Levels
        self.reset_button = ttk.Button(
            tweak_frame,
            text="Reset Waste\nInk Levels",
            command=self.reset_waste_ink,
            style="Centered.TButton"
        )
        self.reset_button.grid(
            row=0, column=5, padx=PADX, pady=PADX, sticky=(tk.W, tk.E)
        )

        # [row 4] Status display (including ScrolledText and Treeview)
        row_n += 1
        status_frame = ttk.LabelFrame(main_frame, text="Status", padding=PAD)
        status_frame.grid(
            row=row_n, column=0, pady=PADY, sticky=(tk.W, tk.E, tk.N, tk.S)
        )
        status_frame.columnconfigure(0, weight=1)
        status_frame.rowconfigure(0, weight=1)

        # ScrolledText widget
        self.status_text = ScrolledText(
            status_frame, wrap=tk.WORD, font=("TkDefaultFont")
        )
        self.status_text.tag_configure("error", foreground="red")
        self.status_text.tag_configure("warn", foreground="blue")
        self.status_text.tag_configure("note", foreground="purple")
        self.status_text.tag_configure("info", foreground="green")
        self.status_text.grid(
            row=0,
            column=0,
            pady=PADY,
            padx=PADY,
            sticky=(tk.W, tk.E, tk.N, tk.S),
        )
        self.status_text.bind("<Tab>", self.focus_next)
        self.status_text.bind("<Shift-Tab>", self.focus_previous)
        self.status_text.bind("<Key>", lambda e: "break")  # disable editing text
        self.status_text.bind(
            "<Control-c>",
            lambda event: self.copy_to_clipboard(self.status_text),
        )
        # self.status_text.bind("<Button-1>", lambda e: "break")  # also disable the mouse

        # Create a context menu
        self.text_context_menu = Menu(self, tearoff=0)
        self.text_context_menu.add_command(
            label="Clear All", command=self.clear_all_text
        )
        self.text_context_menu.add_command(
            label="Copy", command=self.copy_text
        )
        self.text_context_menu.add_command(
            label="Copy all text", command=self.copy_all_text
        )
        self.text_context_menu.add_command(
            label="Print all text",
            command=lambda: self.print_items(
                self.status_text.get("1.0", tk.END).strip()
            )
        )
        self.text_context_menu.add_command(
            label="Switch to tree view",
            command=self.show_treeview
        )
        self.status_text.bind("<Button-3>", self.show_text_context_menu)

        # Create a frame to contain the Treeview and its scrollbar
        self.tree_frame = tk.Frame(status_frame)
        self.tree_frame.grid(column=0, row=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.tree_frame.columnconfigure(0, weight=1)
        self.tree_frame.rowconfigure(0, weight=1)

        # Style configuration for the treeview
        style = ttk.Style(self)
        treeview_font = style.lookup("Treeview.Heading", "font")

        # For the treeview, if the treeview_font is a tuple, split into components
        if isinstance(treeview_font, tuple):
            treeview_font_name, treeview_font_size = (
                treeview_font[0],
                treeview_font[1],
            )
        else:
            # If font is not a tuple, it might be a font string or other format.
            treeview_font_name, treeview_font_size = tkfont.Font().actual(
                "family"
            ), tkfont.Font().actual("size")
        style.configure(
            "Treeview.Heading",
            font=(treeview_font_name, treeview_font_size - 4, "bold"),
            background="lightblue",
            foreground="darkblue",
        )

        # Create and configure the Treeview widget
        self.tree = ttk.Treeview(self.tree_frame, style="Treeview")
        self.tree.grid(column=0, row=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Create a vertical scrollbar for the Treeview
        tree_scrollbar = ttk.Scrollbar(
            self.tree_frame, orient="vertical", command=self.tree.yview
        )
        tree_scrollbar.grid(column=1, row=0, sticky=(tk.N, tk.S))

        # Configure the Treeview to use the scrollbar
        self.tree.configure(yscrollcommand=tree_scrollbar.set)

        # Create a context menu
        self.context_menu = Menu(self, tearoff=0)
        self.context_menu.add_command(
            label="Copy this item", command=self.copy_selected_item
        )
        self.context_menu.add_command(
            label="Copy all items", command=self.copy_all_items
        )
        self.context_menu.add_command(
            label="Print all items",
            command=lambda: self.print_items(self.text_dump)
        )
        self.context_menu.add_command(
            label="Switch to text status",
            command=self.show_status_text_view
        )

        # Bind the right-click event to the Treeview
        self.tree.bind("<Button-3>", self.show_context_menu)

        # Hide the Treeview initially
        self.tree_frame.grid_remove()

        self.model_var.trace('w', self.change_widget_states)
        self.ip_var.trace('w', self.change_widget_states)
        self.change_widget_states()

    def save_to_file(self):
        if not self.model_var.get():
            self.show_status_text_view()
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END,
                ': Unknown printer model.'
            )
            return
        if not self.printer:
            self.printer = EpsonPrinter(
                conf_dict=self.conf_dict,
                model=self.model_var.get(),
            )
        if not self.printer or not self.printer.parm:
            self.show_status_text_view()
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END,
                ': No printer configuration defined.'
            )
            return
        # Open file dialog to enter the file
        file_path = filedialog.asksaveasfilename(
            defaultextension=".pickle",
            title="PICKLE file name",
            initialfile=self.model_var.get(),
            filetypes=[("PICKLE files", "*.pickle")]
        )
        if not file_path:
            self.show_status_text_view()
            self.status_text.insert(tk.END, '[WARNING]', "warn")
            self.status_text.insert(
                tk.END,
                f" File save operation aborted.\n"
            )
            return
        # Ensure the file has the desired extension
        if "." not in file_path and not file_path.endswith(".pickle"):
            file_path += ".pickle"
        normalized_config = { self.model_var.get(): self.printer.parm.copy() }
        normalized_config["internal_data"] = {}
        normalized_config["internal_data"]["default_model"] = self.model_var.get()
        if self.ip_var.get():
            normalized_config["internal_data"]["hostname"] = self.ip_var.get()
        try:
            with open(file_path, "wb") as file:
                pickle.dump(normalized_config, file) # serialize the list
        except Exception:
            self.show_status_text_view()
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END,
                f" File save operation failed.\n"
            )
            return
        self.status_text.insert(tk.END, '[INFO]', "info")
        self.status_text.insert(
            tk.END,
            f' "{os.path.basename(file_path)}" file save operation completed.\n'
        )

    def load_from_file(self, file_type, type):
        # Open file dialog to select the file
        self.show_status_text_view()
        file_path = filedialog.askopenfilename(**file_type)
        self.config(cursor="watch")
        self.update_idletasks()
        self.update()
        if not file_path:
            self.config(cursor="")
            self.update_idletasks()
            self.show_status_text_view()
            self.status_text.insert(tk.END, '[WARNING]', "warn")
            self.status_text.insert(
                tk.END,
                f" File load operation aborted.\n"
            )
            return
        if type == 0:
            try:
                with open(file_path, 'rb') as pickle_file:
                    self.conf_dict = pickle.load(pickle_file)
            except Exception as e:
                self.config(cursor="")
                self.update_idletasks()
                self.show_status_text_view()
                if not file_path.tell():
                    self.status_text.insert(tk.END, '[ERROR]', "error")
                    self.status_text.insert(
                        tk.END,
                        f" Empty PICKLE FILE {file_path}.\n"
                    )
                else:
                    self.status_text.insert(tk.END, '[ERROR]', "error")
                    self.status_text.insert(
                        tk.END,
                        f" Cannot load PICKLE file {file_path}. {e}\n"
                    )
                return
            if (
                "internal_data" in self.conf_dict
                and "hostname" in self.conf_dict["internal_data"]
            ):
                self.ip_var.set(self.conf_dict["internal_data"]["hostname"])
            if (
                "internal_data" in self.conf_dict
                and "default_model" in self.conf_dict["internal_data"]
            ):
                self.model_var.set(self.conf_dict["internal_data"]["default_model"])
        else:
            self.config(cursor="watch")
            self.status_text.insert(tk.END, '[INFO]', "info")
            self.status_text.insert(
                tk.END,
                f" Converting file, please wait...\n"
            )
            self.update_idletasks()
            if type == 1:
                printer_config = generate_config_from_xml(config=file_path)
            if type == 2:
                printer_config = generate_config_from_toml(config=file_path)
            if not printer_config:
                self.config(cursor="")
                self.show_status_text_view()
                self.status_text.insert(tk.END, '[ERROR]', "error")
                self.status_text.insert(
                    tk.END,
                    f" Cannot load file {file_path}\n"
                )
                return
            self.conf_dict = normalize_config(config=printer_config)
        self.model_dropdown["values"] = sorted(EpsonPrinter(
            conf_dict=self.conf_dict,
            replace_conf=self.replace_conf
        ).valid_printers)
        self.config(cursor="")
        self.update_idletasks()
        if file_path:
            self.show_status_text_view()
            self.status_text.insert(tk.END, '[INFO]', "info")
            self.status_text.insert(
                tk.END,
                f" Loaded file {os.path.basename(file_path)}.\n"
            )

    def keep_printer_conf(self):
        self.show_status_text_view()
        if not self.model_var.get():
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END,
                ' Select a valid printer model.\n'
            )
            return
        keep_model = self.model_var.get()
        self.model_dropdown["values"] = tuple(
            model for model in self.model_dropdown["values"] if model == keep_model
        )
        self.replace_conf = True
        self.show_status_text_view()
        self.update_idletasks()
        self.status_text.insert(tk.END, '[INFO]', "info")
        self.status_text.insert(
            tk.END,
            f" Printer {keep_model} is the only one in the list.\n"
        )

    def remove_printer_conf(self):
        self.show_status_text_view()
        if not self.model_var.get():
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END,
                ' Select a valid printer model.\n'
            )
            return
        remove_model = self.model_var.get()
        self.model_var.set("")
        self.model_dropdown["values"] = tuple(
            model for model in self.model_dropdown["values"] if model != remove_model
        )
        self.replace_conf = True
        self.show_status_text_view()
        self.update_idletasks()
        self.status_text.insert(tk.END, '[INFO]', "info")
        self.status_text.insert(
            tk.END,
            f" Configuation of printer {remove_model} removed.\n"
        )

    def clear_printer_list(self):
        self.conf_dict = {}
        self.model_var.set("")
        self.model_dropdown["values"] = {}
        self.replace_conf = True
        self.show_status_text_view()
        self.update_idletasks()
        self.status_text.insert(tk.END, '[INFO]', "info")
        self.status_text.insert(
            tk.END,
            f" Printer list cleared.\n"
        )

    def tk_console(self):
        if hasattr(
            self, '_console_window'
        ) and self._console_window.winfo_exists():
            self._console_window.deiconify()
            self._console_window.lift()
            self._console_window.focus_force()
            # Find the console widget and focus it properly
            for widget in self._console_window.winfo_children():
                widget.focus_set()
            return

        self._console_window = tk.Toplevel(self)
        self._console_window.title(
            "Epson Printer Configuration Interactive Console (API Playground)"
        )
        self._console_window.geometry("800x400")

        console = EpcTextConsole(self, self._console_window)
        console.focus_set()
        console.pack(fill='both', expand=True)

        # Optional: handle window close to remove reference
        def on_close():
            self._console_window.destroy()
            self._console_window = None

    def open_help_browser(self):
        # Opens a web browser to a help URL
        url = "https://ircama.github.io/epson_print_conf"
        self.show_status_text_view()
        try:
            ret = webbrowser.open(url)
            if ret:
                self.status_text.insert(tk.END, '[INFO]', "info")
                self.status_text.insert(
                    tk.END, f" The browser is being opened.\n"
                )
            else:
                self.status_text.insert(tk.END, '[ERROR]', "error")
                self.status_text.insert(
                    tk.END, f" Cannot open browser.\n"
                )
        except Exception as e:
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END, f" Cannot open web browser: {e}\n"
            )
        finally:
            self.config(cursor="")
            self.update_idletasks()

    def show_program_info(self):
        # Show program information in a popup
        program_version = "1.0.0"  # Specify your program version
        description = """
Epson Printer Configuration tool via SNMP (TCP/IP).

A tool for managing settings of Epson printers connected via Wi-Fi over the SNMP protocol.

Web site: https://github.com/Ircama/epson_print_conf
"""
        self.title("Epson Printer Configuration - v" + VERSION)
        messagebox.showinfo("Program Information",
            f"Version: {VERSION}\n{description}"
        )

    def focus_next(self, event):
        event.widget.tk_focusNext().focus()
        return("break")

    def focus_previous(self, event):
        event.widget.tk_focusPrev().focus()
        return("break")

    def change_widget_states(self, index=None, value=None, op=None):
        """
        Enable or disable buttons when IP address and printer model change
        """
        ToolTip(self.get_ti_received, "")
        ToolTip(self.get_po_minutes, "")
        ToolTip(self.get_mac_addr, "")
        ToolTip(self.set_mac_addr, "")
        ToolTip(self.read_eeprom_button, "")
        ToolTip(self.detect_configuration_button, "")
        ToolTip(self.clean_nozzles_button, "")
        ToolTip(self.print_tests_button, "")
        ToolTip(self.temp_reset_ink_waste_button, "")
        ToolTip(self.write_eeprom_button, "")
        ToolTip(self.reset_button, "")
        if self.ip_var.get():
            if not self.model_var.get():
                self.reset_button.state(["disabled"])
            self.status_button.state(["!disabled"])
            self.web_interface_button.state(["!disabled"])
            self.detect_access_key_button.state(["!disabled"])
            self.printer = None
        else:
            self.reset_button.state(["disabled"])
            self.status_button.state(["disabled"])
            self.read_eeprom_button.state(["disabled"])
            self.clean_nozzles_button.state(["disabled"])
            self.print_tests_button.state(["disabled"])
            self.temp_reset_ink_waste_button.state(["disabled"])
            self.detect_configuration_button.state(["disabled"])
            self.write_eeprom_button.state(["disabled"])
            self.web_interface_button.state(["disabled"])
            self.detect_access_key_button.state(["disabled"])
        if self.ip_var.get() and self.model_var.get():
            self.printer = EpsonPrinter(
                conf_dict=self.conf_dict,
                replace_conf=self.replace_conf,
                model=self.model_var.get(),
                hostname=self.ip_var.get()
            )
            if not self.printer:
                return
            if not self.printer.parm:
                self.reset_printer_model()
                return

            self.read_eeprom_button.state(["disabled"])
            ToolTip(
                self.read_eeprom_button,
                "Feature not defined in the printer configuration."
            )
            self.temp_reset_ink_waste_button.state(["disabled"])
            ToolTip(
                self.temp_reset_ink_waste_button,
                "Select the printer first."
            )
            self.clean_nozzles_button.state(["disabled"])
            ToolTip(
                self.clean_nozzles_button,
                "Select the printer first."
            )
            self.print_tests_button.state(["disabled"])
            ToolTip(
                self.print_tests_button,
                "Select the printer first."
            )
            self.detect_configuration_button.state(["disabled"])
            ToolTip(
                self.detect_configuration_button,
                "Select the printer first."
            )
            self.write_eeprom_button.state(["disabled"])
            ToolTip(
                self.write_eeprom_button,
                "Feature not defined in the printer configuration."
            )
            if self.printer and self.printer.parm:
                if "read_key" in self.printer.parm:
                    self.read_eeprom_button.state(["!disabled"])
                    ToolTip(self.read_eeprom_button, "")
                    self.clean_nozzles_button.state(["!disabled"])
                    self.print_tests_button.state(["!disabled"])
                    self.temp_reset_ink_waste_button.state(["!disabled"])
                    self.detect_configuration_button.state(["!disabled"])
                    ToolTip(self.detect_configuration_button, "")
                    ToolTip(self.clean_nozzles_button, "")
                    ToolTip(self.print_tests_button, "")
                    ToolTip(self.temp_reset_ink_waste_button, "")
                if "write_key" in self.printer.parm:
                    self.write_eeprom_button.state(["!disabled"])
                    ToolTip(
                        self.write_eeprom_button,
                        "Ensure you really want this before pressing this key."
                    )

            if self.printer.parm.get("stats", {}).get("Power off timer"):
                self.po_timer_entry.state(["!disabled"])
                self.get_po_minutes.state(["!disabled"])
                self.set_po_minutes.state(["!disabled"])
                ToolTip(self.get_po_minutes, "")
            else:
                self.po_timer_entry.state(["disabled"])
                self.get_po_minutes.state(["disabled"])
                self.set_po_minutes.state(["disabled"])
                ToolTip(
                    self.get_po_minutes,
                    "Feature not defined in the printer configuration."
                )

            if self.printer.parm.get("stats", {}).get("First TI received time"):
                self.date_entry.state(["!disabled"])
                self.get_ti_received.state(["!disabled"])
                self.set_ti_received.state(["!disabled"])
                ToolTip(self.get_ti_received, "")
            else:
                self.date_entry.state(["disabled"])
                self.get_ti_received.state(["disabled"])
                self.set_ti_received.state(["disabled"])
                ToolTip(
                    self.get_ti_received,
                    "Feature not defined in the printer configuration."
                )

            if self.printer.parm.get("wifi_mac_address"):
                self.mac_addr_entry.state(["!disabled"])
                self.get_mac_addr.state(["!disabled"])
                self.set_mac_addr.state(["!disabled"])
                ToolTip(self.get_mac_addr, "")
            else:
                self.mac_addr_entry.state(["disabled"])
                self.get_mac_addr.state(["disabled"])
                self.set_mac_addr.state(["disabled"])
                ToolTip(
                    self.get_mac_addr,
                    "Feature not defined in the printer configuration."
                )

            if self.printer.parm.get("serial_number"):
                self.ser_num_entry.state(["!disabled"])
                self.get_ser_num.state(["!disabled"])
                self.set_ser_num.state(["!disabled"])
                ToolTip(self.get_ser_num, "")
            else:
                self.ser_num_entry.state(["disabled"])
                self.get_ser_num.state(["disabled"])
                self.set_ser_num.state(["disabled"])
                ToolTip(
                    self.get_ser_num,
                    "Feature not defined in the printer configuration."
                )

            if self.printer.reset_waste_ink_levels(dry_run=True):
                self.reset_button.state(["!disabled"])
                ToolTip(
                    self.reset_button,
                    "Ensure you really want this before pressing this key."
                )
            else:
                self.reset_button.state(["disabled"])
                ToolTip(
                    self.reset_button,
                    "Feature not defined in the printer configuration."
                )
        else:
            self.status_button.state(["disabled"])
            self.read_eeprom_button.state(["disabled"])
            self.detect_configuration_button.state(["disabled"])
            self.clean_nozzles_button.state(["disabled"])
            self.print_tests_button.state(["disabled"])
            self.temp_reset_ink_waste_button.state(["disabled"])
            self.write_eeprom_button.state(["disabled"])

            self.po_timer_entry.state(["disabled"])
            self.get_po_minutes.state(["disabled"])
            self.set_po_minutes.state(["disabled"])

            self.date_entry.state(["disabled"])
            self.get_ti_received.state(["disabled"])
            self.set_ti_received.state(["disabled"])

            self.mac_addr_entry.state(["disabled"])
            self.get_mac_addr.state(["disabled"])
            self.set_mac_addr.state(["disabled"])

            self.ser_num_entry.state(["disabled"])
            self.get_ser_num.state(["disabled"])
            self.set_ser_num.state(["disabled"])

        self.update_idletasks()

    def next_ip(self, event):
        ip = self.ip_var.get()
        if self.ip_list_cycle == None:
            self.ip_list = self.printer_scanner.get_all_printers(local=True)
            self.ip_list_cycle = 0
        if not self.ip_list:
            return
        self.ip_var.set(self.ip_list[self.ip_list_cycle])
        self.ip_list_cycle += 1
        if self.ip_list_cycle >= len(self.ip_list):
            self.ip_list_cycle = None

    def copy_to_clipboard(self, text_widget):
        try:
            text = text_widget.selection_get()
            pyperclip.copy(text)
        except tk.TclError:
            pass
        return "break"

    def handle_printer_error(self, e):
        self.show_status_text_view()
        if isinstance(e, TimeoutError):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END, f" Printer is unreachable or offline.\n"
            )
        else:
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END, f" {e}\n{traceback.format_exc()}\n"
            )

    def get_po_mins(self, cursor=True):
        if cursor:
            self.config(cursor="watch")
            self.update()
            current_function_name = inspect.stack()[0][3]
            method_to_call = getattr(self, current_function_name)
            self.after(100, lambda: method_to_call(cursor=False))
            return
        self.show_status_text_view()
        ip_address = self.ip_var.get()
        if not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update()
            return
        if not self.printer:
            return
        if not self.printer.parm.get("stats", {}).get("Power off timer"):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END,
                f" Missing 'Power off timer' in configuration\n",
            )
            self.config(cursor="")
            self.update_idletasks()
            return
        try:
            po_timer = self.printer.stats()["stats"]["Power off timer"]
            self.status_text.insert(tk.END, '[INFO]', "info")
            self.status_text.insert(
                tk.END, f" Power off timer: {po_timer} minutes.\n"
            )
            self.po_timer_var.set(po_timer)
        except Exception as e:
            self.handle_printer_error(e)
        finally:
            self.config(cursor="")
            self.update_idletasks()

    def get_ser_number(self, cursor=True):
        if cursor:
            self.config(cursor="watch")
            self.update()
            current_function_name = inspect.stack()[0][3]
            method_to_call = getattr(self, current_function_name)
            self.after(100, lambda: method_to_call(cursor=False))
            return
        self.show_status_text_view()
        ip_address = self.ip_var.get()
        if not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update()
            return
        if not self.printer:
            return
        try:
            ser_num = self.printer.get_serial_number()
        except Exception as e:
            self.handle_printer_error(e)
            self.config(cursor="")
            self.update_idletasks()
            return
        if ser_num is False:
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END,
                f" Improper values in printer serial number.\n",
            )
            self.config(cursor="")
            self.update_idletasks()
            return
        if not ser_num or "?" in ser_num:
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END,
                f" Cannot retrieve the printer serial number.\n",
            )
            self.config(cursor="")
            self.update_idletasks()
            return
        self.status_text.insert(tk.END, '[INFO]', "info")
        self.status_text.insert(
            tk.END, f" Printer serial number: {ser_num}.\n"
        )
        self.ser_num_var.set(ser_num)
        self.config(cursor="")
        self.update_idletasks()

    def get_mac_address(self, cursor=True):
        if cursor:
            self.config(cursor="watch")
            self.update()
            current_function_name = inspect.stack()[0][3]
            method_to_call = getattr(self, current_function_name)
            self.after(100, lambda: method_to_call(cursor=False))
            return
        self.show_status_text_view()
        ip_address = self.ip_var.get()
        if not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update()
            return
        if not self.printer:
            return
        try:
            mac_addr = self.printer.get_wifi_mac_address()
        except Exception as e:
            self.handle_printer_error(e)
            self.config(cursor="")
            self.update_idletasks()
            return
        if not mac_addr:
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END,
                f" Cannot retrieve the printer WiFi MAC address.\n",
            )
            self.config(cursor="")
            self.update_idletasks()
            return
        self.status_text.insert(tk.END, '[INFO]', "info")
        self.status_text.insert(
            tk.END, f" Printer WiFi MAC address: {mac_addr}.\n"
        )
        self.mac_addr_var.set(mac_addr)
        self.config(cursor="")
        self.update_idletasks()

    def get_current_eeprom_values(self, values, label):
        values = list(values)
        try:
            org_values = ', '.join(
                "" if v is None else f"{k}: {int(v, 16)}" for k, v in zip(
                    values, self.printer.read_eeprom_many(values, label=label)
                )
            )
            if org_values:
                self.status_text.insert(tk.END, '[NOTE]', "note")
                self.status_text.insert(
                    tk.END,
                    f" Current EEPROM values for {label}: {org_values}.\n"
                )
            else:
                self.status_text.insert(tk.END, '[ERROR]', "error")
                self.status_text.insert(
                    tk.END,
                    f' Cannot read EEPROM values for "{label}"'
                    f' invalid printer model selected: {self.printer.model}.\n'
                )
                self.config(cursor="")
                self.update_idletasks()
                return False
            self.config(cursor="")
            self.update_idletasks()
            return True
        except Exception as e:
            self.handle_printer_error(e)
            self.config(cursor="")
            self.update_idletasks()
            return False

    def set_po_mins(self, cursor=True):
        if cursor:
            self.config(cursor="watch")
            self.update()
            current_function_name = inspect.stack()[0][3]
            method_to_call = getattr(self, current_function_name)
            self.after(100, lambda: method_to_call(cursor=False))
            return
        self.show_status_text_view()
        ip_address = self.ip_var.get()
        if not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update_idletasks()
            return
        if not self.printer:
            return
        if not self.printer.parm.get("stats", {}).get("Power off timer"):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END,
                f" Missing 'Power off timer' in configuration\n",
            )
            self.config(cursor="")
            self.update_idletasks()
            return
        po_timer = self.po_timer_var.get()
        self.config(cursor="")
        self.update_idletasks()
        if not po_timer.isnumeric():
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END, " Please Use a valid value for minutes.\n"
            )
            self.config(cursor="")
            self.update_idletasks()
            return
        try:
            if not self.get_current_eeprom_values(
                self.printer.parm["stats"]["Power off timer"],
                "Power off timer"
            ):
                self.config(cursor="")
                self.update_idletasks()
                return
        except Exception as e:
            self.handle_printer_error(e)
            self.config(cursor="")
            self.update_idletasks()
            return
        self.status_text.insert(tk.END, '[INFO]', "info")
        self.status_text.insert(
            tk.END,
            f" Set Power off timer: {po_timer} minutes. Restarting"
            " the printer is required for this change to take effect.\n"
        )
        response = messagebox.askyesno(*CONFIRM_MESSAGE, default='no')
        if response:
            try:
                self.printer.write_poweroff_timer(int(po_timer))
                self.status_text.insert(tk.END, '[INFO]', "info")
                self.status_text.insert(
                    tk.END, " Update operation completed.\n"
                )
            except Exception as e:
                self.handle_printer_error(e)
        else:
            self.status_text.insert(tk.END, '[WARNING]', "warn")
            self.status_text.insert(
                tk.END, f" Set Power off timer aborted.\n"
            )
        self.config(cursor="")
        self.update_idletasks()

    def set_mac_address(self, cursor=True):
        if cursor:
            self.config(cursor="watch")
            self.update()
            current_function_name = inspect.stack()[0][3]
            method_to_call = getattr(self, current_function_name)
            self.after(100, lambda: method_to_call(cursor=False))
            return
        self.show_status_text_view()
        ip_address = self.ip_var.get()
        if not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update_idletasks()
            return
        if not self.printer:
            return
        mac = self.mac_to_int_list(self.mac_addr_var.get())
        if not mac or not self.validate_mac_address(
            self.mac_addr_var.get()
        ):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END, " Please Use a valid MAC address.\n"
            )
            self.config(cursor="")
            self.update_idletasks()
            return
        response = messagebox.askyesno(
            "Critical operation",
            "After the change is applied, restarting the printer is required"
            " for this change to take effect.\n\n"
            "Warning: this is a dangerous operation.\nContinue only "
            "if you are very sure of what you do.\n\n",
            default='no')
        if not response:
            self.status_text.insert(tk.END, '[WARNING]', "warn")
            self.status_text.insert(
                tk.END, " Operation aborted.\n"
            )
            self.config(cursor="")
            self.update_idletasks()
            return
        try:
            if not self.get_current_eeprom_values(
                self.printer.parm["wifi_mac_address"],
                "WiFi MAC Address"
            ):
                self.config(cursor="")
                self.update_idletasks()
                return
        except Exception as e:
            self.handle_printer_error(e)
            self.config(cursor="")
            self.update_idletasks()
            return
        self.status_text.insert(tk.END, '[INFO]', "info")
        self.status_text.insert(
            tk.END,
            f" Set WiFi MAC Address: {self.mac_addr_var.get()}.\n"
        )
        response = messagebox.askyesno(*CONFIRM_MESSAGE, default='no')
        if not response:
            self.status_text.insert(tk.END, '[WARNING]', "warn")
            self.status_text.insert(
                tk.END, " Operation aborted.\n"
            )
            self.config(cursor="")
            self.update_idletasks()
            return
        self.status_text.insert(tk.END, '[INFO]', "info")
        self.status_text.insert(
            tk.END,
            " Changing the WiFi MAC address of the printer. Restarting"
            " the printer is required for this change to take effect.\n"
        )
        ret = None
        try:
            ret = self.printer.update_parameter(
                "wifi_mac_address",
                mac,
                dry_run=False
            )
        except Exception as e:
            self.handle_printer_error(e)
        if ret:
            self.status_text.insert(tk.END, '[INFO]', "info")
            self.status_text.insert(
                tk.END, " Update operation completed.\n"
            )
        else:
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END, f" Write operation failed.\n"
            )
        self.config(cursor="")
        self.update_idletasks()

    def set_ser_number(self, cursor=True):
        if cursor:
            self.config(cursor="watch")
            self.update()
            current_function_name = inspect.stack()[0][3]
            method_to_call = getattr(self, current_function_name)
            self.after(100, lambda: method_to_call(cursor=False))
            return
        self.show_status_text_view()
        ip_address = self.ip_var.get()
        if not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update_idletasks()
            return
        if not self.printer:
            return
        if not self.ser_num_var.get() or not self.validate_ser_number(
            self.ser_num_var.get()
        ):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END, " Please Use a valid serial number.\n"
            )
            self.config(cursor="")
            self.update_idletasks()
            return
        pr_ser_num = self.printer.parm["serial_number"]
        if isinstance(pr_ser_num, (list, tuple)):
            list_ser_num = pr_ser_num
        else:
            list_ser_num = [pr_ser_num]
        for i in list_ser_num:
            try:
                if not self.get_current_eeprom_values(
                    i, "Printer Serial Number"
                ):
                    self.config(cursor="")
                    self.update_idletasks()
                    return
            except Exception as e:
                self.handle_printer_error(e)
                self.config(cursor="")
                self.update_idletasks()
                return
        self.status_text.insert(tk.END, '[INFO]', "info")
        self.status_text.insert(
            tk.END,
            f" Set Printer Serial Number: {self.ser_num_var.get()}.\n"
        )
        response = messagebox.askyesno(*CONFIRM_MESSAGE, default='no')
        if not response:
            self.status_text.insert(tk.END, '[WARNING]', "warn")
            self.status_text.insert(
                tk.END, " Operation aborted.\n"
            )
            self.config(cursor="")
            self.update_idletasks()
            return
        self.status_text.insert(tk.END, '[INFO]', "info")
        self.status_text.insert(
            tk.END,
            " Changing the serial number of the printer. Restarting"
            " the printer is required for this change to take effect.\n"
        )
        ret = None
        try:
            ret = self.printer.update_parameter(
                "serial_number",
                [i for i in self.ser_num_var.get().encode()],
                dry_run=False
            )
        except Exception as e:
            self.handle_printer_error(e)
        if ret:
            self.status_text.insert(tk.END, '[INFO]', "info")
            self.status_text.insert(
                tk.END, " Update operation completed.\n"
            )
        else:
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END, f" Write operation failed.\n"
            )
        self.config(cursor="")
        self.update_idletasks()

    def get_ti_date(self, cursor=True):
        if cursor:
            self.config(cursor="watch")
            self.update()
            current_function_name = inspect.stack()[0][3]
            method_to_call = getattr(self, current_function_name)
            self.after(100, lambda: method_to_call(cursor=False))
            return
        self.show_status_text_view()
        ip_address = self.ip_var.get()
        if not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update_idletasks()
            return
        if not self.printer:
            return
        if not self.printer.parm.get("stats", {}).get("First TI received time"):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END,
                f" Missing 'First TI received time' in configuration\n",
            )
            self.config(cursor="")
            self.update_idletasks()
            return
        try:
            d = self.printer.stats()["stats"]["First TI received time"]
            if d == "?":
                self.status_text.insert(tk.END, '[ERROR]', "error")
                self.status_text.insert(
                    tk.END,
                    " No data from 'First TI received time'."
                    " Check printer configuration.\n",
                )
                self.config(cursor="")
                self.update_idletasks()
                return
            date_string = datetime.strptime(d, "%d %b %Y").strftime("%Y-%m-%d")
            self.status_text.insert(tk.END, '[INFO]', "info")
            self.status_text.insert(
                tk.END,
                f" First TI received time (YYYY-MM-DD): {date_string}.\n",
            )
            self.date_entry.set_date(date_string)
        except Exception as e:
            self.handle_printer_error(e)
        finally:
            self.config(cursor="")
            self.update_idletasks()

    def set_ti_date(self, cursor=True):
        if cursor:
            self.config(cursor="watch")
            self.update()
            current_function_name = inspect.stack()[0][3]
            method_to_call = getattr(self, current_function_name)
            self.after(100, lambda: method_to_call(cursor=False))
            return
        self.show_status_text_view()
        ip_address = self.ip_var.get()
        if not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update_idletasks()
            return
        if not self.printer:
            return
        if not self.printer.parm.get("stats", {}).get("First TI received time"):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END,
                f" Missing 'First TI received time' in configuration\n",
            )
            self.config(cursor="")
            self.update_idletasks()
            return
        date_string = self.date_entry.get_date()
        try:
            if not self.get_current_eeprom_values(
                self.printer.parm["stats"]["First TI received time"],
                "First TI received time"
            ):
                self.config(cursor="")
                self.update_idletasks()
                return
        except Exception as e:
            self.handle_printer_error(e)
            self.config(cursor="")
            self.update_idletasks()
            return
        self.status_text.insert(tk.END, '[INFO]', "info")
        self.status_text.insert(
            tk.END,
            f" Set 'First TI received time' (YYYY-MM-DD) to: "
            f"{date_string.strftime('%Y-%m-%d')}.\n",
        )
        response = messagebox.askyesno(*CONFIRM_MESSAGE, default='no')
        if response:
            try:
                self.printer.write_first_ti_received_time(
                    date_string.year, date_string.month, date_string.day
                )
                self.status_text.insert(tk.END, '[INFO]', "info")
                self.status_text.insert(
                    tk.END, " Update operation completed.\n"
                )
            except Exception as e:
                self.handle_printer_error(e)
        else:
            self.status_text.insert(tk.END, '[WARNING]', "warn")
            self.status_text.insert(
                tk.END,
                f" Change of 'First TI received time' aborted.\n",
            )
        self.config(cursor="")
        self.update_idletasks()

    def mac_to_int_list(self, mac):
        # Remove any dashes if present, then split the MAC address into 2-character chunks
        mac = mac.replace('-', '')
        try:
            mac_list = [int(mac[i:i+2], 16) for i in range(0, len(mac), 2)]
        except Exception:
            return None
        if len(mac_list) != 6:
            return None
        return mac_list

    def validate_ser_number(self, new_value):
        # Regular expression for a valid serial number (10 uppercase or numeric characters)
        ser_pattern = re.compile(r'^[A-Z0-9]{10}$')
        if ser_pattern.match(new_value) or new_value == "":
            return True
        else:
            return False

    def validate_mac_address(self, new_value):
        # Regular expression for a valid MAC address (6 groups of 2 hexadecimal digits)
        mac_pattern = re.compile(r'^([0-9A-Fa-f]{2}[-:]?){5}([0-9A-Fa-f]{2})?$')
        if mac_pattern.match(new_value) or new_value == "":
            return True
        else:
            return False

    def validate_number_input(self, new_value):
        # This function will be called with the new input value
        if new_value == "" or new_value.isdigit():
            return True
        else:
            return False

    def show_status_text_view(self):
        """Show the status frame and hide the Treeview."""
        self.tree_frame.grid_remove()
        self.status_text.grid()

    def show_treeview(self):
        """Show the Treeview and hide the status frame."""
        self.status_text.grid_remove()
        self.tree_frame.grid()

    def printer_status(self, cursor=True):
        if cursor:
            self.config(cursor="watch")
            self.update()
            current_function_name = inspect.stack()[0][3]
            method_to_call = getattr(self, current_function_name)
            self.after(100, lambda: method_to_call(cursor=False))
            return
        self.show_status_text_view()
        model = self.model_var.get()
        ip_address = self.ip_var.get()
        if not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END,
                " Please enter a valid IP address, or "
                "press 'Detect Printers'.\n"
            )
            self.config(cursor="")
            self.update_idletasks()
            return
        printer = EpsonPrinter(
            conf_dict=self.conf_dict,
            replace_conf=self.replace_conf,
            model=model,
            hostname=ip_address
        )
        if not printer:
            return
        try:
            self.text_dump = black.format_str(
                f'"{printer.model}": ' + repr(printer.stats()), mode=self.mode
            )
            self.show_treeview()

            # Configure tags
            self.tree.tag_configure("key", foreground="black")
            self.tree.tag_configure("key_value", foreground="dark blue")
            self.tree.tag_configure("value", foreground="blue")
            self.tree.heading("#0", text="Status Information", anchor="w")

            # Populate the Treeview
            self.tree.delete(*self.tree.get_children())
            self.populate_treeview("", self.tree, printer.stats())

            # Expand all nodes
            self.expand_all(self.tree)
        except Exception as e:
            self.handle_printer_error(e)
        finally:
            self.config(cursor="")
            self.update_idletasks()

    def reset_printer_model(self):
        self.show_status_text_view()
        if self.model_var.get():
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END,
                ' Unknown printer model '
                f'"{self.model_var.get()}"\n',
            )
        else:
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END,
                ' Select a valid printer model.\n'
            )
        self.config(cursor="")
        self.update()
        self.model_var.set("")
    
    def printer_config(self, cursor=True):
        """
        Pressing F2 dumps the printer configuration
        """
        model = self.model_var.get()
        printer = EpsonPrinter(
            conf_dict=self.conf_dict,
            replace_conf=self.replace_conf,
            model=model
        )
        if not printer:
            return
        if not printer.parm:
            self.reset_printer_model()
            return
        try:
            self.text_dump = black.format_str(  # used by Copy All
                f'"{printer.model}": ' + repr(printer.parm),
                mode=self.mode
            )
            self.show_treeview()

            # Configure tags
            self.tree.tag_configure("key", foreground="black")
            self.tree.tag_configure("key_value", foreground="dark blue")
            self.tree.tag_configure("value", foreground="blue")
            self.tree.heading("#0", text="Printer parameters", anchor="w")

            # Populate the Treeview
            self.tree.delete(*self.tree.get_children())
            self.populate_treeview("", self.tree, printer.parm)

            # Expand all nodes
            self.expand_all(self.tree)
        except Exception as e:
            self.handle_printer_error(e)
        finally:
            self.update_idletasks()

    def key_values(self, cursor=True):
        """
        Pressing F3 gets the values of the keys from the printer configuration
        """
        model = self.model_var.get()
        printer = EpsonPrinter(
            conf_dict=self.conf_dict,
            replace_conf=self.replace_conf,
            model=model
        )
        if not printer:
            return
        if not printer.parm:
            self.reset_printer_model()
            return
        try:
            key_data = {
                "Printer model": printer.model,
                "Read sequence":
                    '.'.join(str(x) for x in printer.parm.get('read_key', [])),
                "Hex read sequence":
                    " ".join(
                        '{0:02x}'.format(x)
                        for x in printer.parm.get('read_key', [])
                    ),
                "Value of the 'write_key'":
                    printer.parm.get("write_key", b''),
                "Write string":
                    "".join(
                        chr(b + 1) for b in printer.parm.get("write_key", b'')
                    ),
                "Write sequence":
                    printer.caesar(printer.parm.get("write_key", b'')),
                "Hex write sequence":
                    printer.caesar(
                        printer.parm.get("write_key", b''), hex=True
                    ).upper(),
                "OID - Read address 0":
                    printer.eeprom_oid_read_address(0),
                "OID - Write value 0 to address 0":
                    printer.eeprom_oid_write_address(0, 0),
            }

            self.text_dump = black.format_str(  # used by Copy All
                f'"{printer.model}": ' + repr(key_data),
                mode=self.mode
            )
            self.show_treeview()

            # Configure tags
            self.tree.tag_configure("key", foreground="black")
            self.tree.tag_configure("key_value", foreground="dark blue")
            self.tree.tag_configure("value", foreground="blue")
            self.tree.heading(
                "#0",
                text="Values of the keys from the printer configuration",
                anchor="w"
            )

            # Populate the Treeview
            self.tree.delete(*self.tree.get_children())
            self.populate_treeview("", self.tree, key_data)

            # Expand all nodes
            self.expand_all(self.tree)
        except Exception as e:
            self.handle_printer_error(e)
        finally:
            self.update_idletasks()

    def read_eeprom(self):
        def parse_list_input(input_str):
            try:
                # Remove any character before ":" if not including digits
                colon_index = input_str.find(':')
                if colon_index != -1 and not any(
                    char.isdigit() for char in input_str[:colon_index]
                ):
                    input_str = input_str[colon_index + 1:]

                # Remove any unwanted characters like brackets, if present
                input_str = input_str.strip('{}[]()')

                # Remove trailing ".", if present
                input_str = input_str.rstrip('.')

                parts = input_str.split(',')
                addresses = []
                for part in parts:
                    part = part.strip()
                    if '-' in part:
                        # Handle range like '2-10'
                        start, end = map(int, part.split('-'))
                        addresses.extend(range(start, end + 1))  # Generate sequence between start and end
                    else:
                        # Handle individual addresses
                        addresses.append(int(part))
                return addresses
            except ValueError:
                # Show an error if the input is not valid
                messagebox.showerror(
                    "Invalid Input for Read EEPROM",
                    "Please enter a valid list of integers."
                )
                return None

        def get_input():
            # Create a popup to accept the list input
            dialog = MultiLineInputDialog(
                self,
                "Read EEPROM values",
                "Enter a comma-separated list of addresses to\n"
                "be read (e.g. 22, 23, 59 or [171, 170, 169, 168]).\n"
                "Use hyphen to represent a range (e.g., 1, 3-10, 13):"
            )
            if dialog.result:
                addresses = parse_list_input(dialog.result)
                if addresses:
                    return addresses
            return None

        def get_values(addresses):
            try:
                values = ', '.join(
                    "" if v is None else f"{k}: {int(v, 16)}" for k, v in zip(
                        addresses,
                        self.printer.read_eeprom_many(
                            addresses,
                            label="read_EEPROM"
                        )
                    )
                )
            except Exception as e:
                self.handle_printer_error(e)
                self.config(cursor="")
                self.update_idletasks()
                return
            if values:
                self.status_text.insert(tk.END, '[INFO]', "info")
                self.status_text.insert(
                    tk.END,
                    f" EEPROM values: {values}.\n"
                )
            else:
                self.status_text.insert(tk.END, '[ERROR]', "error")
                self.status_text.insert(
                    tk.END,
                    f' Cannot read EEPROM values for addresses "{addresses}"'
                    ' invalid printer model selected.\n'
                )
            self.config(cursor="")
            self.update_idletasks()

        self.show_status_text_view()
        ip_address = self.ip_var.get()
        if not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update_idletasks()
            return
        addresses = get_input()
        if addresses is not None:
            self.config(cursor="watch")
            self.update()
            self.after(100, lambda: get_values(addresses))

    def detect_access_key(self):
        def run_detection():
            """
            Process:
            - detect the read_key
            - extract the serial number
            - use the last character of the serial number to validate the write_key
            - produce an ordered list of all the known write_key
            - validate the write_key against any of the known values
            """
            current_log_level = logging.getLogger().getEffectiveLevel()
            logging.getLogger().setLevel(logging.ERROR)
            if not self._is_valid_ip(ip_address):
                self.status_text.insert(tk.END, '[ERROR]', "error")
                self.status_text.insert(tk.END, NO_CONF_ERROR)
                logging.getLogger().setLevel(current_log_level)
                self.config(cursor="")
                self.update_idletasks()
                return
            if not self.printer:
                self.printer = EpsonPrinter(
                    conf_dict=self.conf_dict,
                    hostname=self.ip_var.get()
                )
                self.printer.parm = {'read_key': None}

            # Detect the read_key
            self.status_text.insert(tk.END, '[INFO]', "info")
            self.status_text.insert(
                tk.END,
                f" Detecting the read_key...\n"
            )
            self.update_idletasks()
            read_key = None
            try:
                read_key = self.printer.brute_force_read_key()
            except Exception as e:
                self.handle_printer_error(e)
                logging.getLogger().setLevel(current_log_level)
                self.config(cursor="")
                self.update_idletasks()
                return
            if read_key:
                self.status_text.insert(tk.END, '[INFO]', "info")
                self.status_text.insert(
                    tk.END, f" Detected read_key: {read_key}.\n"
                )
            else:
                self.status_text.insert(tk.END, '[ERROR]', "error")
                self.status_text.insert(
                    tk.END, f" Could not detect read_key.\n"
                )
                logging.getLogger().setLevel(current_log_level)
                self.config(cursor="")
                self.update_idletasks()
                return

            # Extract the serial number
            DETECTED = "DETECTED"
            self.printer.PRINTER_CONFIG[DETECTED] = {}
            self.update_idletasks()
            len_ser_num = 10
            last_ser_num_addr = None
            if (
                self.printer.parm
                and 'read_key' in self.printer.parm
                and self.printer.parm['read_key'] != read_key
            ):
                if self.printer.parm['read_key']:
                    self.status_text.insert(tk.END, '[ERROR]', "error")
                    self.status_text.insert(
                        tk.END,
                        f" You selected a model with the wrong read_key "
                        f"{self.printer.parm['read_key']} instead of "
                        f"{read_key}. Using the detected one to go on.\n"
                    )
                self.printer.PRINTER_CONFIG[DETECTED] = {'read_key': read_key}
                self.printer.parm = self.printer.PRINTER_CONFIG[DETECTED]
            self.status_text.insert(tk.END, '[INFO]', "info")
            self.status_text.insert(
                tk.END,
                f" Detecting the serial number...\n"
            )
            try:
                hex_bytes, matches = self.printer.find_serial_number(
                    range(2048)
                )
            except Exception as e:
                self.handle_printer_error(e)
                logging.getLogger().setLevel(current_log_level)
                self.config(cursor="")
                self.update_idletasks()
                return
            if not matches:
                self.status_text.insert(tk.END, '[ERROR]', "error")
                self.status_text.insert(
                    tk.END,
                    f" Cannot detect the serial number.\n"
                )
            left_ser_num = None
            for match in matches:
                tmp_ser_num = match.group()
                if left_ser_num is not None and tmp_ser_num != left_ser_num:
                    self.status_text.insert(tk.END, '[ERROR]', "error")
                    self.status_text.insert(
                        tk.END,
                        " More than one pattern appears to be"
                        " a serial number with different values:\n"
                    )
                    for match in matches:
                        self.status_text.insert(tk.END, '[ERROR]', "error")
                        self.status_text.insert(
                            tk.END,
                            f' - found pattern "{match.group()}"'
                            f" at address {match.start()}\n"
                        )
                    left_ser_num = None
                    break
                left_ser_num = tmp_ser_num
            if left_ser_num:
                for match in matches:
                    serial_number = match.group()
                    serial_number_address = match.start()
                    serial_number_range = range(
                        serial_number_address,
                        serial_number_address + len_ser_num
                    )
                    self.status_text.insert(tk.END, '[INFO]', "info")
                    self.status_text.insert(
                        tk.END,
                        f' Detected serial number "{serial_number}"'
                        f" at address {serial_number_address}.\n"
                    )
                last_ser_num_addr = serial_number_address + len_ser_num - 1
                last_ser_num_value = int(hex_bytes[last_ser_num_addr], 16)
                self.status_text.insert(tk.END, '[NOTE]', "note")
                self.status_text.insert(
                    tk.END,
                    f" Current EEPROM value for the last byte of the"
                    f" serial number:"
                    f" {last_ser_num_addr}: {last_ser_num_value}.\n"
                )

            if last_ser_num_addr is None:
                self.status_text.insert(tk.END, '[ERROR]', "error")
                self.status_text.insert(
                    tk.END,
                    " Could not detect serial number.\n"
                )
                logging.getLogger().setLevel(current_log_level)
                self.config(cursor="")
                self.update_idletasks()
                return
            if (
                'serial_number' not in self.printer.parm
                or self.printer.parm['serial_number'] != serial_number_range
            ):
                if 'serial_number' in self.printer.parm:
                    self.status_text.insert(tk.END, '[ERROR]', "error")
                    self.status_text.insert(
                        tk.END,
                        f" The serial number addresses"
                        f" {self.printer.parm['serial_number']} of the"
                        f" selected printer is different from the detected"
                        f" one {serial_number_range},"
                        f" which will be used to go on.\n"
                    )
                self.printer.PRINTER_CONFIG[DETECTED] = {'read_key': read_key}
                self.printer.PRINTER_CONFIG[DETECTED]["serial_number"] = (
                    serial_number_range
                )
                self.printer.parm = self.printer.PRINTER_CONFIG[DETECTED]

            # Produce an ordered list of all the known write_key
            write_key_list = self.printer.write_key_list(read_key)

            # Validate the write_key against any of the known values
            self.status_text.insert(tk.END, '[INFO]', "info")
            self.status_text.insert(
                tk.END,
                " Detecting the write_key,"
                " do not power off the printer now...\n"
            )
            old_write_key = self.printer.parm.get('write_key')
            found_write_key = None
            valid = False
            for write_key in write_key_list:
                self.printer.parm['write_key'] = write_key
                try:
                    valid = self.printer.validate_write_key(
                        last_ser_num_addr,
                        last_ser_num_value,
                        label="test_write_eeprom"
                    )
                    assert valid is not None
                except AssertionError:
                    self.status_text.insert(tk.END, '[ERROR]', "error")
                    self.status_text.insert(
                        tk.END,
                        " Write operation failed. Check whether the"
                        " serial number is changed and restore it manually.\n"
                    )
                    self.printer.parm['write_key'] = old_write_key
                    logging.getLogger().setLevel(current_log_level)
                    self.config(cursor="")
                    self.update_idletasks()
                    return
                except Exception as e:
                    self.handle_printer_error(e)
                    self.printer.parm['write_key'] = old_write_key
                    logging.getLogger().setLevel(current_log_level)
                    self.config(cursor="")
                    self.update_idletasks()
                    return
                if valid is None:
                    self.status_text.insert(tk.END, '[ERROR]', "error")
                    self.status_text.insert(
                        tk.END, " Operation interrupted with errors.\n"
                    )
                    self.printer.parm['write_key'] = old_write_key
                    logging.getLogger().setLevel(current_log_level)
                    self.config(cursor="")
                    self.update_idletasks()
                    return
                if valid is False:
                    continue

                found_write_key = write_key
                self.printer.parm['write_key'] = old_write_key
                self.status_text.insert(tk.END, '[INFO]', "info")
                self.status_text.insert(
                    tk.END, f" Detected write_key: {found_write_key}\n"
                )
                if not old_write_key or old_write_key != found_write_key:
                    if old_write_key and old_write_key != found_write_key:
                        self.status_text.insert(tk.END, '[ERROR]', "error")
                        self.status_text.insert(
                            tk.END,
                            f" The selected write key {old_write_key}"
                            f" is different from the detected one, which will"
                            f" be used to go on.\n"
                        )
                    self.printer.PRINTER_CONFIG[DETECTED] = {
                        'read_key': read_key
                    }
                    self.printer.PRINTER_CONFIG[DETECTED]["serial_number"] = (
                        serial_number_range
                    )
                    self.printer.PRINTER_CONFIG[DETECTED]["write_key"] = (
                        found_write_key
                    )
                    self.printer.parm = self.printer.PRINTER_CONFIG[DETECTED]

                # List conforming models
                rk_kist = []
                wk_kist = []
                rwk_kist = []
                for p, v in self.printer.PRINTER_CONFIG.items():
                    if not p or not v or p == DETECTED:
                        continue
                    if v.get("read_key") == read_key:
                        rk_kist.append(p)
                    if v.get("write_key") == found_write_key:
                        wk_kist.append(p)
                    if (
                        v.get("read_key") == read_key
                        and v.get("write_key") == found_write_key
                    ):
                        rwk_kist.append(p)
                if rk_kist:
                    self.status_text.insert(tk.END, '[INFO]', "info")
                    self.status_text.insert(
                        tk.END,
                        f" Models with same read_key: {rk_kist}\n"
                    )
                if wk_kist:
                    self.status_text.insert(tk.END, '[INFO]', "info")
                    self.status_text.insert(
                        tk.END,
                        f" Models with same write_key: {wk_kist}\n"
                    )
                if rwk_kist:
                    self.status_text.insert(tk.END, '[INFO]', "info")
                    self.status_text.insert(
                        tk.END,
                        f" Models with same access keys: {rwk_kist}\n"
                    )

                if (
                    DETECTED in self.printer.PRINTER_CONFIG
                    and self.printer.PRINTER_CONFIG[DETECTED]
                ):
                    self.status_text.insert(tk.END, '[INFO]', "info")
                    self.status_text.insert(
                        tk.END,
                        f' Found data: '
                        f'{self.printer.PRINTER_CONFIG[DETECTED]}.\n'
                    )
                self.detect_configuration_button.state(["!disabled"])
                self.clean_nozzles_button.state(["!disabled"])
                self.print_tests_button.state(["!disabled"])
                self.temp_reset_ink_waste_button.state(["!disabled"])
                self.status_text.insert(tk.END, '[INFO]', "info")
                self.status_text.insert(
                    tk.END, " Detect operation completed.\n"
                )
                break
            if not found_write_key:
                self.status_text.insert(tk.END, '[ERROR]', "error")
                self.status_text.insert(
                    tk.END,
                    " Unable to detect the write key by validating"
                    " against any of the known ones.\n"
                )
            logging.getLogger().setLevel(current_log_level)
            self.config(cursor="")
            self.update_idletasks()

        # Confirmation message
        self.show_status_text_view()
        ip_address = self.ip_var.get()
        if not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            return
        response = messagebox.askyesno(
            "Detect Access Keys - Confirm Action",
            "Warning: this is a brute force operation, which takes several\n"
            "minutes to complete.\n\n"
            "Results will be shown in the status box.\n\n"
            "Make sure not to switch off the printer while the process"
            " is running and disable the auto power-off timer.\n\n"
            "Are you sure you want to proceed?",
            default='no'
        )
        if response:
            self.status_text.insert(tk.END, '[INFO]', "info")
            self.status_text.insert(
                tk.END,
                f" Starting the access key detection, please wait for many minutes...\n"
            )
            self.config(cursor="watch")
            self.update()
            self.after(100, lambda: run_detection())
        else:
            self.status_text.insert(tk.END, '[WARNING]', "warn")
            self.status_text.insert(
                tk.END, f" Detect access key aborted.\n"
            )
            self.config(cursor="")
            self.update_idletasks()

    def set_cursor(self, widget, cursor_type):
        widget.config(cursor=cursor_type)
        for child in widget.winfo_children():
            self.set_cursor(child, cursor_type)

    def web_interface(self, cursor=True):
        if cursor:
            self.config(cursor="watch")
            self.update()
            current_function_name = inspect.stack()[0][3]
            method_to_call = getattr(self, current_function_name)
            self.after(100, lambda: method_to_call(cursor=False))
            return
        self.show_status_text_view()
        ip_address = self.ip_var.get()
        if not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update()
            return
        if not self.printer:
            return
        try:
            ret = webbrowser.open(ip_address)
            if ret:
                self.status_text.insert(tk.END, '[INFO]', "info")
                self.status_text.insert(
                    tk.END, f" The browser is being opened.\n"
                )
            else:
                self.status_text.insert(tk.END, '[ERROR]', "error")
                self.status_text.insert(
                    tk.END, f" Cannot open browser.\n"
                )
        except Exception as e:
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END, f" Cannot open web browser: {e}\n"
            )
        finally:
            self.config(cursor="")
            self.update_idletasks()

    def print_tests(self) -> None:
        """
        Print nozzle, Print color, Print paper pass and Print paper feed tests.
        """
        options = [
            "Print standard nozzle test",  # 0
            "Print alternative nozzle test",  # 1
            "Color test pattern (for XP-200 range)",  # 2
            "Advance paper of one or n lines",  # 3
            "Feed one or more sheets",  # 4
        ]

        def get_test_dialog():
            dialog = tk.Toplevel(self)
            dialog.title("Print Test Options")
            dialog.transient(self)
            dialog.grab_set()
            dialog.focus_force()

            # Test selection
            ttk.Label(dialog, text="Select test:").grid(
                row=0, column=0, padx=10, pady=(10, 5), sticky="w"
            )
            combo_var = tk.StringVar(value=options[0])
            combo = ttk.Combobox(
                dialog,
                textvariable=combo_var,
                values=options,
                state="readonly",
                width=35
            )
            combo.current(0)
            combo.grid(row=0, column=1, padx=10)

            # Number of tests
            spin_label = ttk.Label(dialog, text="Number of tests:")
            spin_label.grid(row=1, column=0, padx=10, pady=5, sticky="w")
            num_tests_var = tk.IntVar(value=1)
            spin = ttk.Spinbox(
                dialog, from_=1, to=999, textvariable=num_tests_var, width=5
            )
            spin.grid(row=1, column=1, padx=10, pady=10, sticky="w")

            # Disable num test entry for first two tests
            def on_combo_change(event=None) -> None:
                if combo.current() < 3:
                    spin.state(["disabled"])
                    spin_label.state(["disabled"])
                else:
                    spin.state(["!disabled"])
                    spin_label.state(["!disabled"])

            combo.bind('<<ComboboxSelected>>', on_combo_change)
            on_combo_change()

            # Buttons
            result: dict[str, tuple[int, int] | None] = {"value": None}
            def on_confirm(event=None) -> None:
                idx = combo.current()
                result["value"] = (idx, num_tests_var.get())
                dialog.destroy()

            def on_cancel(event=None) -> None:
                dialog.destroy()

            frame = ttk.Frame(dialog)
            frame.grid(
                row=2, column=0, columnspan=2, pady=(5, 10), padx=10, sticky="ew"
            )
            frame.columnconfigure((0, 1), weight=1)
            ttk.Button(frame, text="Confirm", command=on_confirm).grid(
                row=0, column=0, padx=(0, 5), sticky="ew"
            )
            ttk.Button(frame, text="Cancel", command=on_cancel).grid(
                row=0, column=1, sticky="ew"
            )

            # Key bindings
            dialog.bind('<Return>', on_confirm)
            dialog.bind('<Escape>', on_cancel)

            # Center
            dialog.update_idletasks()
            w, h = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
            x = self.winfo_x() + (self.winfo_width() - w) // 2
            y = self.winfo_y() + (self.winfo_height() - h) // 2
            dialog.geometry(f"{w}x{h}+{x}+{y}")

            dialog.wait_window()
            return result["value"]

        def run_tests(index: int, num_tests: int) -> None:
            if index == 0:
                self.printer.check_nozzles(type=0)
                self.set_cursor(self, '')
                self.update_idletasks()
                return
            if index == 1:
                self.printer.check_nozzles(type=1)
                self.set_cursor(self, '')
                self.update_idletasks()
                return
            if index == 2:
                self.printer.print_test_color_pattern()
                self.set_cursor(self, '')
                self.update_idletasks()
                return
            try:
                with LprClient(
                    self.ip_var.get(), port="LPR", label="Print tests"
                ) as client:
                    payload = (
                        client.EXIT_PACKET_MODE
                        + client.INITIALIZE_PRINTER
                        + f"{options[index]} for {num_tests} tests\n".encode()
                        + client.FF
                    )
                    if index == 3:
                        payload = bytes.fromhex("0d 0a") * num_tests
                    if index == 4:
                        payload = (
                            client.INITIALIZE_PRINTER
                            + bytes.fromhex("0d 0a")
                            + client.FF
                            + client.INITIALIZE_PRINTER
                        ) * num_tests
                    client.send(payload)
            except Exception:
                self.show_status_text_view()
                self.status_text.insert(
                    tk.END, '[ERROR] Printer unreachable or offline.\n', 'error'
                )
            finally:
                self.set_cursor(self, '')
                self.update_idletasks()

        ip = self.ip_var.get()
        if not self._is_valid_ip(ip):
            self.status_text.insert(
                tk.END, '[ERROR] Invalid IP address.\n', 'error'
            )
            self.set_cursor(self, '')
            return

        if not self.printer:
            return

        result = get_test_dialog()
        if result is None:
            self.status_text.insert(
                tk.END, '[WARNING] Print test aborted by user.\n', 'warn'
            )
            self.set_cursor(self, '')
            return

        test_index, num_tests = result
        self.set_cursor(self, 'watch')
        self.after(100, lambda: run_tests(test_index, num_tests))

    def clean_nozzles(self):
        """
        Initiates nozzles cleaning routine with optional power clean.
        Displays a dialog to select a nozzle group and power clean option.
        """

        def show_clean_dialog():
            # Define groups
            groups = [
                "Clean all nozzles",  # 0
                "Clean the black ink nozzle",  # 1
                "Clean the color ink nozzles",  # 2
                "Head cleaning (alternative mode)",  # 3
            ]

            # Create modal dialog
            dialog = tk.Toplevel(self)
            dialog.title("Clean Nozzles Options")
            dialog.transient(self)
            dialog.grab_set()
            dialog.focus_force()

            introduction = (
                'The printer performs nozzles cleaning by flushing excess ink '
                'through the nozzles.'
            )
            tk.Label(
                dialog,
                text=introduction,
                wraplength=400,
                justify='left',
                foreground='gray30'
            ).pack(padx=10)

            # Label
            tk.Label(dialog, text="Select Nozzle Group:").pack(
                padx=10, pady=(10, 0)
            )

            # Compute width in characters for combobox
            max_len = max(len(item) for item in groups)
            combo_var = tk.StringVar()
            combo = ttk.Combobox(
                dialog,
                textvariable=combo_var,
                values=groups,
                state="readonly",
                width=max_len
            )
            combo.current(0)
            combo.configure(justify='center')  # Center the displayed text in the combobox
            combo.pack(padx=10, pady=5)
            combo.pack(padx=10, pady=5)
            combo.focus_set()

            note = (
                'The default action is to clean all nozzles.\n'
                'The clean black/color ink nozzles might not be supported on your printer.'
            )
            tk.Label(
                dialog,
                text=note,
                wraplength=400,
                justify='left',
                foreground='gray30'
            ).pack(padx=10, pady=(10, 5))

            # Checkbutton for power clean
            power_var = tk.BooleanVar(value=False)
            chk = ttk.Checkbutton(
                dialog, text="Power Clean", variable=power_var
            )
            chk.pack(padx=10, pady=5)

            # Warning message for power clean ink usage
            warning_text = (
                "Power Clean uses a significant amount of ink "
                "to flush the nozzles, "
                "and more rapidly fills the internal waste ink tank, "
                "which collects "
                "the excess ink used during the cleaning process."
            )
            msg = tk.Message(
                dialog,
                text=warning_text, width=(max_len+2)*8,
                foreground='gray30'
            )
            msg.pack(padx=10, pady=(2, 5))

            # Container for buttons
            btn_frame = ttk.Frame(dialog)
            btn_frame.pack(padx=10, pady=(5, 10), fill=tk.X)
            btn_frame.columnconfigure((0, 1), weight=1)

            result = {'value': None}

            def on_confirm(event=None):
                sel = combo.current()
                if sel < 0:
                    return
                result['value'] = (sel, power_var.get())
                dialog.destroy()

            def on_cancel(event=None):
                dialog.destroy()

            # Confirm and Cancel buttons
            confirm_btn = ttk.Button(
                btn_frame, text="Confirm", command=on_confirm
            )
            cancel_btn = ttk.Button(
                btn_frame, text="Cancel", command=on_cancel
            )
            confirm_btn.grid(row=0, column=0, sticky=tk.EW, padx=(0, 5))
            cancel_btn.grid(row=0, column=1, sticky=tk.EW)

            # Highlight Cancel as default and bind keys
            cancel_btn.focus_set()
            dialog.bind('<Return>', on_confirm)
            dialog.bind('<Escape>', on_cancel)

            # Center dialog
            dialog.update_idletasks()
            w = dialog.winfo_reqwidth()
            h = dialog.winfo_reqheight()
            x = self.winfo_x() + (self.winfo_width() - w) // 2
            y = self.winfo_y() + (self.winfo_height() - h) // 2
            dialog.geometry(f"{w}x{h}+{x}+{y}")

            dialog.wait_window()
            return result['value']

        def run_cleaning(group_index, power_clean, has_alt_mode=None):
            try:
                ret = self.printer.clean_nozzles(
                    group_index, power_clean, has_alt_mode
                )
            except Exception as e:
                self.status_text.insert(tk.END, '[ERROR]', "error")
                self.status_text.insert(
                    tk.END, f" Clean nozzless failure: {e}\n"
                )
            if ret is None:
                self.status_text.insert(tk.END, '[ERROR]', "error")
                self.status_text.insert(
                    tk.END, f" clean_nozzles internal error.\n"
                )
            elif ret is False:
                self.status_text.insert(tk.END, '[ERROR]', "error")
                self.status_text.insert(
                    tk.END, f" Printer is unreachable or offline.\n"
                )
            else:
                self.status_text.insert(tk.END, '[INFO]', "info")
                self.status_text.insert(tk.END,
                    f" Initiated cleaning of nozzles."
                    #f" Selected procedure: {group_index}, {power_clean}, {has_alt_mode}"
                    f"\n"
                )
            self.set_cursor(self, "")
            self.update_idletasks()

        ip_address = self.ip_var.get()
        if not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.set_cursor(self, "")
            self.update_idletasks()
            return

        if not self.printer:
            return

        # Call the dialog
        selection = show_clean_dialog()
        if selection is None:
            self.status_text.insert(tk.END, '[WARNING]', "warn")
            self.status_text.insert(
                tk.END,
                f" Nozzles cleaning operation aborted.\n"
            )
            self.set_cursor(self, "")
            self.update_idletasks()
            return  # User cancelled

        group_index, power_clean = selection

        self.set_cursor(self, "watch")
        self.update_idletasks()
        self.after(
            100,
            lambda: run_cleaning(group_index, power_clean, has_alt_mode=3)
        )

    def detect_configuration(self, cursor=True):
        def detect_sequence(eeprom, sequence):
            seq_len = len(sequence)
            addresses = []
            
            # Loop through all possible starting positions
            for address in range(len(eeprom) - seq_len + 1):
                # Check if the sequence matches starting at the current address
                if all(eeprom[address + i] == sequence[i] for i in range(seq_len)):
                    addresses.append(address)
            
            return addresses

        if cursor:
            self.config(cursor="watch")
            self.update()
            current_function_name = inspect.stack()[0][3]
            method_to_call = getattr(self, current_function_name)
            self.after(100, lambda: method_to_call(cursor=False))
            return
        self.show_status_text_view()
        ip_address = self.ip_var.get()
        if not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update()
            return
        if not self.printer:
            return
        self.status_text.insert(tk.END, '[INFO]', "info")
        self.status_text.insert(
            tk.END,
            f" Reading Printer SNMP values...\n"
        )
        try:
            stats = self.printer.stats()
        except Exception as e:
            self.handle_printer_error(e)
            self.config(cursor="")
            self.update_idletasks()
            return False
        if not "snmp_info" in stats:
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END,
                ' No SNMP values could be found.\n'
            )
            self.update()
            self.config(cursor="")
            self.update_idletasks()
            return False
        self.status_text.insert(tk.END, '[INFO]', "info")
        self.status_text.insert(
            tk.END,
            f" Reading EEPROM values, please wait for some minutes...\n"
        )
        self.update()
        try:
            addr = range(0, 2048)
            eeprom = {
                k: None if v == None else int(v, 16) for k, v in zip(
                    addr,
                    self.printer.read_eeprom_many(
                        addr, label="dump_EEPROM"
                    )
                )
            }
            if not eeprom or eeprom == {0: None}:
                self.status_text.insert(tk.END, '[ERROR]', "error")
                self.status_text.insert(
                    tk.END,
                    ' Cannot read EEPROM values: invalid printer model selected.\n'
                )
                self.update()
                self.config(cursor="")
                self.update_idletasks()
                return False
        except Exception as e:
            self.handle_printer_error(e)
            self.config(cursor="")
            self.update_idletasks()
            return False
        self.status_text.insert(tk.END, '[INFO]', "info")
        self.status_text.insert(
            tk.END,
            f" Analyzing EEPROM values...\n"
        )
        self.update()

        conf_data = {}

        epson_name = [  # convert EPSON to a sequence of numbers, adding 0 after each char
            val for char in "EPSON" for val in (ord(char), 0)
        ]
        epson_name.extend([0] * (64 - len(epson_name)))  # pad to zero until 32 chars

        result = detect_sequence(eeprom, epson_name)
        c = 0
        for i in result:
            conf_data["brand_name[%s]" % c] = range(i, i + 64)
            c += 1

        if "Model" in stats["snmp_info"] and stats["snmp_info"]["Model"]:
            model_name = [
                val for char in stats["snmp_info"]["Model"] for val in (ord(char), 0)
            ]
            model_name.extend([0] * (64 - len(model_name)))
            result = detect_sequence(eeprom, model_name)
            c = 0
            for i in result:
                conf_data["model_name[%s]" % c] = range(i, i + 64)
                c += 1
        else:
            conf_data["model_name"] = None

        sequence = ''.join([chr(eeprom[addr]) for addr in range(len(eeprom))])
        serial_number_pattern = r'[A-Z0-9]{10}'  # Serial number pattern (10 consecutive uppercase letters or digits)
        c = 0
        for i in re.finditer(serial_number_pattern, sequence):
            conf_data["serial_name[%s]" % c] = i.group()
            conf_data["serial_number[%s]" % c] = range(i.start(), i.end())
            c += 1

        if "Power Off Timer" in stats["snmp_info"] and stats["snmp_info"]["Power Off Timer"]:
            matches = re.findall(r'\d+', stats["snmp_info"]["Power Off Timer"])
            if matches:
                po_mins = int(matches[0])
                msb = po_mins // 256
                lsb = po_mins % 256
                result = detect_sequence(eeprom, (lsb, msb))
                c = 0
                for i in result:
                    conf_data["po_time[%s]" % c] = [i + 1, i]
                    c += 1
            else:
                conf_data["po_time"] = None
        else:
            conf_data["po_time"] = None

        result = detect_sequence(eeprom, [94])
        c = 0
        for i in result:
            conf_data["Maintenance required level[%s]" % c] = [i]
            c += 1

        if "MAC Address" in stats["snmp_info"] and stats["snmp_info"]["MAC Address"]:
            mac = self.mac_to_int_list(stats["snmp_info"]["MAC Address"])
            result = detect_sequence(eeprom, mac)
            c = 0
            for i in result:
                conf_data["wifi_mac_address[%s]" % c] = range(i, i + 6)
                c += 1
        else:
            conf_data["wifi_mac_address"] = None

        if self.printer and self.printer.parm:
            if "read_key" in self.printer.parm:
                conf_data["read_key"] = self.printer.parm["read_key"]
            if "write_key" in self.printer.parm:
                conf_data["write_key"] = self.printer.parm["write_key"]
        try:
            self.text_dump = black.format_str(  # used by Copy All
                '"Printer configuration": ' + repr(conf_data),
                mode=self.mode
            )
            self.show_treeview()

            # Configure tags
            self.tree.tag_configure("key", foreground="black")
            self.tree.tag_configure("key_value", foreground="dark blue")
            self.tree.tag_configure("value", foreground="blue")
            self.tree.heading(
                "#0",
                text="Printer configuration",
                anchor="w"
            )

            # Populate the Treeview
            self.tree.delete(*self.tree.get_children())
            self.populate_treeview("", self.tree, conf_data)

            # Expand all nodes
            self.expand_all(self.tree)
        except Exception as e:
            self.handle_printer_error(e)
        finally:
            self.status_text.insert(tk.END, '[INFO]', "info")
            self.status_text.insert(
                tk.END,
                f" Operation completed.\n"
            )
            self.update_idletasks()
            self.config(cursor="")
            self.update_idletasks()

    def write_eeprom(self):
        def parse_dict_input(input_str):
            try:
                # Remove any character before ":" if not including digits
                colon_index = input_str.find(':')
                if colon_index != -1 and not any(
                    char.isdigit() for char in input_str[:colon_index]
                ):
                    input_str = input_str[colon_index + 1:]

                # Remove any unwanted characters like brackets, if present
                input_str = input_str.strip('{}[]()')

                # Remove trailing ".", if present
                input_str = input_str.rstrip('.')

                parts = input_str.split(',')
                result_dict = {}
                for part in parts:
                    part = part.strip()
                    if ':' not in part:
                        raise ValueError()
                    # Handle key: value pairs
                    key, value = map(str.strip, part.split(':', 1))
                    result_dict[int(key)] = int(value)
                return result_dict
            except ValueError:
                messagebox.showerror(
                    "Invalid input for Write EEPROM",
                    "Please enter a valid comma-separated sequence "
                    "of 'address: value', like 24: 0, 25: 0, 30: 0 "
                    "using decimal numbers."
                )
                return {}

        def get_input():
            # Create a popup to accept the dictionary input
            dialog = MultiLineInputDialog(
                self,
                "Write EEPROM values",
                "Warning: this is a dangerous operation.\nContinue only "
                "if you are very sure of what you do.\n\n"
                "Enter a comma-separated sequence of 'address: value'\n"
                "(like 24: 0, 25: 0, 30: 0) using decimal numbers:"
            )
            if dialog.result:
                dict_addr_val = parse_dict_input(dialog.result)
                if dict_addr_val:
                    return dict_addr_val
            return None

        def dialog_write_values(dict_addr_val):
            try:
                if not self.get_current_eeprom_values(
                    dict_addr_val.keys(),
                    "the entered addresses"
                ):
                    self.config(cursor="")
                    self.update_idletasks()
                    return
            except Exception as e:
                self.handle_printer_error(e)
                self.config(cursor="")
                self.update_idletasks()
                return
            self.config(cursor="")
            self.update_idletasks()
            response = messagebox.askyesno(*CONFIRM_MESSAGE, default='no')
            if response:
                self.config(cursor="watch")
                self.update()
                self.after(200, lambda: write_eeprom_values(dict_addr_val))
            else:
                self.status_text.insert(tk.END, '[WARNING]', "warn")
                self.status_text.insert(
                    tk.END, f" Write EEPROM aborted.\n"
                )
                self.config(cursor="")
                self.update_idletasks()

        def write_eeprom_values(dict_addr_val):
            try:
                for oid, value in dict_addr_val.items():
                    if not self.printer.write_eeprom(
                        oid, value, label="write_eeprom"
                    ):
                        return False
            except Exception as e:
                self.handle_printer_error(e)
            self.status_text.insert(tk.END, '[INFO]', "info")
            self.status_text.insert(
                tk.END, f" Write EEPROM completed.\n"
            )
            self.config(cursor="")
            self.update_idletasks()

        self.show_status_text_view()
        ip_address = self.ip_var.get()
        if not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            return
        dict_addr_val = get_input()
        if dict_addr_val is not None:
            self.config(cursor="watch")
            self.update()
            self.status_text.insert(tk.END, '[INFO]', "info")
            self.status_text.insert(
                tk.END, f" Going to write EEPROM: {dict_addr_val}.\n"
            )
            self.after(200, lambda: dialog_write_values(dict_addr_val))

    def reset_waste_ink(self, cursor=True):
        if cursor:
            self.config(cursor="watch")
            self.update()
            current_function_name = inspect.stack()[0][3]
            method_to_call = getattr(self, current_function_name)
            self.after(100, lambda: method_to_call(cursor=False))
            return
        msg = (
            "Reset Waste Ink Levels - Confirm Action",
            "This feature permanently resets the ink waste tank full counters."
            "\n\nAlways replace the waste ink pads before "
            "continuing. Carefully monitor the ink flow and "
            "consider risks of ink overflow into printer internals and "
            "also environmental contamination that possibly cannot be cleaned."
            "\n\nAre you sure you want to proceed?"
        )
        response = messagebox.askyesno(*msg, default='no')
        if not response:
            self.status_text.insert(tk.END, '[WARNING]', "warn")
            self.status_text.insert(
                tk.END, f" Waste ink levels reset aborted.\n"
            )
            self.config(cursor="")
            self.update_idletasks()
            return
        self.show_status_text_view()
        ip_address = self.ip_var.get()
        if (
            not self._is_valid_ip(ip_address)
            or not self.printer
            or not self.printer.parm
            or "read_key" not in self.printer.parm
            or "write_key" not in self.printer.parm
        ):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update_idletasks()
            return
        try:
            if "raw_waste_reset" in self.printer.parm:
                if not self.get_current_eeprom_values(
                    self.printer.parm["raw_waste_reset"].keys(),
                    "Raw waste reset"
                ):
                    self.config(cursor="")
                    self.update_idletasks()
                    return
            for i in self.printer.parm:
                if i.endswith("_waste") and "oids" in self.printer.parm[i]:
                    if not self.get_current_eeprom_values(
                        self.printer.parm[i]["oids"],
                        i.replace("_", " ").capitalize()
                    ):
                        self.config(cursor="")
                        self.update_idletasks()
                        return
        except Exception as e:
            self.handle_printer_error(e)
            self.config(cursor="")
            self.update_idletasks()
            return
        response = messagebox.askyesno(*CONFIRM_MESSAGE, default='no')
        if not self.printer:
            return
        if response:
            try:
                self.printer.reset_waste_ink_levels()
                self.status_text.insert(tk.END, '[INFO]', "info")
                self.status_text.insert(
                    tk.END,
                    " Waste ink levels have been reset."
                    " Perform a power cycle of the printer now.\n"
                )
            except Exception as e:
                self.handle_printer_error(e)
        else:
            self.status_text.insert(tk.END, '[WARNING]', "warn")
            self.status_text.insert(
                tk.END, f" Waste ink levels reset aborted.\n"
            )
        self.config(cursor="")
        self.update_idletasks()

    def temp_reset_waste_ink(self, cursor=True):
        if cursor:
            self.config(cursor="watch")
            self.update()
            current_function_name = inspect.stack()[0][3]
            method_to_call = getattr(self, current_function_name)
            self.after(100, lambda: method_to_call(cursor=False))
            return
        self.show_status_text_view()
        ip_address = self.ip_var.get()
        if (
            not self._is_valid_ip(ip_address)
            or not self.printer
            or not self.printer.parm
            or "read_key" not in self.printer.parm
            or "write_key" not in self.printer.parm
        ):
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update_idletasks()
            return
        if not self.printer:
            return
        msg = (
            "Temporary Bypass of the Waste Ink Lock - Confirm Action",
            "This feature temporarily bypasses the ink waste tank full"
            "  message, which would otherwise disable printing. "
            "\n\nThis setting does not persist a reboot. "
            "\n\nAlways replace the waste ink pads before "
            "continuing. Carefully monitor the ink flow and "
            "consider risks of ink overflow into printer internals and "
            "also environmental contamination that possibly cannot be cleaned."
            "\n\nAre you sure you want to proceed?"
        )
        response = messagebox.askyesno(*msg, default='no')
        if response:
            try:
                if self.printer.temporary_reset_waste():
                    self.status_text.insert(tk.END, '[INFO]', "info")
                    self.status_text.insert(
                        tk.END,
                        " Waste ink levels have been temporarily bypassed."
                        " You can now print.\n"
                    )
                else:
                    self.status_text.insert(tk.END, '[ERROR]', "error")
                    self.status_text.insert(
                        tk.END,
                        " Failed to perform the temporary bypass of the "
                        "waste ink levels."
                    )
            except Exception as e:
                self.handle_printer_error(e)
        else:
            self.status_text.insert(tk.END, '[WARNING]', "warn")
            self.status_text.insert(
                tk.END,
                " Temporary bypass of the waste ink levels aborted.\n"
            )
        self.config(cursor="")
        self.update_idletasks()

    def start_detect_printers(self):
        self.show_status_text_view()
        self.status_text.insert(tk.END, '[INFO]', "info")
        self.status_text.insert(
            tk.END, " Detecting printers... (this might take a while)\n"
        )

        # run printer detection in new thread, as it can take a while
        threading.Thread(target=self.detect_printers_thread).start()

    def detect_printers_thread(self, cursor=True):
        if cursor:
            self.config(cursor="watch")
            self.update()
            current_function_name = inspect.stack()[0][3]
            method_to_call = getattr(self, current_function_name)
            self.after(100, lambda: method_to_call(cursor=False))
            return
        self.detect_button.config(state=tk.DISABLED)  # disable button while processing
        self.show_status_text_view()
        try:
            # [{'ip': '...', 'hostname': '...', 'name': '...'}]
            printers = self.printer_scanner.get_all_printers(
                self.ip_var.get().strip()
            )
            if len(printers) > 0:
                if len(printers) == 1 and printers[0]['name'] != None:
                    self.status_text.insert(tk.END, '[INFO]', "info")
                    self.status_text.insert(
                        tk.END,
                        f" Found printer '{printers[0]['name']}' "
                        f"at {printers[0]['ip']} "
                        f"(hostname: {printers[0]['hostname']})\n",
                    )
                    self.ip_var.set(printers[0]["ip"])
                    for model in get_printer_models(printers[0]["name"]):
                        if model in EpsonPrinter(
                            conf_dict=self.conf_dict,
                            replace_conf=self.replace_conf
                        ).valid_printers:
                            self.model_var.set(model)
                            break
                    if self.model_var.get() == "":
                        self.status_text.insert(tk.END, '[ERROR]', "error")
                        self.status_text.insert(
                            tk.END,
                            f' Printer model unknown.\n'
                        )
                        self.model_var.set("")
                else:
                    self.status_text.insert(tk.END, '[INFO]', "info")
                    self.status_text.insert(
                        tk.END, f" Found {len(printers)} printers:\n"
                    )
                    for printer in printers:
                        if printers[0]['name']:
                            self.status_text.insert(tk.END, '[INFO]', "info")
                            self.status_text.insert(
                                tk.END,
                                f" {printer['name']} found at {printer['ip']}"
                                f" (hostname: {printer['hostname']})\n",
                            )
                        else:
                            self.status_text.insert(tk.END, '[WARN]', "warn")
                            self.status_text.insert(
                                tk.END,
                                f" Cannot contact printer {printer['ip']}"
                                f" (hostname: {printer['hostname']}).\n",
                            )
            else:
                self.status_text.insert(tk.END, '[WARN]', "warn")
                self.status_text.insert(tk.END, " No printers found.\n")
        except Exception as e:
            self.handle_printer_error(e)
        finally:
            self.detect_button.config(state=tk.NORMAL)  # enable button after processing
            self.config(cursor="")
            self.update_idletasks()

    def _is_valid_ip(self, ip):
        try:
            ip = ipaddress.ip_address(ip)
            return True
        except ValueError:
            return False

    def is_simple_type(self, data):
        return isinstance(data, (str, int, float, bool))

    def contains_parentheses(self, data):
        """Check if a string representation contains parentheses."""
        if isinstance(data, (list, tuple, set)):
            for item in data:
                if isinstance(item, (tuple, list, set)):
                    return True
                if isinstance(item, str) and ("(" in item or ")" in item):
                    return True
        return False

    def populate_treeview(self, parent, treeview, data):
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, (dict, list, set, tuple)):
                    node = treeview.insert(
                        parent, "end", text=key, tags=("key",)
                    )
                    self.populate_treeview(node, treeview, value)
                else:
                    treeview.insert(
                        parent,
                        "end",
                        text=f"{key}: {value}",
                        tags=("key_value"),
                    )
        elif isinstance(data, list):
            if all(
                self.is_simple_type(item) for item in data
            ) and not self.contains_parentheses(data):
                treeview.insert(
                    parent,
                    "end",
                    text=", ".join(map(str, data)),
                    tags=("value",),
                )
            else:
                for item in data:
                    if isinstance(item, (dict, list, set, tuple)):
                        self.populate_treeview(parent, treeview, item)
                    else:
                        treeview.insert(
                            parent, "end", text=str(item), tags=("value",)
                        )
        elif isinstance(data, set):
            if not self.contains_parentheses(data):
                treeview.insert(
                    parent,
                    "end",
                    text=", ".join(map(str, data)),
                    tags=("value",),
                )
            else:
                for item in data:
                    treeview.insert(
                        parent, "end", text=str(item), tags=("value",)
                    )
        elif isinstance(data, tuple):
            treeview.insert(parent, "end", text=str(data), tags=("value",))
        else:
            treeview.insert(parent, "end", text=str(data), tags=("value",))

    def expand_all(self, treeview):
        def recursive_expand(item):
            treeview.item(item, open=True)
            children = treeview.get_children(item)
            for child in children:
                recursive_expand(child)

        root_children = treeview.get_children()
        for child in root_children:
            recursive_expand(child)

    def show_text_context_menu(self, event):
        """Show the context menu of the text box."""
        self.text_context_menu.post(event.x_root, event.y_root)

    def clear_all_text(self):
        # Clear all the text in the ScrolledText
        self.status_text.delete("1.0", tk.END)  # Delete all text from the widget

    def copy_text(self):
        # Copy the selected text
        self.status_text.event_generate("<<Copy>>")

    def copy_all_text(self):
        # Copy all the text in the ScrolledText
        self.clipboard_clear()
        self.clipboard_append(self.status_text.get("1.0", tk.END))  # Get all text from the widget
        self.update()  # Ensure clipboard updates

    def show_context_menu(self, event):
        """Show the context menu."""
        # Select the item under the cursor
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)
        else:
            self.context_menu.post(event.x_root, event.y_root)

    def copy_selected_item(self):
        """Copy the selected Treeview item text to the clipboard."""
        selected_item = self.tree.selection()
        if selected_item:
            item_text = self.tree.item(selected_item[0], "text")
            self.clipboard_clear()
            self.clipboard_append(item_text)

    def copy_all_items(self):
        """Copy all items to the clipboard."""
        self.clipboard_clear()
        self.clipboard_append(self.text_dump)

    def print_items(self, text):
        """Send items to the printer."""
        ip_address = self.ip_var.get()
        if not self._is_valid_ip(ip_address):
            self.show_status_text_view()
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END, f" Missing IP address or printer host name.\n"
            )
            return
        try:
            with LprClient(ip_address, port="LPR", label="Print items") as lpr:
                lpr.send(
                    lpr.EXIT_PACKET_MODE
                    + lpr.INITIALIZE_PRINTER
                    + b"Printer configuration\n"
                    + text.encode('utf-8')
                    + lpr.FF
                )
        except Exception as e:
            self.show_status_text_view()
            self.status_text.insert(tk.END, '[ERROR]', "error")
            self.status_text.insert(
                tk.END, f" Printer is unreachable or offline.\n"
            )


def main():
    import argparse
    import pickle

    parser = argparse.ArgumentParser(
        epilog='Epson Printer Configuration GUI'
    )
    parser.add_argument(
        '-m',
        '--model',
        dest='model',
        action="store",
        help='Printer model. Example: -m XP-205',
        default=None
    )
    parser.add_argument(
        '-a',
        '--address',
        dest='hostname',
        action="store",
        help='Printer host name or IP address. (Example: -a 192.168.1.87)',
        default=None
    )
    parser.add_argument(
        '-P',
        "--pickle",
        dest='pickle',
        type=argparse.FileType('rb'),
        help="Load a pickle configuration archive saved by parse_devices.py",
        default=None,
        nargs=1,
        metavar='PICKLE_FILE'
    )
    parser.add_argument(
        '-O',
        "--override",
        dest='override',
        action='store_true',
        help="Replace the default configuration with the one in the pickle "
            "file instead of merging (default is to merge)",
    )
    parser.add_argument(
        '-d',
        '--debug',
        dest='debug',
        action='store_true',
        help='Print debug information'
    )
    args = parser.parse_args()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    conf_dict = {}
    if args.pickle:
        try:
            conf_dict = pickle.load(args.pickle[0])
        except Exception as e:
            if not args.pickle[0].tell():
                print("Error. Empty PICKLE FILE.")
            else:
                print("Error. Cannot load PICKLE FILE:", e)
            quit()

    return EpsonPrinterUI(
        model=args.model,
        hostname=args.hostname,        
        conf_dict=conf_dict,
        replace_conf=args.override
    )


if __name__ == "__main__":
    try:
        main().mainloop()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)

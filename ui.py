#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Epson Printer Configuration via SNMP (TCP/IP) - GUI
"""

import sys
import re
import threading
import ipaddress
import inspect
from datetime import datetime
import socket
import traceback
import logging
import webbrowser

import black
import tkinter as tk
from tkinter import ttk, Menu
from tkinter.scrolledtext import ScrolledText
import tkinter.font as tkfont
from tkcalendar import DateEntry  # Ensure you have: pip install tkcalendar
from tkinter import simpledialog, messagebox

import pyperclip
from epson_print_conf import EpsonPrinter
from find_printers import PrinterScanner


VERSION = "3.0"

NO_CONF_ERROR = (
    "[ERROR] Please select a printer model and a valid IP address,"
    " or press 'Detect Printers'.\n"
)

CONFIRM_MESSAGE = (
            "Confirm Action",
            "Please copy and save the codes in the [NOTE] shown on the screen."
            " They can be used to restore the initial configuration"
            " in case of problems.\n\n"
            "Are you sure you want to proceed?"
)

def get_printer_models(input_string):
    # Tokenize the string
    tokens = re.split(" |/", input_string)
    if not len(tokens):
        return []

    # Define the words to remove (uppercase, then case insensitive)
    remove_tokens = {"EPSON", "SERIES"}

    # Process tokens
    processed_tokens = []
    non_numeric_part = ""
    pre_model = ""
    for token in tokens:
        upper_token = token.upper()

        # Remove tokens that match remove_tokens
        if any(word == upper_token for word in remove_tokens):
            continue
        if not any(char.isdigit() for char in token):  # no alphanum inside
            pre_model = pre_model + token + " "
            continue
        # Identify the non-numeric part of the first token
        if not token.isnumeric() and not non_numeric_part:
            non_numeric_part = "".join(c for c in token if not c.isdigit())
        # if token is numeric, prepend the non-numeric part
        if token.isnumeric():
            processed_tokens.append(f"{pre_model}{non_numeric_part}{token}")
        else:
            processed_tokens.append(f"{pre_model}{token}")
    if not processed_tokens and pre_model:
        processed_tokens.append(pre_model.strip())
    return processed_tokens


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
        conf_dict={},
        replace_conf=False
        ):
        super().__init__()
        self.title("Epson Printer Configuration - v" + VERSION)
        self.geometry("500x500")
        self.minsize(500, 500)
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

        FRAME_PAD = 10
        PAD = (3, 0)
        PADX = 4
        PADY = 5

        # main Frame
        main_frame = ttk.Frame(self, padding=FRAME_PAD)
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(4, weight=1)  # Number of rows
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
            "Select the model of the printer, or press 'Detect Printers'.\n"
            "Press F2 to dump the parameters associated to the printer model.",
        )
        self.model_dropdown.bind("<F2>", self.printer_config)

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
        self.ip_entry.bind("<F2>", self.next_ip)
        ToolTip(
            self.ip_entry,
            "Enter the IP address, or press 'Detect Printers'"
            " (you can also enter part of the IP address"
            " to speed up the detection),"
            " or press F2 more times to get the next local IP address,"
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

        # [row 2] Query Buttons
        row_n += 1
        button_frame = ttk.Frame(main_frame, padding=PAD)
        button_frame.grid(row=row_n, column=0, pady=PADY, sticky=(tk.W, tk.E))
        button_frame.columnconfigure((0, 1, 2), weight=1)  # expand columns

        # Query Printer Status
        self.status_button = ttk.Button(
            button_frame, text="Printer Status",
            command=self.printer_status,
            style="Centered.TButton"
        )
        self.status_button.grid(
            row=0, column=0, padx=PADX, pady=PADY, sticky=(tk.W, tk.E)
        )

        # Query list of cartridge types
        self.web_interface_button = ttk.Button(
            button_frame,
            text="Printer Web interface",
            command=self.web_interface,
            style="Centered.TButton"
        )
        self.web_interface_button.grid(
            row=0, column=1, padx=PADX, pady=PADX, sticky=(tk.W, tk.E)
        )

        # Query firmware version
        self.firmware_version_button = ttk.Button(
            button_frame,
            text="Firmware version",
            command=self.firmware_version,
            style="Centered.TButton"
        )
        self.firmware_version_button.grid(
            row=0, column=2, padx=PADX, pady=PADX, sticky=(tk.W, tk.E)
        )

        # [row 3] Tweak Buttons
        row_n += 1
        tweak_frame = ttk.Frame(main_frame, padding=PAD)
        tweak_frame.grid(row=row_n, column=0, pady=PADY, sticky=(tk.W, tk.E))
        tweak_frame.columnconfigure((0, 1, 2, 3, 4), weight=1)  # expand columns

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

        # Read EEPROM
        self.read_eeprom_button = ttk.Button(
            tweak_frame,
            text="Read\nEEPROM",
            command=self.read_eeprom,
            style="Centered.TButton"
        )
        self.read_eeprom_button.grid(
            row=0, column=2, padx=PADX, pady=PADX, sticky=(tk.W, tk.E)
        )

        # Write EEPROM
        self.write_eeprom_button = ttk.Button(
            tweak_frame,
            text="Write\nEEPROM",
            command=self.write_eeprom,
            style="Centered.TButton"
        )
        self.write_eeprom_button.grid(
            row=0, column=3, padx=PADX, pady=PADX, sticky=(tk.W, tk.E)
        )

        # Reset Waste Ink Levels
        self.reset_button = ttk.Button(
            tweak_frame,
            text="Reset Waste\nInk Levels",
            command=self.reset_waste_ink,
            style="Centered.TButton"
        )
        self.reset_button.grid(
            row=0, column=4, padx=PADX, pady=PADX, sticky=(tk.W, tk.E)
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
            label="Print all items", command=self.print_items
        )

        # Bind the right-click event to the Treeview
        self.tree.bind("<Button-3>", self.show_context_menu)

        # Hide the Treeview initially
        self.tree_frame.grid_remove()

        self.model_var.trace('w', self.change_widget_states)
        self.ip_var.trace('w', self.change_widget_states)
        self.change_widget_states()

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
        ToolTip(self.read_eeprom_button, "")
        ToolTip(self.write_eeprom_button, "")
        ToolTip(self.reset_button, "")
        if self.ip_var.get():
            if not self.model_var.get():
                self.reset_button.state(["disabled"])
            self.status_button.state(["!disabled"])
            self.firmware_version_button.state(["!disabled"])
            self.web_interface_button.state(["!disabled"])
            self.detect_access_key_button.state(["!disabled"])
            self.printer = None
        else:
            self.reset_button.state(["disabled"])
            self.status_button.state(["disabled"])
            self.read_eeprom_button.state(["disabled"])
            self.write_eeprom_button.state(["disabled"])
            self.firmware_version_button.state(["disabled"])
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
            self.write_eeprom_button.state(["disabled"])
            ToolTip(
                self.write_eeprom_button,
                "Feature not defined in the printer configuration."
            )
            if self.printer and self.printer.parm:
                if "read_key" in self.printer.parm:
                    self.read_eeprom_button.state(["!disabled"])
                    ToolTip(self.read_eeprom_button, "")
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
            self.write_eeprom_button.state(["disabled"])

            self.po_timer_entry.state(["disabled"])
            self.get_po_minutes.state(["disabled"])
            self.set_po_minutes.state(["disabled"])

            self.date_entry.state(["disabled"])
            self.get_ti_received.state(["disabled"])
            self.set_ti_received.state(["disabled"])

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
            self.status_text.insert(
                tk.END, f"[ERROR] printer is unreachable or offline.\n"
            )
        else:
            self.status_text.insert(
                tk.END, f"[ERROR] {e}\n{traceback.format_exc()}\n"
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
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update()
            return
        if not self.printer:
            return
        if not self.printer.parm.get("stats", {}).get("Power off timer"):
            self.status_text.insert(
                tk.END,
                f"[ERROR]: Missing 'Power off timer' in configuration\n",
            )
            self.config(cursor="")
            self.update_idletasks()
            return
        try:
            po_timer = self.printer.stats()["stats"]["Power off timer"]
            self.status_text.insert(
                tk.END, f"[INFO] Power off timer: {po_timer} minutes.\n"
            )
            self.po_timer_var.set(po_timer)
        except Exception as e:
            self.handle_printer_error(e)
        finally:
            self.config(cursor="")
            self.update_idletasks()

    def get_current_eeprom_values(self, values, label):
        try:
            org_values = ', '.join(
                "" if v is None else f"{k}: {int(v, 16)}" for k, v in zip(
                    values, self.printer.read_eeprom_many(values, label=label)
                )
            )
            if org_values:
                self.status_text.insert(
                    tk.END,
                    f"[NOTE] Current EEPROM values for {label}: {org_values}.\n"
                )
            else:
                self.status_text.insert(
                    tk.END,
                    f'[ERROR] Cannot read EEPROM values for "{label}"'
                    ': invalid printer model selected.\n'
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
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update_idletasks()
            return
        if not self.printer:
            return
        if not self.printer.parm.get("stats", {}).get("Power off timer"):
            self.status_text.insert(
                tk.END,
                f"[ERROR]: Missing 'Power off timer' in configuration\n",
            )
            self.config(cursor="")
            self.update_idletasks()
            return
        po_timer = self.po_timer_var.get()
        self.config(cursor="")
        self.update_idletasks()
        if not po_timer.isnumeric():
            self.status_text.insert(
                tk.END, "[ERROR] Please Use a valid value for minutes.\n"
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
        self.status_text.insert(
            tk.END, f"[INFO] Set Power off timer: {po_timer} minutes.\n"
        )
        response = messagebox.askyesno(*CONFIRM_MESSAGE, default='no')
        if response:
            try:
                self.printer.write_poweroff_timer(int(po_timer))
            except Exception as e:
                self.handle_printer_error(e)
        else:
            self.status_text.insert(
                tk.END, f"[WARNING] Set Power off timer aborted.\n"
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
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update_idletasks()
            return
        if not self.printer:
            return
        if not self.printer.parm.get("stats", {}).get("First TI received time"):
            self.status_text.insert(
                tk.END,
                f"[ERROR]: Missing 'First TI received time' in configuration\n",
            )
            self.config(cursor="")
            self.update_idletasks()
            return
        try:
            date_string = datetime.strptime(
                self.printer.stats(
                )["stats"]["First TI received time"], "%d %b %Y"
            ).strftime("%Y-%m-%d")
            self.status_text.insert(
                tk.END,
                f"[INFO] First TI received time (YYYY-MM-DD): {date_string}.\n",
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
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update_idletasks()
            return
        if not self.printer:
            return
        if not self.printer.parm.get("stats", {}).get("First TI received time"):
            self.status_text.insert(
                tk.END,
                f"[ERROR]: Missing 'First TI received time' in configuration\n",
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
        self.status_text.insert(
            tk.END,
            f"[INFO] Set 'First TI received time' (YYYY-MM-DD) to: "
            f"{date_string.strftime('%Y-%m-%d')}.\n",
        )
        response = messagebox.askyesno(*CONFIRM_MESSAGE, default='no')
        if response:
            try:
                self.printer.write_first_ti_received_time(
                    date_string.year, date_string.month, date_string.day
                )
            except Exception as e:
                self.handle_printer_error(e)
        else:
            self.status_text.insert(
                tk.END,
                f"[WARNING] Change of 'First TI received time' aborted.\n",
            )
        self.config(cursor="")
        self.update_idletasks()

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
            self.status_text.insert(
                tk.END,
                "[ERROR] Please enter a valid IP address, or "
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
            self.status_text.insert(
                tk.END,
                '[ERROR]: Unknown printer model '
                f'"{self.model_var.get()}"\n',
            )
        else:
            self.status_text.insert(
                tk.END,
                '[ERROR]: Select a valid printer model.\n'
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
            self.text_dump = black.format_str(
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
                self.status_text.insert(
                    tk.END,
                    f"[INFO] EEPROM values: {values}.\n"
                )
            else:
                self.status_text.insert(
                    tk.END,
                    f'[ERROR] Cannot read EEPROM values'
                    ': invalid printer model selected.\n'
                )
            self.config(cursor="")
            self.update_idletasks()

        self.show_status_text_view()
        ip_address = self.ip_var.get()
        if not self._is_valid_ip(ip_address):
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
                self.status_text.insert(tk.END, NO_CONF_ERROR)
                logging.getLogger().setLevel(current_log_level)
                self.config(cursor="")
                self.update_idletasks()
                return
            if not self.printer:
                self.printer = EpsonPrinter(
                    hostname=self.ip_var.get()
                )
                self.printer.parm = {'read_key': None}

            # Detect the read_key
            self.status_text.insert(
                tk.END,
                f"[INFO] Detecting the read_key...\n"
            )
            self.update_idletasks()
            read_key = None
            try:
                read_key = self.printer.brute_force_read_key()
                self.status_text.insert(
                    tk.END, f"[INFO] Detected read_key: {read_key}.\n"
                )
            except Exception as e:
                self.handle_printer_error(e)
                logging.getLogger().setLevel(current_log_level)
                self.config(cursor="")
                self.update_idletasks()
                return
            if not read_key:
                self.status_text.insert(
                    tk.END, f"[ERROR] Could not detect read_key.\n"
                )
                logging.getLogger().setLevel(current_log_level)
                self.config(cursor="")
                self.update_idletasks()
                return

            # Extract the serial number
            self.status_text.insert(
                tk.END,
                f"[INFO] Detecting the serial number...\n"
            )
            self.update_idletasks()
            last_ser_num_addr = None
            if not self.printer.parm:
                self.printer.parm = {'read_key': read_key}
            if (
                'read_key' not in self.printer.parm
                or self.printer.parm['read_key'] is None
            ):
                self.printer.parm['read_key'] = read_key
            if self.printer.parm['read_key'] != read_key:
                self.status_text.insert(
                    tk.END,
                    f"[INFO] You selected a model with the wrong read_key "
                    f"{self.printer.parm['read_key']} instead of "
                    f"{read_key}. Using the correct one now.\n"
                )
                self.printer.parm['read_key'] = read_key
            hex_bytes, matches = self.printer.find_serial_number(range(2048))
            if not matches:
                self.status_text.insert(
                    tk.END,
                    f"[ERROR] Cannot detect the serial number.\n"
                )
            elif len(matches) != 1:
                self.status_text.insert(
                    tk.END,
                    "[ERROR] More than one pattern appears to be"
                    " a serial number:\n"
                )
                for match in matches:
                    self.status_text.insert(
                        tk.END,
                        f'[ERROR] - found pattern "{match.group()}"'
                        f" at address {match.start()}\n"
                    )
            else:
                serial_number = matches[0].group()
                serial_number_address = matches[0].start()
                self.status_text.insert(
                    tk.END,
                    f'[INFO] Detected serial number "{serial_number}"'
                    f" at address {serial_number_address}.\n"
                )
                last_ser_num_addr = serial_number_address + 9
                last_ser_num_value = int(hex_bytes[last_ser_num_addr], 16)

            if last_ser_num_addr is None:
                self.status_text.insert(
                    tk.END,
                    "[ERROR] Could not detect serial number.\n"
                )
                logging.getLogger().setLevel(current_log_level)
                self.config(cursor="")
                self.update_idletasks()
                return

            # Produce an ordered list of all the known write_key
            write_key_list = self.printer.write_key_list(read_key)

            # Validate the write_key against any of the known values
            old_write_key = None
            if 'write_key' in self.printer.parm:
                old_write_key = self.printer.parm['write_key']
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
                    self.status_text.insert(
                        tk.END,
                        "[ERROR] Write operation failed. Check whether the"
                        " serial number is changed and restore it manually.\n"
                    )
                    self.config(cursor="")
                    self.update_idletasks()
                except Exception as e:
                    self.handle_printer_error(e)
                    logging.getLogger().setLevel(current_log_level)
                    self.config(cursor="")
                    self.update_idletasks()
                    return
                if valid is None:
                    self.status_text.insert(
                        tk.END, "[ERROR] Operation interrupted with errors.\n"
                    )
                    logging.getLogger().setLevel(current_log_level)
                    self.config(cursor="")
                    self.update_idletasks()
                    return
                if valid is False:
                    continue

                found_write_key = write_key
                self.status_text.insert(
                    tk.END, f"[INFO] Detected write_key: {found_write_key}\n"
                )
                if old_write_key and old_write_key != found_write_key:
                    self.status_text.insert(
                        tk.END,
                        f"[INFO] Found write key is different from"
                        f" the selected one: {old_write_key}\n"
                    )
                    self.printer.parm['write_key'] = old_write_key

                # List conforming models
                rk_kist = []
                wk_kist = []
                rwk_kist = []
                for p, v in self.printer.PRINTER_CONFIG.items():
                    if not v:
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
                    self.status_text.insert(
                        tk.END,
                        f"[INFO] Models with same read_key: {rk_kist}\n"
                    )
                if wk_kist:
                    self.status_text.insert(
                        tk.END,
                        f"[INFO] Models with same write_key: {wk_kist}\n"
                    )
                if rwk_kist:
                    self.status_text.insert(
                        tk.END,
                        f"[INFO] Models with same access keys: {rwk_kist}\n"
                    )

                self.status_text.insert(
                    tk.END, "[INFO] Detect operation completed.\n"
                )
                break
            if not found_write_key:
                self.status_text.insert(
                    tk.END,
                    "[ERROR] Unable to detect the write key by validating"
                    " against any of the known ones.\n"
                )
            logging.getLogger().setLevel(current_log_level)
            self.config(cursor="")
            self.update_idletasks()

        # Confirmation message
        self.show_status_text_view()
        ip_address = self.ip_var.get()
        if not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            return
        response = messagebox.askyesno(
            "Confirm Action",
            "Warning: this is a brute force operation, which takes several\n"
            "minutes to complete.\n\n"
            "Results will be shown in the status box.\n\n"
            "Make sure not to switch off the printer while the process"
            " is running and disable the auto power-off timer.\n\n"
            "Are you sure you want to proceed?",
            default='no'
        )
        if response:
            self.status_text.insert(
                tk.END, f"[INFO] Starting the operation, please wait...\n"
            )
            self.config(cursor="watch")
            self.update()
            self.after(100, lambda: run_detection())
        else:
            self.status_text.insert(
                tk.END, f"[WARNING] Detect access key aborted.\n"
            )
            self.config(cursor="")
            self.update_idletasks()

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
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update()
            return
        if not self.printer:
            return
        try:
            ret = webbrowser.open(ip_address)
            if ret:
                self.status_text.insert(
                    tk.END, f"[INFO] The browser is being opened.\n"
                )
            else:
                self.status_text.insert(
                    tk.END, f"[ERROR] Cannot open browser.\n"
                )
        except Exception as e:
            self.status_text.insert(
                tk.END, f"[ERROR] Cannot open web browser: {e}\n"
            )
        finally:
            self.config(cursor="")
            self.update_idletasks()

    def firmware_version(self, cursor=True):
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
            self.update()
            return
        if not self.printer:
            return
        try:
            firmware_version = self.printer.get_firmware_version()
            self.status_text.insert(
                tk.END, f"[INFO] Firmware version: {firmware_version}.\n"
            )
        except Exception as e:
            self.handle_printer_error(e)
        finally:
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
                self.status_text.insert(
                    tk.END, f"[WARNING] Write EEPROM aborted.\n"
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
            self.status_text.insert(
                tk.END, f"[INFO] Write EEPROM completed.\n"
            )
            self.config(cursor="")
            self.update_idletasks()

        self.show_status_text_view()
        ip_address = self.ip_var.get()
        if not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            return
        dict_addr_val = get_input()
        if dict_addr_val is not None:
            self.config(cursor="watch")
            self.update()
            self.status_text.insert(
                tk.END, f"[INFO] Going to write EEPROM: {dict_addr_val}.\n"
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
        self.show_status_text_view()
        ip_address = self.ip_var.get()
        if (
            not self._is_valid_ip(ip_address)
            or not self.printer
            or not self.printer.parm
            or "read_key" not in self.printer.parm
            or "write_key" not in self.printer.parm
        ):
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
                self.status_text.insert(
                    tk.END,
                    "[INFO] Waste ink levels have been reset."
                    " Perform a power cycle of the printer now.\n"
                )
            except Exception as e:
                self.handle_printer_error(e)
        else:
            self.status_text.insert(
                tk.END, f"[WARNING] Waste ink levels reset aborted.\n"
            )
        self.config(cursor="")
        self.update_idletasks()

    def start_detect_printers(self):
        self.show_status_text_view()
        self.status_text.insert(
            tk.END, "[INFO] Detecting printers... (this might take a while)\n"
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
            printers = self.printer_scanner.get_all_printers(
                self.ip_var.get().strip()
            )
            if len(printers) > 0:
                if len(printers) == 1:
                    self.status_text.insert(
                        tk.END,
                        f"[INFO] Found printer '{printers[0]['name']}' "
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
                        self.status_text.insert(
                            tk.END,
                            f'[ERROR] Printer model unknown.\n'
                        )
                        self.model_var.set("")
                else:
                    self.status_text.insert(
                        tk.END, f"[INFO] Found {len(printers)} printers:\n"
                    )
                    for printer in printers:
                        self.status_text.insert(
                            tk.END,
                            f"[INFO] {printer['name']} found at {printer['ip']}"
                            f" (hostname: {printer['hostname']})\n",
                        )
            else:
                self.status_text.insert(tk.END, "[WARN] No printers found.\n")
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

    def show_context_menu(self, event):
        """Show the context menu."""
        # Select the item under the cursor
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
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

    def print_items(self):
        """Send items to the printer."""
        exit_packet_mode = b'\x00\x00\x00\x1b\x01@EJL 1284.4\n@EJL     \n'
        initialize_printer = b"\x1B\x40"
        form_feed = b"\f"

        self.clipboard_append(self.text_dump)
        ip_address = self.ip_var.get()
        if not self._is_valid_ip(ip_address):
            return
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.connect((ip_address, 9100))
                sock.sendall(
                    exit_packet_mode
                    + initialize_printer
                    + b"Printer configuration\n"
                    + self.text_dump.encode('utf-8')
                    + form_feed
                )
        except Exception as e:
            self.handle_printer_error(e)


def main():
    import argparse
    import pickle

    parser = argparse.ArgumentParser(
        epilog='epson_print_conf GUI'
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
        conf_dict = pickle.load(args.pickle[0])

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

import re
import threading
import ipaddress
import inspect
from datetime import datetime

import tkinter as tk
from tkinter import ttk, Menu
from tkinter.scrolledtext import ScrolledText
import tkinter.font as tkfont
from tkcalendar import DateEntry  # Ensure you have: pip install tkcalendar
from tkinter import messagebox

import pyperclip
from epson_print_conf import EpsonPrinter
from find_printers import PrinterScanner


VERSION = "2.1"

NO_CONF_ERROR = (
    "[ERROR] Please select a printer model and a valid IP address, or press 'Detect Printers'.\n"
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


class ToolTip:
    def __init__(self, widget, text="widget info", wrap_length=10):
        self.widget = widget
        self.text = text
        self.wrap_length = wrap_length
        self.tooltip_window = None
        widget.bind("<Enter>", self.enter, "+")  # Show the tooltip on hover
        widget.bind("<Leave>", self.leave, "+")  # Hide the tooltip on leave
        widget.bind("<Button-1>", self.leave, "+")  # Hide tooltip on mouse click

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


class EpsonPrinterUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Epson Printer Configuration - v" + VERSION)
        self.geometry("450x500")
        self.minsize(450, 500)
        self.printer_scanner = PrinterScanner()
        self.ip_list = []
        self.ip_list_cycle = None

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
        main_frame.rowconfigure(3, weight=1)  # Number of rows
        row_n = 0

        # [row 0] Container frame for the two LabelFrames Power-off timer and TI Received Time
        model_ip_frame = ttk.Frame(main_frame, padding=PAD)
        model_ip_frame.grid(row=row_n, column=0, pady=PADY, sticky=(tk.W, tk.E))
        model_ip_frame.columnconfigure(0, weight=1)  # Allow column to expand
        model_ip_frame.columnconfigure(1, weight=1)  # Allow column to expand

        # printer model selection
        model_frame = ttk.LabelFrame(
            model_ip_frame, text="Printer Model", padding=PAD
        )
        model_frame.grid(
            row=0, column=0, pady=PADY, padx=(0, PADX), sticky=(tk.W, tk.E)
        )
        model_frame.columnconfigure(0, weight=0)
        model_frame.columnconfigure(1, weight=1)

        self.model_var = tk.StringVar()
        ttk.Label(model_frame, text="Model:").grid(
            row=0, column=0, sticky=tk.W, padx=PADX
        )
        self.model_dropdown = ttk.Combobox(
            model_frame, textvariable=self.model_var, state="readonly"
        )
        self.model_dropdown["values"] = sorted(EpsonPrinter().valid_printers)
        self.model_dropdown.grid(
            row=0, column=1, pady=PADY, padx=PADX, sticky=(tk.W, tk.E)
        )
        ToolTip(
            self.model_dropdown,
            "Select the model of the printer, or press 'Detect Printers'.",
        )

        # IP address entry
        ip_frame = ttk.LabelFrame(
            model_ip_frame, text="Printer IP Address", padding=PAD
        )
        ip_frame.grid(
            row=0, column=1, pady=PADY, padx=(PADX, 0), sticky=(tk.W, tk.E)
        )
        ip_frame.columnconfigure(0, weight=0)
        ip_frame.columnconfigure(1, weight=1)

        self.ip_var = tk.StringVar()
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
            "Enter the IP address, or press 'Detect Printers' (you can also enter part of the IP address to speed up the detection), or press F2 more times to get the next local IP address, which can then be edited (by removing the last part before pressing 'Detect Printers').",
        )

        # [row 1] Container frame for the two LabelFrames Power-off timer and TI Received Time
        row_n += 1
        container_frame = ttk.Frame(main_frame, padding=PAD)
        container_frame.grid(
            row=row_n, column=0, pady=PADY, sticky=(tk.W, tk.E)
        )
        container_frame.columnconfigure(0, weight=1)  # Allow column to expand
        container_frame.columnconfigure(1, weight=1)  # Allow column to expand

        # Power-off timer
        po_timer_frame = ttk.LabelFrame(
            container_frame, text="Power-off timer (minutes)", padding=PAD
        )
        po_timer_frame.grid(
            row=0, column=0, pady=PADY, padx=(0, PADX), sticky=(tk.W, tk.E)
        )
        po_timer_frame.columnconfigure(0, weight=0)  # Button column on the left
        po_timer_frame.columnconfigure(1, weight=1)  # Entry column
        po_timer_frame.columnconfigure(2, weight=0)  # Button column on the right

        # Configure validation command for numeric entry
        validate_cmd = self.register(self.validate_number_input)

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
        ToolTip(self.po_timer_entry, "Enter a number of minutes.")

        button_width = 7
        get_po_minutes = ttk.Button(
            po_timer_frame,
            text="Get",
            width=button_width,
            command=self.get_po_mins,
        )
        get_po_minutes.grid(row=0, column=0, padx=PADX, pady=PADY, sticky=tk.W)

        set_po_minutes = ttk.Button(
            po_timer_frame,
            text="Set",
            width=button_width,
            command=self.set_po_mins,
        )
        set_po_minutes.grid(row=0, column=2, padx=PADX, pady=PADY, sticky=tk.E)

        # TI Received Time
        ti_received_frame = ttk.LabelFrame(
            container_frame, text="TI Received Time (date)", padding=PAD
        )
        ti_received_frame.grid(
            row=0, column=1, pady=PADY, padx=(PADX, 0), sticky=(tk.W, tk.E)
        )
        ti_received_frame.columnconfigure(0, weight=0)  # Button column on the left
        ti_received_frame.columnconfigure(1, weight=1)  # Calendar column
        ti_received_frame.columnconfigure(2, weight=0)  # Button column on the right

        # TI Received Time Calendar Widget
        self.date_entry = DateEntry(
            ti_received_frame, date_pattern="yyyy-mm-dd"
        )
        self.date_entry.grid(
            row=0, column=1, padx=PADX, pady=PADY, sticky=(tk.W, tk.E)
        )
        self.date_entry.delete(0, "end")
        ToolTip(self.date_entry, "Enter a valid date with format YYYY-MM-DD.")

        # TI Received Time Buttons
        get_ti_received = ttk.Button(
            ti_received_frame,
            text="Get",
            width=button_width,
            command=self.get_ti_date,
        )
        get_ti_received.grid(row=0, column=0, padx=PADX, pady=PADY, sticky=tk.W)

        set_ti_received = ttk.Button(
            ti_received_frame,
            text="Set",
            width=button_width,
            command=self.set_ti_date,
        )
        set_ti_received.grid(row=0, column=2, padx=PADX, pady=PADY, sticky=tk.E)

        # [row 2] Buttons
        row_n += 1
        button_frame = ttk.Frame(main_frame, padding=PAD)
        button_frame.grid(row=row_n, column=0, pady=PADY, sticky=(tk.W, tk.E))
        button_frame.columnconfigure((0, 1, 2), weight=1)

        self.detect_button = ttk.Button(
            button_frame,
            text="Detect Printers",
            command=self.start_detect_printers,
        )
        self.detect_button.grid(
            row=0, column=0, padx=PADX, pady=PADX, sticky=(tk.W, tk.E)
        )

        self.status_button = ttk.Button(
            button_frame, text="Printer Status", command=self.printer_status
        )
        self.status_button.grid(
            row=0, column=1, padx=PADX, pady=PADY, sticky=(tk.W, tk.E)
        )

        self.reset_button = ttk.Button(
            button_frame,
            text="Reset Waste Ink Levels",
            command=self.reset_waste_ink,
        )
        self.reset_button.grid(
            row=0, column=2, padx=PADX, pady=PADX, sticky=(tk.W, tk.E)
        )

        # [row 3] Status display
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
        self.tree.heading("#0", text="Status Information", anchor="w")
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
            label="Copy", command=self.copy_selected_item
        )

        # Bind the right-click event to the Treeview
        self.tree.bind("<Button-3>", self.show_context_menu)

        # Hide the Treeview initially
        self.tree_frame.grid_remove()

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

    def get_po_mins(self, cursor=True):
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
        if not model or not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update()
            return
        printer = EpsonPrinter(model=model, hostname=ip_address)
        try:
            po_timer = printer.stats()["stats"]["Power off timer"]
            self.status_text.insert(
                tk.END, f"[INFO] Power off timer: {po_timer} minutes.\n"
            )
            self.po_timer_var.set(po_timer)
        except Exception as e:
            self.status_text.insert(
                tk.END,
                f"[ERROR] {e}: Missing 'Power off timer' in configuration\n",
            )
        finally:
            self.config(cursor="")
            self.update_idletasks()

    def set_po_mins(self, cursor=True):
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
        if not model or not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update_idletasks()
            return
        printer = EpsonPrinter(model=model, hostname=ip_address)
        try:
            po_timer = printer.stats()["stats"]["Power off timer"]
            po_timer = self.po_timer_var.get()
            self.config(cursor="")
            self.update_idletasks()
            if not po_timer.isnumeric():
                self.status_text.insert(
                    tk.END, "[ERROR] Please Use a valid value for minutes.\n"
                )
                return
            self.status_text.insert(
                tk.END, f"[INFO] Set Power off timer: {po_timer} minutes.\n"
            )
            response = messagebox.askyesno(
                "Confirm Action", "Are you sure you want to proceed?"
            )
            if response:
                printer.write_poweroff_timer(int(po_timer))
            else:
                self.status_text.insert(
                    tk.END, f"[WARNING] Set Power off timer aborted.\n"
                )
        except Exception as e:
            self.config(cursor="")
            self.update_idletasks()
            self.status_text.insert(
                tk.END,
                f"[ERROR] {e}: Cannot set 'Power off timer'; missing configuration\n",
            )

    def get_ti_date(self, cursor=True):
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
        if not model or not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update_idletasks()
            return
        printer = EpsonPrinter(model=model, hostname=ip_address)
        try:
            date_string = datetime.strptime(
                printer.stats()["stats"]["First TI received time"], "%d %b %Y"
            ).strftime("%Y-%m-%d")
            self.status_text.insert(
                tk.END,
                f"[INFO] First TI received time (YYYY-MM-DD): {date_string}.\n",
            )
            self.date_entry.set_date(date_string)
        except Exception as e:
            self.status_text.insert(
                tk.END,
                f"[ERROR] {e}: Missing 'First TI received time' in configuration\n",
            )
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
        model = self.model_var.get()
        ip_address = self.ip_var.get()
        if not model or not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update_idletasks()
            return
        printer = EpsonPrinter(model=model, hostname=ip_address)
        try:
            date_string = datetime.strptime(
                printer.stats()["stats"]["First TI received time"], "%d %b %Y"
            ).strftime("%y-%m-%d")
            date_string = self.date_entry.get_date()
            self.status_text.insert(
                tk.END,
                f"[INFO] Set 'First TI received time' (YYYY-MM-DD) to: {date_string.strftime('%Y-%m-%d')}.\n",
            )
            response = messagebox.askyesno(
                "Confirm Action", "Are you sure you want to proceed?"
            )
            if response:
                printer.write_first_ti_received_time(
                    date_string.year, date_string.month, date_string.day
                )
            else:
                self.status_text.insert(
                    tk.END,
                    f"[WARNING] Change of 'First TI received time' aborted.\n",
                )
        except Exception as e:
            self.status_text.insert(
                tk.END,
                f"[ERROR] {e}: Cannot set 'First TI received time'; missing configuration\n",
            )
        finally:
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
        if not model or not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update_idletasks()
            return
        printer = EpsonPrinter(model=model, hostname=ip_address)

        try:
            self.show_treeview()

            # Configure tags
            self.tree.tag_configure("key", foreground="black")
            self.tree.tag_configure("key_value", foreground="dark blue")
            self.tree.tag_configure("value", foreground="blue")

            # Populate the Treeview
            self.populate_treeview("", self.tree, printer.stats())

            # Expand all nodes
            self.expand_all(self.tree)
        except Exception as e:
            self.show_status_text_view()
            self.status_text.insert(tk.END, f"[ERROR] {e}\n")
        finally:
            self.config(cursor="")
            self.update_idletasks()

    def reset_waste_ink(self, cursor=True):
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
        if not model or not self._is_valid_ip(ip_address):
            self.status_text.insert(tk.END, NO_CONF_ERROR)
            self.config(cursor="")
            self.update_idletasks()
            return
        printer = EpsonPrinter(model=model, hostname=ip_address)
        try:
            printer.stats()  # query the printer first
            response = messagebox.askyesno(
                "Confirm Action", "Are you sure you want to proceed?"
            )
            if response:
                printer.reset_waste_ink_levels()
                self.status_text.insert(
                    tk.END, "[INFO] Waste ink levels have been reset.\n"
                )
            else:
                self.status_text.insert(
                    tk.END, f"[WARNING] Waste ink levels reset aborted.\n"
                )
        except Exception as e:
            self.status_text.insert(tk.END, f"[ERROR] {e}\n")
        finally:
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
                        f"[INFO] Found printer '{printers[0]['name']}' at {printers[0]['ip']} (hostname: {printers[0]['hostname']})\n",
                    )
                    self.ip_var.set(printers[0]["ip"])
                    for model in get_printer_models(printers[0]["name"]):
                        if model in EpsonPrinter().valid_printers:
                            self.model_var.set(model)
                            break
                else:
                    self.status_text.insert(
                        tk.END, f"[INFO] Found {len(printers)} printers:\n"
                    )
                    for printer in printers:
                        self.status_text.insert(
                            tk.END,
                            f"[INFO] {printer['name']} found at {printer['ip']} (hostname: {printer['hostname']})\n",
                        )
            else:
                self.status_text.insert(tk.END, "[WARN] No printers found.\n")
        except Exception as e:
            self.status_text.insert(tk.END, f"[ERROR] {e}\n")
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


if __name__ == "__main__":
    app = EpsonPrinterUI()
    app.mainloop()

import sys
import logging
import re
import xml.etree.ElementTree as ET
import itertools
import textwrap

from ui import get_printer_models

def to_ranges(iterable):
    iterable = sorted(set(iterable))
    for key, group in itertools.groupby(enumerate(iterable),
                                        lambda t: t[1] - t[0]):
        group = list(group)
        yield group[0][1], group[-1][1]


def text_to_bytes(text):
    l = [int(h, 16) for h in text.split()]
    r = list(to_ranges(l))
    if len(l) > 6 and len(r) == 1:
        return eval("range(%s, %s)" % (r[0][0], r[0][1]+1))
    return l


def text_to_dict(text):
    b = text_to_bytes(text)
    return {b[i]: b[i + 1] for i in range(0, len(b), 2)}


def traverse_data(element, depth=0):
    indent = '    ' * depth
    if element.tag and not element.attrib and element.text and element.text.strip():
        print(indent + element.tag + " = " + element.text)
    else:
        if element.tag:
            print(indent + element.tag + ":")
        if element.attrib:
            print(indent + '    Attributes:', element.attrib)
        if element.text and element.text.strip():
            print(indent + '    Text:', element.text.strip())
    
    # Recursively traverse the children
    for child in element:
        traverse_data(child, depth + 1)


def generate_config(config, traverse, add_fatal_errors, full, printer_model):
    waste_string = [
        "main_waste", "borderless_waste", "third_waste", "fourth_waste",
        "fifth_waste", "sixth_waste"
    ]
    irc_pattern = [
        r'Ink replacement counter %-% (\w+) % \((\w+)\)'
    ]
    tree = ET.parse(config)
    root = tree.getroot()
    printer_config = {}
    for printer in root.iterfind(".//printer"):
        title = printer.attrib.get("title", "")
        if printer_model and printer_model not in title:
            continue
        specs = printer.attrib["specs"].split(",")
        logging.info(
            "Tag: %s, Attributes: %s, Specs: %s",
            printer.tag, printer.attrib, printer.attrib['specs']
        )
        printer_short_name = printer.attrib["short"]
        printer_long_name = printer.attrib["title"]
        printer_model_name = printer.attrib["model"]
        chars = {}
        for spec in specs:
            logging.debug("SPEC: %s", spec)
            for elm in root.iterfind(".//" + spec):
                if traverse:
                    traverse_data(elm)
                for item in elm:
                    logging.debug("item.tag: %s", item.tag)
                    if elm.tag == 'EPSON' and item.tag == "status":
                        for st in item:
                            if full and st.tag == 'colors':
                                chars["ink_color_ids"] = {}
                                for color in st:
                                    if color.tag == 'color':
                                        color_code = ""
                                        color_name = ""
                                        for color_data in color:
                                            if color_data.tag == "code":
                                                color_code = color_data.text
                                            if color_data.tag == "name":
                                                color_name = color_data.text
                                        chars["ink_color_ids"][color_code] = color_name
                            if full and st.tag == 'states':
                                chars["status_ids"] = {}
                                for status_id in st:
                                    if status_id.tag == 'state':
                                        status_code = ""
                                        status_name = ""
                                        for status_data in status_id:
                                            if status_data.tag == "code":
                                                status_code = status_data.text
                                            if status_data.tag == "text":
                                                status_name = status_data.text
                                        chars["status_ids"][status_code] = status_name
                            if full and st.tag == 'errors':
                                chars["errcode_ids"] = {}
                                for error_id in st:
                                    if error_id.tag == 'error':
                                        error_code = ""
                                        error_name = ""
                                        for error_data in error_id:
                                            if error_data.tag == "code":
                                                error_code = error_data.text
                                            if error_data.tag == "text":
                                                error_name = error_data.text
                                        chars["errcode_ids"][error_code] = error_name
                    if item.tag == "information":
                        for info in item:
                            if info.tag == "report":
                                chars["stats"] = {}
                                fatal = []
                                irc = ""
                                for number in info:
                                    if number.tag == "fatals" and add_fatal_errors:
                                        for n in number:
                                            if n.tag == "registers":
                                                for j in text_to_bytes(n.text):
                                                    fatal.append(j)
                                        chars["last_printer_fatal_errors"] = (
                                            fatal
                                        )
                                    if number.tag in ["number", "period"]:
                                        stat_name = ""
                                        for n in number:
                                            if n.tag == "name":
                                                stat_name = n.text
                                            if (
                                                n.tag == "registers"
                                                and stat_name
                                            ):
                                                match = False
                                                for ircp in irc_pattern:
                                                    match = re.search(ircp, stat_name)
                                                    if match:
                                                        color = match.group(1)
                                                        identifier = f"{match.group(2)}"
                                                        if "ink_replacement_counters" not in chars:
                                                            chars["ink_replacement_counters"] = {}
                                                        if color not in chars["ink_replacement_counters"]:
                                                            chars["ink_replacement_counters"][color] = {}
                                                        chars["ink_replacement_counters"][color][identifier] = int(n.text, 16)
                                                        break
                                                if not match:
                                                    stat_name = stat_name.replace("% BL", "- Black")
                                                    stat_name = stat_name.replace("% CY", "- Cyan")
                                                    stat_name = stat_name.replace("% MG", "- Magenta")
                                                    stat_name = stat_name.replace("% YE", "- Yellow")
                                                    stat_name = stat_name.replace("%-%", "-")
                                                    chars["stats"][stat_name] = text_to_bytes(n.text)
                    if item.tag == "waste":
                        for operations in item:
                            if operations.tag == "reset":
                                chars["raw_waste_reset"] = text_to_dict(
                                    operations.text
                                )
                            if operations.tag == "query":
                                count = 0
                                for counter in operations:
                                    waste = {}
                                    for ncounter in counter:
                                        if ncounter.tag == "entry":
                                            if "oids" in waste:
                                                waste["oids"] += text_to_bytes(
                                                    ncounter.text
                                                )
                                            else:
                                                waste["oids"] = text_to_bytes(
                                                    ncounter.text
                                                )
                                        if ncounter.tag == "max":
                                            waste["divider"] = (
                                                int(ncounter.text) / 100
                                            )
                                        if full:
                                            for filter in ncounter:
                                                waste["filter"] = filter.text
                                    chars[waste_string[count]] = waste
                                    count += 1
                    if item.tag == "serial":
                        chars["serial_number"] = text_to_bytes(item.text)
                    if full and item.tag == "headid":
                        chars["headid"] = text_to_bytes(item.text)
                    if full and item.tag == "memory":
                        for mem in item:
                            if mem.tag == "lower":
                                chars["memory_lower"] = int(mem.text, 16)
                            if mem.tag == "upper":
                                chars["memory_upper"] = int(mem.text, 16)
                    if item.tag == "service":
                        for s in item:
                            if s.tag == "factory":
                                chars["read_key"] = text_to_bytes(s.text)
                            if s.tag == "keyword":
                                chars["write_key"] = (
                                    "".join(
                                        [
                                            chr(0 if b == 0 else b - 1)
                                            for b in text_to_bytes(s.text)
                                        ]
                                    )
                                ).encode()
                            if full and s.tag == "sendlen":
                                chars["sendlen"] = int(s.text, 16)
                            if full and s.tag == "readlen":
                                chars["readlen"] = int(s.text, 16)
        if full:
            chars["long_name"] = printer_long_name
            chars["model"] = printer_model_name
        printer_config[printer_short_name] = chars
    return printer_config

def normalize_config(
        config,
        remove_invalid,
        expand_names,
        add_alias,
        add_same_as,
    ):
    # Remove printers without write_key or without read_key
    if remove_invalid:
        for base_key, base_items in config.copy().items():
            if 'write_key' not in base_items:
                del config[base_key]
                continue
            if 'read_key' not in base_items:
                del config[base_key]
                continue

    # Replace original names with converted names and add printers for all optional names
    if expand_names:
        for key, items in config.copy().items():
            printer_list = get_printer_models(key)
            del config[key]
            for i in printer_list:
                if i in config and config[i] != items:
                    print("ERROR key", key)
                    quit()
                config[i] = items

    # Add aliases for same printer with different names and remove aliased printers
    if add_alias:
        for base_key, base_items in config.copy().items():
            found = False
            for key, items in config.copy().items():
                if not found:
                    if base_key == key and base_key in config:
                        found = True
                    continue
                if base_key != key and items == base_items:  # different name, same printer
                    if "alias" not in config[base_key]:
                        config[base_key]["alias"] = []
                    for i in get_printer_models(key):
                        if i not in config[base_key]["alias"]:
                            config[base_key]["alias"].append(i)
                    del config[key]

    # Add "same-as" for almost same printer (IGNORED_KEYS) with different names
    if add_same_as:
        IGNORED_KEYS = ['write_key', 'read_key', 'alias', 'main_waste', 'borderless_waste']
        for base_key, base_items in config.copy().items():
            found = False
            for key, items in config.copy().items():
                if not found:
                    if base_key == key and base_key in config:
                        found = True
                    continue
                if base_key != key:
                    if equal_dicts(base_items, items, IGNORED_KEYS):  # everything but the IGNORED_KEYS is the same
                        # Get the IGNORED_KEYS from the printer
                        write_key = base_items['write_key']
                        read_key = base_items['read_key']
                        alias = base_items['alias'] if 'alias' in base_items else []
                        main_waste = base_items['main_waste'] if 'main_waste' in base_items else []
                        borderless_waste = base_items['borderless_waste'] if 'borderless_waste' in base_items else []
                        # Rebuild the printer with only the IGNORED_KEYS, then add the 'same-as'
                        del config[base_key]
                        config[base_key] = {}
                        config[base_key]['write_key'] = write_key
                        config[base_key]['read_key'] = read_key
                        if alias:
                            config[base_key]['alias'] = alias
                        if main_waste:
                            config[base_key]['main_waste'] = main_waste
                        if borderless_waste:
                            config[base_key]['borderless_waste'] = borderless_waste
                        config[base_key]['same-as'] = key

    return config

def equal_dicts(a, b, ignore_keys):
    ka = set(a).difference(ignore_keys)
    kb = set(b).difference(ignore_keys)
    return ka == kb and all(a[k] == b[k] for k in ka)

if __name__ == "__main__":
    import argparse
    import pickle

    parser = argparse.ArgumentParser(
        epilog='Generate printer configuration from devices.xml'
    )
    parser.add_argument(
        '-m',
        '--model',
        dest='printer_model',
        default=False,
        action="store",
        help='Printer model. Example: -m XP-205'
    )
    parser.add_argument(
        '-l',
        '--line',
        dest='line_length',
        type=int,
        help='Set line length of the output (default: 120)',
        default=120
    )
    parser.add_argument(
        '-i',
        '--indent',
        dest='indent',
        action='store_true',
        help='Indent output of 4 spaces'
    )
    parser.add_argument(
        '-d',
        '--debug',
        dest='debug',
        action='store_true',
        help='Print debug information'
    )
    parser.add_argument(
        '-t',
        '--traverse',
        dest='traverse',
        action='store_true',
        help='Traverse the XML, dumping content related to the printer model'
    )
    parser.add_argument(
        '-v',
        '--verbose',
        dest='verbose',
        action='store_true',
        help='Print verbose information'
    )
    parser.add_argument(
        '-f',
        '--full',
        dest='full',
        action='store_true',
        help='Generate additional tags'
    )
    parser.add_argument(
        '-e',
        '--errors',
        dest='add_fatal_errors',
        action='store_true',
        help='Add last_printer_fatal_errors'
    )
    parser.add_argument(
        '-c',
        "--config",
        dest='config_file',
        type=argparse.FileType('r'),
        help="use the XML configuration file to generate the configuration",
        default=0,
        nargs=1,
        metavar='CONFIG_FILE'
    )
    parser.add_argument(
        '-s',
        '--default_model',
        dest='default_model',
        action="store",
        help='Default printer model. Example: -s XP-205'
    )
    parser.add_argument(
        '-a',
        '--address',
        dest='hostname',
        action="store",
        help='Default printer host name or IP address. (Example: -a 192.168.1.87)',
        required=True
    )
    parser.add_argument(
        '-p',
        "--pickle",
        dest='pickle',
        type=argparse.FileType('wb'),
        help="Save a pickle archive for subsequent load by ui.py and epson_print_conf.py",
        default=0,
        nargs=1,
        metavar='PICKLE_FILE'
    )
    parser.add_argument(
        '-I',
        '--keep_invalid',
        dest='keep_invalid',
        action='store_true',
        help='Do not remove printers without write_key or without read_key'
    )
    parser.add_argument(
        '-N',
        '--keep_names',
        dest='keep_names',
        action='store_true',
        help='Do not replace original names with converted names and add printers for all optional names'
    )
    parser.add_argument(
        '-A',
        '--no_alias',
        dest='no_alias',
        action='store_true',
        help='Do not add aliases for same printer with different names and remove aliased printers'
    )
    parser.add_argument(
        '-S',
        '--no_same_as',
        dest='no_same_as',
        action='store_true',
        help='Do not add "same-as" for similar printers with different names'
    )
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.INFO)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.config_file:
        args.config_file[0].close()

    if args.config_file:
        config = args.config_file[0].name
    else:
        config = "devices.xml"

    printer_config = generate_config(
        config=config,
        traverse=args.traverse,
        add_fatal_errors=args.add_fatal_errors,
        full=args.full,
        printer_model=args.printer_model
    )
    normalized_config = normalize_config(
        config=printer_config,
        remove_invalid=not args.keep_invalid,
        expand_names=not args.keep_names,
        add_alias=not args.no_alias,
        add_same_as=not args.no_same_as,
    )
    if args.default_model:
        if "internal_data" not in normalized_config:
            normalized_config["internal_data"] = {}
        normalized_config["internal_data"]["default_model"] = args.default_model
    if args.hostname:
        if "internal_data" not in normalized_config:
            normalized_config["internal_data"] = {}
        normalized_config["internal_data"]["hostname"] = args.hostname
    if args.pickle:
        pickle.dump(normalized_config, args.pickle[0]) # serialize the list
        args.pickle[0].close()
        quit()

    try:
        import black
        config_str = "PRINTER_CONFIG = " + repr(normalized_config)
        mode = black.Mode(line_length=args.line_length, magic_trailing_comma=False)
        dict_str = black.format_str(config_str, mode=mode)
    except Exception:
        import pprint
        dict_str = pprint.pformat(config_str)
    if args.indent:
        dict_str = textwrap.indent(dict_str, '    ')
    print(dict_str)

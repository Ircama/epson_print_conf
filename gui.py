import pickle
from ui import EpsonPrinterUI
from os import path

PICKLE_CONF_FILE = "printer_conf.pickle"

path_to_pickle = path.abspath(path.join(path.dirname(__file__), PICKLE_CONF_FILE))
with open(path_to_pickle, 'rb') as fp:
    conf_dict = pickle.load(fp)
app = EpsonPrinterUI(conf_dict=conf_dict, replace_conf=False)
app.mainloop()

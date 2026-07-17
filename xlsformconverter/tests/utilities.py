import inspect
import os


def data_folder():
    """Return the absolute path to the tests/data directory."""
    this_filename = inspect.stack()[0][1]
    basepath, _ = os.path.split(this_filename)
    return os.path.join(basepath, "data")

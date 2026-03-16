# -*- coding: utf-8 -*-
"""
/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import importlib
import pathlib
import re
import sys

src_dir = pathlib.Path(__file__).parent.resolve()

# remove previously loaded `convert2qgis.whl` from the python import path
for python_path in sys.path:
    if re.search(r"convert2qgis.*\.whl$", python_path):
        sys.path.remove(python_path)

# add the new `convert2qgis.whl` file to the python import path
for convert2qgis_whl in src_dir.glob("convert2qgis*.whl"):
    sys.path.append(str(convert2qgis_whl))

# force reload all the `convert2qgis` modules from the new path
module_names = list(sys.modules.keys())
for module_name in module_names:
    if module_name.startswith("convert2qgis"):
        importlib.reload(sys.modules[module_name])


def classFactory(iface):
    """Load plugin.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    from .xlsform_converter_plugin import XlsformConverterPlugin

    return XlsformConverterPlugin(iface)

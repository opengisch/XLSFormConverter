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

# remove previously loaded `xlsform2qgis.whl` from the python import path
for python_path in sys.path:
    if re.search(r"xlsform2qgis.*\.whl$", python_path):
        sys.path.remove(python_path)

# add the new `xlsform2qgis.whl` file to the python import path
for xlsform2qgis_whl in src_dir.glob("xlsform2qgis*.whl"):
    sys.path.append(str(xlsform2qgis_whl))

# force reload all the `xlsform2qgis` modules from the new path
module_names = list(sys.modules.keys())
for module_name in module_names:
    if module_name.startswith("xlsform2qgis"):
        importlib.reload(sys.modules[module_name])


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load plugin.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    #
    from .XLSFormConverterPlugin import XLSFormConverterPlugin

    return XLSFormConverterPlugin(iface)

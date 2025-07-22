# -*- coding: utf-8 -*-
"""XLSX Form Converter

.. note:: This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.
"""

__author__ = "(C) 2025 by Mathieu Pellerin"
__date__ = "22/04/2025"
__copyright__ = "Copyright 2025, Mathieu Pellerin"
# This will get replaced with a git SHA1 when you do a git archive
__revision__ = "$Format:%H$"

import os

from qgis.core import QgsApplication, QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .XLSFormConverterAlgorithms import XLSFormConverterAlgorithm

VERSION = "1.1.1"


class XLSFormConverterProvider(QgsProcessingProvider):
    def __init__(self, iface):
        QgsProcessingProvider.__init__(self)
        self.iface = iface

    def loadAlgorithms(self):
        for alg in [XLSFormConverterAlgorithm]:
            self.addAlgorithm(alg())

    def id(self):
        return "xlsformconverter"

    def name(self):
        return "XLSForm Converter"

    def longName(self):
        return "XLSForm Converter Algorithms"

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))

    def versionInfo(self):
        return VERSION


class XLSFormConverterPlugin:
    def __init__(self, iface):
        super().__init__()
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.provider = XLSFormConverterProvider(self.iface)

    def initGui(self):
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        QgsApplication.processingRegistry().removeProvider(self.provider)
        self.provider = None

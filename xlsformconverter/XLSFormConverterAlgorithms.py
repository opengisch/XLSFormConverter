import os

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterCrs,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterString,
)
from qgis.PyQt.QtCore import QCoreApplication, QEventLoop
from qgis.PyQt.QtGui import QIcon

from .XLSFormConverter import XLSFormConverter

QFIELDSYNC_AVAILABLE = True
try:
    from plugins.qfieldsync.core.cloud_api import (
        CloudException,
        CloudNetworkAccessManager,
    )
    from plugins.qfieldsync.core.cloud_project import CloudProject
    from plugins.qfieldsync.core.cloud_transferrer import CloudTransferrer
except ImportError:
    QFIELDSYNC_AVAILABLE = False


class XLSFormConverterAlgorithm(QgsProcessingAlgorithm):
    INPUT = "INPUT"
    TITLE = "TITLE"
    LANGUAGE = "LANGUAGE"
    BASEMAP = "BASEMAP"
    GROUPS_AS_TABS = "GROUPS_AS_TABS"
    UPLOAD_TO_QFIELDCLOUD = "UPLOAD_TO_QFIELDCLOUD"
    CRS = "CRS"
    GEOMETRIES = "GEOMETRIES"
    OUTPUT = "OUTPUT"

    def tr(self, string):
        return QCoreApplication.translate("Processing", string)

    def createInstance(self):
        return XLSFormConverterAlgorithm()

    def name(self):
        return "xlsformconverter"

    def displayName(self):
        return self.tr("Convert XLSForm to QGIS project")

    def group(self):
        return self.tr("XLSForm Converter")

    def groupId(self):
        return "xlsformconverter"

    def shortHelpString(self):
        return self.tr(
            '<a href="https://xlsform.org/en/">XLSForm</a> is a form standard created to help simplify the authoring of forms using a spreadsheet program such as LibreOffice Calc or Microsoft Excel. They are simple to get started with but allow for the authoring of complex forms by someone familiar with the syntax.\n\n'
            "This algorithm converts a XLSForm file into a QGIS project containing a survey layer with a feature form reflecting the authored form. This can facilitate the creation of complex feature forms through a simple, well-known format.\n\n"
            'An option to upload the generated project directly to <a href="https://qfield.cloud">QFieldCloud</a> facilitates its deployment to <a href="https://qfield.org/">QField</a>, an open-source fieldwork app for geospatial data collection built on top of QGIS. A deployment through QFieldCloud enables multiple collaborators to seamlessly work on the same survey layer. This option works alongside the QFieldSync plugin.'
        )

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT,
                self.tr("XLSForm file"),
                fileFilter="XLSForm file (*.xls *.XLS *.xlsx *.XLSX *.ods *.ODS)",
            )
        )

        param = QgsProcessingParameterString(
            self.TITLE, self.tr("Project title"), optional=True
        )
        param.setHelp(
            self.tr(
                "If left blank, the title within the settings' tab of the input XLSForm file will be used if available"
            )
        )
        self.addParameter(param)

        param = QgsProcessingParameterString(
            self.LANGUAGE, self.tr("Project language"), optional=True
        )
        param.setHelp(
            self.tr(
                "If left blank, the default language within the settings' tab of the input XLSForm file will be used if available"
            )
        )
        self.addParameter(param)

        self.addParameter(
            QgsProcessingParameterEnum(
                self.BASEMAP,
                self.tr("Project basemap"),
                [
                    self.tr("OpenStreetMap"),
                    self.tr("Humanitarian OpenStreetMap Team (HOT)"),
                ],
                defaultValue=0,
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.GROUPS_AS_TABS,
                self.tr("Use form tabs for root groups"),
                defaultValue=False,
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.UPLOAD_TO_QFIELDCLOUD,
                self.tr("Upload generated project to QFieldCloud"),
                defaultValue=False,
            )
        )

        param = QgsProcessingParameterCrs(
            self.CRS,
            self.tr("Project CRS"),
            optional=True,
        )
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.Flag.Advanced)
        self.addParameter(param)

        param = QgsProcessingParameterFeatureSource(
            self.GEOMETRIES,
            self.tr(
                "Pre-fill project with features' geometries and matching attributes"
            ),
            types=[QgsProcessing.SourceType.VectorAnyGeometry],
            optional=True,
        )
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.Flag.Advanced)
        self.addParameter(param)

        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT,
                self.tr("Output local project directory"),
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        xlsform_file = self.parameterAsString(parameters, self.INPUT, context)
        title = self.parameterAsString(parameters, self.TITLE, context)
        language = self.parameterAsString(parameters, self.LANGUAGE, context)
        crs = self.parameterAsCrs(parameters, self.CRS, context)
        geometries = self.parameterAsSource(parameters, self.GEOMETRIES, context)

        basemap = "OpenStreetMap"
        basemap_index = self.parameterAsEnum(parameters, self.BASEMAP, context)
        if basemap_index == 1:
            basemap = "HOT"

        groups_as_tabs = self.parameterAsBoolean(
            parameters, self.GROUPS_AS_TABS, context
        )
        upload_to_qfieldcloud = self.parameterAsBoolean(
            parameters, self.UPLOAD_TO_QFIELDCLOUD, context
        )
        output_directory = self.parameterAsString(parameters, self.OUTPUT, context)

        converter = XLSFormConverter(xlsform_file)
        if not converter.is_valid():
            feedback.reportError(self.tr("The provided XLSForm is invalid, aborting."))
            return {}

        converter.info.connect(lambda message: feedback.pushInfo(message))
        converter.warning.connect(lambda message: feedback.pushWarning(message))
        converter.error.connect(lambda message: feedback.reportError(message))

        converter.set_custom_title(title)
        converter.set_preferred_language(language)
        converter.set_basemap(basemap)
        converter.set_geometries(geometries)
        converter.set_groups_as_tabs(groups_as_tabs)
        if crs.isValid():
            converter.set_crs(crs)

        project_file = converter.convert(output_directory)

        if project_file and upload_to_qfieldcloud:
            for root, dirs, files in os.walk(output_directory):
                for file in files:
                    if file.lower().endswith(".qgs") or file.lower().endswith(".qgz"):
                        if os.path.join(root, file) != project_file:
                            feedback.pushWarning(
                                self.tr(
                                    "Upload to QFieldCloud skipped as the output directory already contains a project file."
                                )
                            )
                            upload_to_qfieldcloud = False
                            break
                if not upload_to_qfieldcloud:
                    break

            if upload_to_qfieldcloud:
                self.uploadToQFieldCloud(output_directory, project_file, feedback)

        return {self.OUTPUT: output_directory}

    def uploadToQFieldCloud(self, output_directory, project_file, feedback):
        if not QFIELDSYNC_AVAILABLE:
            feedback.pushWarning(
                self.tr(
                    "QFieldSync plugin is required to proceed with uploading the generated project to QFieldCloud, please install it and log into your account first."
                )
            )
            return

        nam = CloudNetworkAccessManager()
        cfg = nam.auth()
        username = cfg.config("username")
        password = cfg.config("password")
        if not nam.has_token():
            feedback.pushInfo(self.tr("Logging into QFieldCloud"))
            if not username or not password:
                feedback.pushWarning(
                    self.tr(
                        "Please log into QFieldCloud within QFieldSync prior to running this algorithm when proceeding with uploading the generated project to QFieldCloud."
                    )
                )
                return

            loop = QEventLoop()
            nam.login_finished.connect(loop.quit)
            nam.login(username, password)
            loop.exec()

        if not nam.has_token():
            feedback.pushWarning(
                self.tr(
                    "Logging into QFieldCloud failed, please successfully log in using QFieldSync prior to running this algorithm when proceeding with uploading the generated project to QFieldCloud."
                )
            )
            return

        feedback.pushInfo(
            self.tr("Retrieving the list of cloud projects from QFieldCloud")
        )
        loop = QEventLoop()
        nam.projects_cache.projects_updated.connect(loop.quit)
        nam.projects_cache.projects_error.connect(loop.quit)
        nam.projects_cache.refresh()
        loop.exec()

        feedback.pushInfo(self.tr("Uploading the generated projects to QFieldCloud"))
        loop = QEventLoop()
        project_title = nam.projects_cache.get_unique_name(
            os.path.splitext(os.path.basename(project_file))[0]
        )
        reply = nam.create_project(
            project_title, username, "Created by XLSForm Converter", True
        )
        reply.finished.connect(loop.quit)
        loop.exec()
        try:
            payload = nam.json_object(reply)
        except CloudException as err:
            feedback.pushWarning(
                self.tr("QFieldCloud rejected project creation:\n{}").format(err)
            )
            return

        loop = QEventLoop()
        cloud_project = CloudProject({**payload, "local_dir": output_directory})
        cloud_transferrer = CloudTransferrer(nam, cloud_project)
        cloud_transferrer.finished.connect(loop.quit)
        cloud_transferrer.sync(list(cloud_project.files_to_sync), [], [], [])
        loop.exec()

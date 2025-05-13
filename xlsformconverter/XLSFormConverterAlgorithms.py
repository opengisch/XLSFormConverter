import os

from qgis.core import (
    Qgis,
    QgsProcessingAlgorithm,
    QgsProcessingParameterBoolean,
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
    UPLOAD_TO_QFIELDCLOUD = "UPLOAD_TO_QFIELDCLOUD"
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
            'Converts an XLSForm file into a QGIS project with prepared layers and feature forms.\n\nThe algorithm conveniently offers way to upload the generated project directly to <a href="https://qfield.cloud">QFieldCloud</a> provided the QFieldSync plugin is installed.'
        )

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(self.INPUT, self.tr("XLSForm file"))
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
            QgsProcessingParameterBoolean(
                self.UPLOAD_TO_QFIELDCLOUD,
                self.tr("Upload generated project to QFieldCloud"),
                defaultValue=False,
            )
        )

        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT,
                self.tr("Output local project directory"),
                Qgis.ProcessingFileParameterBehavior.Folder,
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        xlsform_file = self.parameterAsString(parameters, self.INPUT, context)
        title = self.parameterAsString(parameters, self.TITLE, context)
        language = self.parameterAsString(parameters, self.LANGUAGE, context)
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
        project_file = converter.convert(output_directory, title, language)

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

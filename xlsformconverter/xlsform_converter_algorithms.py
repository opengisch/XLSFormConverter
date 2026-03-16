import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from convert2qgis.xlsform2qgis.converter import (
    XlsformConverterError,
    convert_xlsform_to_qgis_project,
)
from convert2qgis.xlsform2qgis.qgis_utils import LoggingSignals, transform_bounding_box
from convert2qgis.xlsform2qgis.type_defs import ConverterSettings, WeakXlsformSettings
from qgis.core import (
    Qgis,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingFeatureSource,
    QgsProcessingFeedback,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterCrs,
    QgsProcessingParameterEnum,
    QgsProcessingParameterExtent,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterString,
    QgsProject,
)
from qgis.PyQt.QtCore import QCoreApplication, QEventLoop
from qgis.PyQt.QtGui import QIcon

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


def decorator_connect_logging(func):
    def wrapper(self, *args, **kwargs):
        feedback = args[-1]
        if not isinstance(feedback, QgsProcessingFeedback):
            feedback.pushWarning(
                "Feedback object not found in algorithm parameters, cannot connect logging signals."
            )

            raise RuntimeError(
                "Feedback object not found in algorithm parameters, cannot connect logging signals."
            )

        self._connect_logging(feedback)

        try:
            result = func(self, *args, **kwargs)
        finally:
            pass
            # self._disconnect_logging()

        return result

    return wrapper


class XlsformConverterAlgorithm(QgsProcessingAlgorithm):
    _logging_callabcks: dict[str, Callable[[str], None]] = {}

    INPUT = "INPUT"
    TITLE = "TITLE"
    LANGUAGE = "LANGUAGE"
    BASEMAP = "BASEMAP"
    GROUPS_AS_TABS = "GROUPS_AS_TABS"
    UPLOAD_TO_QFIELDCLOUD = "UPLOAD_TO_QFIELDCLOUD"
    CRS = "CRS"
    EXTENT = "EXTENT"
    FEATURES = "FEATURES"
    OUTPUT = "OUTPUT"

    def tr(self, string):
        return QCoreApplication.translate("Processing", string)

    def createInstance(self):
        return XlsformConverterAlgorithm()

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

    def initAlgorithm(self, configuration=None):
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
        param.setFlags(param.flags() | Qgis.ProcessingParameterFlag.Advanced)
        self.addParameter(param)

        param = QgsProcessingParameterExtent(
            self.EXTENT,
            self.tr("Project extent"),
            optional=True,
        )
        param.setFlags(param.flags() | Qgis.ProcessingParameterFlag.Advanced)
        self.addParameter(param)

        param = QgsProcessingParameterFeatureSource(
            self.FEATURES,
            self.tr(
                "Pre-fill project's survey with features' geometries and matching attributes"
            ),
            types=[Qgis.ProcessingSourceType.VectorAnyGeometry],
            optional=True,
        )
        param.setFlags(param.flags() | Qgis.ProcessingParameterFlag.Advanced)
        self.addParameter(param)

        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT,
                self.tr("Output local project directory"),
            )
        )

    def _get_basemap_url(self, index: int) -> str:
        if index == 0:
            return "type=xyz&tilePixelRatio=1&url=https://tile.openstreetmap.org/%7Bz%7D/%7Bx%7D/%7By%7D.png&zmax=19&zmin=0&crs=EPSG3857"
        elif index == 1:
            return "type=xyz&tilePixelRatio=1&url=https://a.tile.openstreetmap.fr/hot/%7Bz%7D/%7Bx%7D/%7By%7D.png&zmax=19&zmin=0&crs=EPSG3857"
        else:
            raise ValueError(f"Unsupported basemap index: {index}")

    @decorator_connect_logging
    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback | None,
    ) -> dict[str, Any]:
        assert feedback

        xlsform_filename = self.parameterAsString(parameters, self.INPUT, context)
        survey_features = self.parameterAsSource(parameters, self.FEATURES, context)
        project_title = self.parameterAsString(parameters, self.TITLE, context)
        default_language = self.parameterAsString(parameters, self.LANGUAGE, context)
        project_crs = self.parameterAsCrs(parameters, self.CRS, context)
        project_extent = self.parameterAsExtent(
            parameters, self.EXTENT, context, project_crs
        )
        basemap_index = self.parameterAsEnum(parameters, self.BASEMAP, context)
        groups_as_tabs = self.parameterAsBoolean(
            parameters, self.GROUPS_AS_TABS, context
        )
        upload_to_qfieldcloud = self.parameterAsBoolean(
            parameters, self.UPLOAD_TO_QFIELDCLOUD, context
        )
        output_dir = self.parameterAsString(parameters, self.OUTPUT, context)

        # Prepare settings
        xlsform_settings: WeakXlsformSettings = {}
        if project_title:
            xlsform_settings["form_title"] = project_title

        if default_language:
            xlsform_settings["default_language"] = default_language

        converter_settings: ConverterSettings = {}
        converter_settings["xlsform_settings"] = xlsform_settings
        # TODO: set author from QGIS metadata
        converter_settings["author"] = ""

        if groups_as_tabs:
            converter_settings["form_group_type"] = "tab"
        else:
            converter_settings["form_group_type"] = "group_box"

        converter_settings["basemap_url"] = self._get_basemap_url(basemap_index)

        if project_crs and project_crs.isValid():
            converter_settings["crs"] = project_crs.authid()
        else:
            feedback.pushWarning(
                self.tr(
                    "Project CRS parameter is invalid, defaulting to EPSG:3857. This may lead to unexpected behavior when using the generated project alongside layers in different CRSs or when using the project extent parameter."
                )
            )

            converter_settings["crs"] = "EPSG:3857"

        if project_extent.isEmpty():
            feedback.pushWarning(
                self.tr("Project extent parameter ignored, invalid extent.")
            )

            if (
                survey_features is not None
                and survey_features.featureCount() > 0
                and not survey_features.sourceExtent().isEmpty()
                and survey_features.sourceExtent.isFinite()
                and survey_features.sourceCrs().isValid()
            ):
                project_extent = transform_bounding_box(
                    survey_features.sourceExtent(),
                    survey_features.sourceCrs(),
                    project_crs,
                    QgsProject(),
                )

                if project_extent.isFinite():
                    converter_settings["extent"] = project_extent.asWktCoordinates()
                else:
                    feedback.pushWarning(
                        self.tr(
                            "Failed to transform features extent, default will be used."
                        )
                    )
            else:
                feedback.pushWarning(
                    self.tr("Cannot use features extent, default will be used.")
                )
        else:
            # no need to transform the extent to another CRS, as we already did in `parameterAsExtent`
            converter_settings["extent"] = project_extent.asWktCoordinates()
        # / Prepare settings

        self._convert_project(
            xlsform_filename, output_dir, converter_settings, survey_features, feedback
        )

        if upload_to_qfieldcloud:
            self._upload_to_qfieldcloud(output_dir, feedback)

        return {self.OUTPUT: output_dir}

    def _convert_project(
        self,
        xlsform_filename: str,
        output_dir: str,
        converter_settings: ConverterSettings,
        survey_features: QgsProcessingFeatureSource | None,
        feedback: QgsProcessingFeedback,
    ) -> None:
        try:
            project = convert_xlsform_to_qgis_project(
                xlsform_filename,
                output_dir=output_dir,
                settings=converter_settings,
                skip_failed_expressions=True,
                survey_features=survey_features,
                # NOTE: set to a temporary file so one can inspect and debug the generated JSON
                json_filename="/tmp/xlsform.json",
            )
        except (FileNotFoundError, XlsformConverterError) as err:
            feedback.reportError(str(err), True)

            return

        feedback.pushInfo(
            self.tr("XLSForm converted and saved as a QGIS project at {}").format(
                project.fileName()
            )
        )

    def _upload_to_qfieldcloud(
        self, output_dir: str | Path, feedback: QgsProcessingFeedback
    ) -> None:
        if not QFIELDSYNC_AVAILABLE:
            feedback.pushWarning(
                self.tr(
                    "QFieldSync plugin is required to proceed with uploading the generated project to QFieldCloud, please install it and log into your account first."
                )
            )
            return

        qgis_project_files = [
            f for pattern in ("*.qgs", "*.qgz") for f in Path(output_dir).rglob(pattern)
        ]

        if len(qgis_project_files) > 1:
            feedback.pushWarning(
                self.tr(
                    "Upload to QFieldCloud skipped as the output directory contains multiple QGIS project files, making it ambiguous which one to upload."
                )
            )
            return

        if len(qgis_project_files) == 0:
            feedback.pushWarning(
                self.tr(
                    "Upload to QFieldCloud skipped as no QGIS project file was found in the output directory after conversion."
                )
            )
            return

        project_file = qgis_project_files[0]

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
        cloud_project = CloudProject({**payload, "local_dir": output_dir})
        cloud_transferrer = CloudTransferrer(nam, cloud_project)
        cloud_transferrer.finished.connect(loop.quit)
        cloud_transferrer.sync(list(cloud_project.files_to_sync), [], [], [])
        loop.exec()

    def _connect_logging(self, feedback):
        self._logging_callabcks = {
            "debug": lambda msg: feedback.pushDebugInfo(msg),
            "info": lambda msg: feedback.pushInfo(msg),
            "warning": lambda msg: feedback.pushWarning(msg),
            "error": lambda msg: feedback.reportError(msg),
        }

        # Setup logging signals
        logging_signals = LoggingSignals()
        logging_signals.debug.connect(self._logging_callabcks["debug"])
        logging_signals.info.connect(self._logging_callabcks["info"])
        logging_signals.warning.connect(self._logging_callabcks["warning"])
        logging_signals.error.connect(self._logging_callabcks["error"])

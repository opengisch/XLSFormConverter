import os
import re
import unicodedata

from lxml import html
from qgis.core import (
    Qgis,
    QgsAttributeEditorContainer,
    QgsAttributeEditorField,
    QgsAttributeEditorRelation,
    QgsAttributeEditorTextElement,
    QgsCoordinateReferenceSystem,
    QgsDefaultValue,
    QgsEditFormConfig,
    QgsEditorWidgetSetup,
    QgsExpression,
    QgsFeature,
    QgsField,
    QgsFieldConstraints,
    QgsFields,
    QgsMapLayer,
    QgsMapSettings,
    QgsOptionalExpression,
    QgsProject,
    QgsProperty,
    QgsPropertyCollection,
    QgsRasterLayer,
    QgsRectangle,
    QgsRelation,
    QgsRelationContext,
    QgsVectorFileWriter,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QMetaType, QObject, QSize, pyqtSignal

MARKDOWN_AVAILABLE = True
try:
    import markdown
except ImportError:
    MARKDOWN_AVAILABLE = False


class XLSFormConverter(QObject):
    survey_layer = None
    choices_layer = None
    settings_layer = None

    label_field_name = "label"

    output_field = None
    output_project = None

    has_calculation = False
    has_relevant = False
    has_choice_filter = False
    has_parameters = False
    has_constraint = False
    has_constraint_message = False
    has_required = False
    has_default = False
    has_read_only = False
    has_trigger = False

    calculate_expressions = {}

    multimedia_info_pushed = False
    barcode_info_pushed = False

    info = pyqtSignal(str)
    warning = pyqtSignal(str)
    error = pyqtSignal(str)

    FIELD_TYPES = [
        "integer",
        "decimal",
        "range",
        "date",
        "time",
        "datetime",
        "text",
        "barcode",
        "image",
        "audio",
        "background-audio",
        "video",
        "file",
        "select_one",
        "select_one_from_file",
        "select_multiple",
        "select_multiple_from_file",
        "acknowledge",
        "rank",
        "calculate",
    ]
    METADATA_TYPES = [
        "start",
        "end",
        "today",
        "deviceid",
        "phonenumber",
        "username",
        "email",
        "audit",
    ]

    def __init__(self, xlsx_form_file):
        QObject.__init__(self)
        if os.path.isfile(xlsx_form_file):
            self.survey_layer = QgsVectorLayer(
                xlsx_form_file
                + "|layername=survey|option:FIELD_TYPES=STRING|option:HEADERS=FORCE",
                "survey",
                "ogr",
            )
            self.choices_layer = QgsVectorLayer(
                xlsx_form_file
                + "|layername=choices|option:FIELD_TYPES=STRING|option:HEADERS=FORCE",
                "options",
                "ogr",
            )
            self.settings_layer = QgsVectorLayer(
                xlsx_form_file
                + "|layername=settings|option:FIELD_TYPES=STRING|option:HEADERS=FORCE",
                "settings",
                "ogr",
            )

            self.has_calculation = "calculation" in self.survey_layer.fields().names()
            self.has_relevant = "relevant" in self.survey_layer.fields().names()
            self.has_choice_filter = (
                "choice_filter" in self.survey_layer.fields().names()
            )
            self.has_parameters = "parameters" in self.survey_layer.fields().names()
            self.has_constraint = "constraint" in self.survey_layer.fields().names()
            self.has_constraint_message = (
                "constraint_message" in self.survey_layer.fields().names()
            )
            self.has_required = "required" in self.survey_layer.fields().names()
            self.has_default = "default" in self.survey_layer.fields().names()
            self.has_read_only = "read_only" in self.survey_layer.fields().names()
            self.has_trigger = "has_trigger" in self.survey_layer.fields().names()

    def create_field(self, feature):
        type_details = str(feature.attribute("type")).split(" ")
        type_details[0] = type_details[0].lower()

        field_name = str(feature.attribute("name")).strip()
        field_alias = (
            str(feature.attribute(self.label_field_name)).strip()
            if feature.attribute(self.label_field_name)
            else field_name
        )

        field_type = None
        field = None

        if type_details[0] == "integer":
            field_type = QMetaType.LongLong
        elif type_details[0] == "decimal":
            field_type = QMetaType.Double
        elif type_details[0] == "range":
            field_type = QMetaType.Double
        elif type_details[0] == "date" or type_details[0] == "today":
            field_type = QMetaType.QDate
        elif type_details[0] == "time":
            field_type = QMetaType.QTime
        elif (
            type_details[0] == "datetime"
            or type_details[0] == "start"
            or type_details[0] == "end"
        ):
            field_type = QMetaType.QDateTime
        elif type_details[0] == "acknowledge":
            field_type = QMetaType.Bool
        elif (
            type_details[0] == "text"
            or type_details[0] == "barcode"
            or type_details[0] == "image"
            or type_details[0] == "audio"
            or type_details[0] == "background-audio"
            or type_details[0] == "video"
            or type_details[0] == "file"
            or type_details[0] == "select_one"
            or type_details[0] == "select_one_from_file"
            or type_details[0] == "select_multiple"
            or type_details[0] == "select_multiple_from_file"
            or type_details[0] == "calculate"
            or type_details[0] == "username"
            or type_details[0] == "email"
        ):
            field_type = QMetaType.QString

            if self.has_calculation and type_details[0] == "calculate":
                field_calculation = (
                    str(feature.attribute("calculation")).strip()
                    if feature.attribute("calculation")
                    else ""
                )
                if field_calculation != "":
                    self.calculate_expressions[field_name] = field_calculation

            if type_details[0] == "barcode":
                if not self.barcode_info_pushed:
                    self.info.emit(
                        self.tr(
                            "Barcode functionality is only available through QField; it will be a simple text field in QGIS"
                        )
                    )
                    self.barcode_info_pushed = True
            elif (
                type_details[0] == "image"
                or type_details[0] == "audio"
                or type_details[0] == "video"
                or type_details[0] == "background-audio"
            ):
                if type_details[0] == "background-audio":
                    self.warning.emit(
                        self.tr(
                            "Unsupported type background-audio, using audio instead"
                        )
                    )

                if not self.multimedia_info_pushed:
                    self.info.emit(
                        self.tr(
                            "Multimedia content can be captured using QField on devices with cameras and microphones; in QGIS, pre-existing files can be selected."
                        )
                    )
                    self.multimedia_info_pushed = True
            elif type_details[0] == "username" or type_details[0] == "email":
                self.info.emit(
                    self.tr(
                        "The metadata {} is only available through QFieldCloud; it will return an empty value in QGIS".format(
                            type_details[0]
                        )
                    )
                )

        if field_type:
            field = QgsField(field_name, field_type)
            field.setAlias(field_alias)

            field_constraints = QgsFieldConstraints()

            if self.has_constraint:
                field_constraint_expression = (
                    str(feature.attribute("constraint")).strip()
                    if feature.attribute("constraint")
                    else ""
                )
                if field_constraint_expression != "":
                    field_constraint_expression = self.convert_expression(
                        field_constraint_expression, dot_field_name=field_name
                    )

                    field_constraint_message = (
                        str(feature.attribute("constraint_message")).strip()
                        if self.has_constraint_message
                        and feature.attribute("constraint_message")
                        else ""
                    )

                    # setup constraints
                    field_constraints.setConstraintExpression(
                        field_constraint_expression, field_constraint_message
                    )
                    field_constraints.setConstraintStrength(
                        QgsFieldConstraints.ConstraintExpression,
                        QgsFieldConstraints.ConstraintStrengthHard,
                    )

            if self.has_required:
                field_required = (
                    str(feature.attribute("required")).strip().lower()
                    if feature.attribute("required")
                    else ""
                )

                if field_required == "yes":
                    field_constraints.setConstraint(
                        QgsFieldConstraints.ConstraintNotNull,
                        QgsFieldConstraints.ConstraintOriginLayer,
                    )
                    field_constraints.setConstraintStrength(
                        QgsFieldConstraints.ConstraintNotNull,
                        QgsFieldConstraints.ConstraintStrengthHard,
                    )

            field.setConstraints(field_constraints)

        return field

    def create_layer(self, name=None):
        if name:
            self.info.emit(self.tr("Creating child survey layer {}".format(name)))
        else:
            self.info.emit(self.tr("Creating main survey layer"))

        layer_geometry = self.detect_geometry(name)
        layer_fields = self.detect_fields(name)

        writer_options = QgsVectorFileWriter.SaveVectorOptions()
        writer_options.actionOnExistingFile = (
            QgsVectorFileWriter.CreateOrOverwriteLayer
            if os.path.isfile(self.output_file)
            else QgsVectorFileWriter.CreateOrOverwriteFile
        )
        writer_options.layerName = "survey" if not name else name
        writer_options.fileEncoding = "utf-8"
        QgsVectorFileWriter.create(
            self.output_file,
            layer_fields,
            layer_geometry,
            QgsCoordinateReferenceSystem(4326),
            QgsProject.instance().transformContext(),
            writer_options,
        )

        layer = QgsVectorLayer(
            self.output_file + "|layername=" + writer_options.layerName,
            writer_options.layerName,
            "ogr",
        )
        if name:
            layer.setFlags(QgsMapLayer.Private)
        layer.setDefaultValueDefinition(
            layer.fields().indexOf("uuid"), QgsDefaultValue("uuid()", False)
        )

        for layer_field in layer_fields:
            field_index = layer.fields().indexOf(layer_field.name())
            if field_index >= 0:
                layer.setConstraintExpression(
                    field_index,
                    layer_field.constraints().constraintExpression(),
                    layer_field.constraints().constraintDescription(),
                )
                if (
                    layer_field.constraints().constraintStrength(
                        QgsFieldConstraints.ConstraintNotNull
                    )
                    == QgsFieldConstraints.ConstraintStrengthHard
                ):
                    layer.setFieldConstraint(
                        field_index,
                        QgsFieldConstraints.ConstraintNotNull,
                        QgsFieldConstraints.ConstraintStrengthHard,
                    )

        layer.setCustomProperty("QFieldSync/cloud_action", "offline")
        layer.setCustomProperty("QFieldSync/action", "offline")

        self.output_project.addMapLayer(layer)

        return layer

    def create_editor_widget(self, feature):
        type_details = str(feature.attribute("type")).split(" ")
        type_details[0] = type_details[0].lower()

        editor_widget = None

        if type_details[0] == "integer" or type_details[0] == "decimal":
            editor_widget = QgsEditorWidgetSetup("Range", {})
            editor_widget = QgsEditorWidgetSetup("Range", {})
        elif type_details[0] == "range":
            if self.has_parameters:
                parameters = feature.attribute("parameters")

                start_value = re.search("start=\s*([0-9]+)", parameters)
                start_value = start_value.group(1) if start_value else 0
                end_value = re.search("end=\s*([0-9]+)", parameters)
                end_value = end_value.group(1) if end_value else 10
                step_value = re.search("step=\s*([0-9]+)", parameters)
                step_value = step_value.group(1) if end_value else 1

                editor_widget = QgsEditorWidgetSetup(
                    "Range",
                    {
                        "Min": start_value,
                        "Max": end_value,
                        "Step": step_value,
                        "Style": "Slider",
                    },
                )
            else:
                editor_widget = QgsEditorWidgetSetup("Range", {})
        elif (
            type_details[0] == "date"
            or type_details[0] == "time"
            or type_details[0] == "datetime"
        ):
            field_format = "yyyy-MM-dd"
            if type_details[0] == "time":
                field_format = "HH:mm:ss"
            elif type_details[0] == "datetime":
                field_format = "yyyy-MM-dd HH:mm:ss"
            editor_widget = QgsEditorWidgetSetup(
                "DateTime",
                {
                    "field_format_overwrite": True,
                    "display_format": field_format,
                    "field_format": field_format,
                    "allow_null": True,
                    "calendar_popup": True,
                },
            )
        elif (
            type_details[0] == "image"
            or type_details[0] == "audio"
            or type_details[0] == "background-audio"
            or type_details[0] == "video"
            or type_details[0] == "file"
        ):
            document_viewer = 0
            if type_details[0] == "image":
                document_viewer = 1
            elif type_details[0] == "audio" or type_details[0] == "background-audio":
                document_viewer = 3
            elif type_details[0] == "video":
                document_viewer = 4
            editor_widget = QgsEditorWidgetSetup(
                "ExternalResource",
                {
                    "DocumentViewer": document_viewer,
                    "FileWidget": True,
                    "FileWidgetButton": True,
                    "RelativeStorage": 1,
                },
            )
        elif type_details[0] == "acknowledge":
            editor_widget = QgsEditorWidgetSetup("CheckBox", {})
        elif (
            type_details[0] == "text"
            or type_details[0] == "barcode"
            or type_details[0] == "calculate"
        ):
            editor_widget = QgsEditorWidgetSetup("TextEdit", {})
        elif (
            type_details[0] == "select_one"
            or type_details[0] == "select_multiple"
            or type_details[0] == "select_one_from_file"
            or type_details[0] == "select_multiple_from_file"
        ):
            value_layer = self.output_project.mapLayersByName("list_" + type_details[1])
            if value_layer:
                allow_multi = (
                    type_details[0] == "select_multiple"
                    or type_details[0] == "select_multiple_from_file"
                )
                filter_expression = (
                    str(feature.attribute("choice_filter")).strip()
                    if self.has_choice_filter and feature.attribute("choice_filter")
                    else ""
                )
                if filter_expression != "":
                    filter_expression = self.convert_expression(
                        filter_expression, use_current_value=True
                    )
                if (
                    type_details[0] == "select_multiple"
                    or type_details[0] == "select_multiple_from_file"
                ):
                    if filter_expression != "":
                        filter_expression = (
                            "\"name\" != '' and (" + filter_expression + ")"
                        )
                    else:
                        filter_expression = "\"name\" != ''"
                editor_widget = QgsEditorWidgetSetup(
                    "ValueRelation",
                    {
                        "Layer": value_layer[0].id(),
                        "LayerName": type_details[1],
                        "LayerProviderName": "ogr",
                        "LayerSource": value_layer[0].source(),
                        "Key": "name",
                        "Value": self.label_field_name,
                        "AllowNull": False,
                        "AllowMulti": allow_multi,
                        "FilterExpression": filter_expression,
                    },
                )
            else:
                editor_widget = QgsEditorWidgetSetup("TextEdit", {})
        elif (
            type_details[0] == "today"
            or type_details[0] == "start"
            or type_details[0] == "end"
            or type_details[0] == "username"
            or type_details[0] == "email"
        ):
            # Metadata values are hidden
            editor_widget = QgsEditorWidgetSetup("Hidden", {})

        if editor_widget and self.has_calculation:
            calculation = (
                str(feature.attribute("calculation")).strip()
                if feature.attribute("calculation")
                else ""
            )
            field_alias = (
                str(feature.attribute(self.label_field_name)).strip()
                if feature.attribute(self.label_field_name)
                else ""
            )
            if calculation != "" and field_alias == "":
                editor_widget = QgsEditorWidgetSetup("Hidden", {})

        return editor_widget

    def detect_geometry(self, child_name=None):
        geometry = Qgis.WkbType.NoGeometry

        current_child_name = []
        it = self.survey_layer.getFeatures()
        for feature in it:
            feature_type = str(feature.attribute("type")).strip()
            if feature_type == "begin repeat":
                current_child_name.append(feature.attribute("name"))
            elif feature_type == "end repeat":
                current_child_name.pop()
            else:
                if (
                    len(current_child_name) > 0 and current_child_name[-1] == child_name
                ) or (len(current_child_name) == 0 and not child_name):
                    type_details = str(feature.attribute("type")).split(" ")[0]
                    if type_details == "geopoint":
                        geometry = Qgis.WkbType.Point
                        break
                    if type_details == "geotrace":
                        geometry = Qgis.WkbType.LineString
                        break
                    if type_details == "geoshape":
                        geometry = Qgis.WkbType.Polygon
                        break

        return geometry

    def detect_fields(self, child_name=None):
        fields = QgsFields()

        fields.append(QgsField("uuid", QMetaType.QString))
        if child_name:
            fields.append(QgsField("uuid_parent", QMetaType.QString))

        current_child_name = []
        it = self.survey_layer.getFeatures()
        for feature in it:
            feature_type = str(feature.attribute("type")).strip()
            feature_name = str(feature.attribute("name")).strip()
            if feature_type == "begin repeat":
                current_child_name.append(feature_name)
            elif feature_type == "end repeat":
                current_child_name.pop()
            else:
                if (
                    len(current_child_name) > 0 and current_child_name[-1] == child_name
                ) or (len(current_child_name) == 0 and not child_name):
                    field = self.create_field(feature)
                    if field:
                        fields.append(field)
                    else:
                        type_details = str(feature.attribute("type")).split(" ")
                        type_details[0] = type_details[0].lower()
                        if type_details[0] in self.FIELD_TYPES:
                            self.warning.emit(
                                self.tr(
                                    "Unsupported field type {} for layer {}, skipping".format(
                                        type_details[0],
                                        "survey" if not child_name else child_name,
                                    )
                                )
                            )
                        elif type_details[0] in self.METADATA_TYPES:
                            if (
                                not type_details[0] == "end"
                                or feature.attribute("type").strip().lower() == "end"
                            ):
                                self.warning.emit(
                                    self.tr(
                                        "Unsupported metadata {} for layer {}, skipping".format(
                                            type_details[0],
                                            "survey" if not child_name else child_name,
                                        )
                                    )
                                )

        return fields

    def convert_label_expression(self, original_label_expression):
        label_expression = original_label_expression

        # ${field} to "field"
        label_expression = label_expression.replace("'", "\\'")
        label_expression = re.sub(
            r"\$\{([^}]+)}", "' || \"\\1\" || '", label_expression
        )
        label_expression = "'{}'".format(label_expression)

        label_expression_try = QgsExpression(label_expression)
        if label_expression_try.hasParserError():
            self.warning.emit(
                self.tr(
                    "Unsupported label expression {}".format(original_label_expression)
                )
            )

        return label_expression

    def convert_expression(
        self,
        original_expression,
        use_current_value=False,
        use_insert=False,
        dot_field_name=None,
    ):
        expression = original_expression

        # replace dot with field name
        if dot_field_name:
            expression = re.sub(
                r"(^|[\s<>=\(\)\,])\.($|[\s<>=\(\)\,])",
                r"\1${" + dot_field_name + r"}\2",
                expression,
            )

        # selected(${field}, value) to ${field} = value
        expression = re.sub(
            r"selected\s*\(\s*(\$\{[^}]+})\,([^)]+)\)", r"\1 = \2", expression
        )

        # regexp(${field}, value) to regexp_match(${field}, value)
        match = re.search(
            r"regex\s*\(\s*(\$\{[^}]+})\s*\,\s*'(.+)'\s*\)\s*$", expression
        )
        if match:
            # warning: ugly hack ahead
            expression = re.sub(
                r"regex\s*\(\s*(\$\{[^}]+})\s*\,\s*'(.+)'\s*\)\s*$",
                "regexp_match(\\1, '",
                expression,
            )
            expression = "{}{}')".format(
                expression, format(match.group(2).replace("\\", "\\\\"))
            )

        if use_insert:
            if use_current_value:
                # ${field} = value to current_value('field')
                for (
                    calculate_name,
                    calculate_expression,
                ) in self.calculate_expressions.items():
                    expression = re.sub(
                        r"\$\{" + calculate_name + r"}",
                        r"[% "
                        + self.convert_expression(
                            calculate_expression, use_current_value=True
                        )
                        + r" %]",
                        expression,
                    )
                expression = re.sub(
                    r"\$\{([^}]+)}", r"[% current_value('\1') %]", expression
                )
            else:
                # ${field} = value to "field"
                for (
                    calculate_name,
                    calculate_expression,
                ) in self.calculate_expressions.items():
                    expression = re.sub(
                        r"\$\{" + calculate_name + r"}",
                        r"[% "
                        + self.convert_expression(
                            calculate_expression, use_current_value=False
                        )
                        + r" %]",
                        expression,
                    )
                expression = re.sub(r"\$\{([^}]+)}", r'[% "\1" %]', expression)
        else:
            if use_current_value:
                # ${field} = value to current_value('field')
                expression = re.sub(r"\$\{([^}]+)}", r"current_value('\1')", expression)
            else:
                # ${field} = value to "field"
                expression = re.sub(r"\$\{([^}]+)}", r'"\1"', expression)

        # today() to format_date(now()...)
        expression = re.sub(
            r"today\(\)", r"format_date(now(),'yyyy-MM-dd')", expression
        )

        # selected(1, 2) to 1 = 2
        expression = re.sub(
            r"selected\s*\(\s*(\$\{[^}]+})\,([^)]+)\)", r"\1 = \2", expression
        )

        if not use_insert:
            expression_try = QgsExpression(expression)
            if expression_try.hasParserError():
                self.warning.emit(
                    self.tr("Unsupported expression {}".format(original_expression))
                )

        return expression

    def process_project_write(self, document):
        nl = document.elementsByTagName("qgis")
        if nl.count() == 0:
            return

        qgisNode = nl.item(0)

        mapcanvasNode = document.createElement("mapcanvas")
        mapcanvasNode.setAttribute("name", "theMapCanvas")
        qgisNode.appendChild(mapcanvasNode)

        extent = QgsRectangle(297905, 3866631, 2336801, 7381331)

        ms = QgsMapSettings()
        ms.setDestinationCrs(self.output_project.crs())
        ms.setOutputSize(QSize(500, 500))
        ms.setExtent(extent)
        ms.writeXml(mapcanvasNode, document)

    def convert(self, output_directory, title=None, language=None):
        if not self.survey_layer:
            return ""

        os.makedirs(os.path.abspath(output_directory), exist_ok=True)

        # Settings handling
        settings_title = "survey"
        settings_id = ""
        settings_language = ""

        it = self.settings_layer.getFeatures()
        header_checked = False
        form_title_index = -1
        form_id_index = -1
        default_language_index = -1
        for feature in it:
            if not header_checked:
                if feature.fields().names()[0] != "Field1":
                    form_title_index = feature.fields().indexOf("form_title")
                    form_id_index = feature.fields().indexOf("form_id")
                    default_language_index = feature.fields().indexOf(
                        "default_language"
                    )
                else:
                    attributes = feature.attributes()
                    form_title_index = (
                        attributes.index("form_title")
                        if "form_title" in attributes
                        else -1
                    )
                    form_id_index = (
                        attributes.index("form_id") if "form_id" in attributes else -1
                    )
                    default_language_index = (
                        attributes.index("default_language")
                        if "default_language" in attributes
                        else -1
                    )
                header_checked = True
                continue

            if form_title_index >= 0 and feature.attribute(form_title_index):
                settings_title = feature.attribute(form_title_index)
            if form_id_index >= 0 and feature.attribute(form_id_index):
                settings_id = feature.attribute(form_id_index)
            if default_language_index >= 0 and feature.attribute(
                default_language_index
            ):
                settings_language = feature.attribute(default_language_index)
            break

        if title:
            settings_title = title

        if language:
            settings_language = language

        self.label_field_name = "label"
        if settings_language != "":
            self.label_field_name = "label::{}".format(settings_language)
            if self.label_field_name not in self.survey_layer.fields().names():
                self.error.emit(
                    self.tr(
                        "Specified {} language not found in the survey spreadsheet, aborting".format(
                            settings_language
                        )
                    )
                )
                return
            elif self.label_field_name not in self.choices_layer.fields().names():
                self.error.emit(
                    self.tr(
                        "Specified {} language not found in the choices spreadsheet, aborting".format(
                            settings_language
                        )
                    )
                )
                return

        settings_filename = title if title else settings_title
        settings_filename = (
            unicodedata.normalize("NFKD", settings_filename)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
        settings_filename = re.sub(r"[^\w\s-]", "", settings_filename)
        settings_filename = re.sub(r"[-\s]+", "-", settings_filename)

        self.info.emit(
            self.tr("Creating survey {} (id: {})".format(settings_title, settings_id))
        )

        # Project creationg
        self.output_file = str(
            os.path.join(output_directory, settings_filename + ".gpkg")
        )
        self.output_project = QgsProject()

        base_layer = QgsRasterLayer(
            "type=xyz&tilePixelRatio=1&url=https://tile.openstreetmap.org/%7Bz%7D/%7Bx%7D/%7By%7D.png&zmax=19&zmin=0&crs=EPSG3857",
            "OpenStreetMap",
            "wms",
        )
        self.output_project.setCrs(base_layer.crs())
        self.output_project.addMapLayer(base_layer)

        # Choices handling
        output_lists_fields = self.choices_layer.fields()
        output_lists_fields.remove(self.choices_layer.fields().indexOf("list_name"))
        lists = {}

        it = self.choices_layer.getFeatures()
        for feature in it:
            list_name = feature.attribute("list_name")
            if not list_name:
                continue

            list_name = str(list_name)
            if list_name not in lists:
                lists[list_name] = []
            lists[list_name].append(feature)

        for list_name, features in lists.items():
            writer_options = QgsVectorFileWriter.SaveVectorOptions()
            writer_options.actionOnExistingFile = (
                QgsVectorFileWriter.CreateOrOverwriteLayer
                if os.path.isfile(self.output_file)
                else QgsVectorFileWriter.CreateOrOverwriteFile
            )
            writer_options.layerName = "list_" + list_name
            writer_options.fileEncoding = "utf-8"
            output_lists_sink = QgsVectorFileWriter.create(
                self.output_file,
                output_lists_fields,
                Qgis.WkbType.NoGeometry,
                QgsCoordinateReferenceSystem(4326),
                QgsProject.instance().transformContext(),
                writer_options,
            )

            # Add pseudo-NULL value
            output_feature = QgsFeature(output_lists_fields)
            output_feature.setAttribute("name", "")
            output_feature.setAttribute(self.label_field_name, "")
            output_lists_sink.addFeature(output_feature)

            for feature in features:
                output_feature = QgsFeature(output_lists_fields)
                for field_name in output_lists_fields.names():
                    attribute_value = feature.attribute(field_name)
                    if field_name == "label":
                        html_fragment = html.fromstring(str(attribute_value))
                        attribute_value = html_fragment.text_content()
                    output_feature.setAttribute(field_name, attribute_value)
                output_lists_sink.addFeature(output_feature)

            output_lists_sink.flushBuffer()
            del output_lists_sink
            output_lists_layer = QgsVectorLayer(
                self.output_file + "|layername=" + writer_options.layerName,
                writer_options.layerName,
                "ogr",
            )
            output_lists_layer.setFlags(QgsMapLayer.Private)
            output_lists_layer.setCustomProperty("QFieldSync/cloud_action", "no_action")
            output_lists_layer.setCustomProperty("QFieldSync/action", "copy")
            self.output_project.addMapLayer(output_lists_layer)

        # Survey handling
        self.calculate_expressions = {}

        current_layer = [self.create_layer()]
        self.output_project.addMapLayer(current_layer[-1])

        current_editor_form = [current_layer[-1].editFormConfig()]
        current_editor_form[-1].invisibleRootContainer().clear()
        current_editor_form[-1].setLayout(Qgis.AttributeFormLayout.DragAndDrop)

        current_container = [
            QgsAttributeEditorContainer(
                "Survey", current_editor_form[-1].invisibleRootContainer()
            )
        ]
        current_container[-1].setType(Qgis.AttributeEditorContainerType.Tab)
        current_editor_form[-1].invisibleRootContainer().addChildElement(
            current_container[-1]
        )

        relation_context = QgsRelationContext(self.output_project)

        it = self.survey_layer.getFeatures()
        for feature in it:
            if not feature.attribute("type"):
                continue

            feature_type = str(feature.attribute("type")).strip().lower()
            feature_name = str(feature.attribute("name")).strip()
            feature_label = (
                str(feature.attribute(self.label_field_name)).strip()
                if feature.attribute(self.label_field_name)
                else ""
            )

            field_index = current_layer[-1].fields().indexOf(feature_name)

            relevant_container = None
            relevant_expression = (
                str(feature.attribute("relevant")).strip()
                if self.has_relevant and feature.attribute("relevant")
                else ""
            )
            if relevant_expression != "":
                relevant_expression = self.convert_expression(relevant_expression)
                if field_index >= 0 or feature_type == "begin repeat":
                    relevant_container = QgsAttributeEditorContainer(
                        feature_name + " - relevant", current_container[-1]
                    )
                    relevant_container.setShowLabel(False)
                    relevant_container.setType(
                        Qgis.AttributeEditorContainerType.GroupBox
                    )
                    relevant_container.setVisibilityExpression(
                        QgsOptionalExpression(QgsExpression(relevant_expression))
                    )

            if feature_type == "begin repeat" or feature_type == "begin_repeat":
                current_layer.append(self.create_layer(feature_name))
                self.output_project.addMapLayer(current_layer[-1])

                current_editor_form.append(current_layer[-1].editFormConfig())
                current_editor_form[-1].invisibleRootContainer().clear()
                current_editor_form[-1].setLayout(Qgis.AttributeFormLayout.DragAndDrop)

                current_container.append(
                    QgsAttributeEditorContainer(
                        "Survey", current_editor_form[-1].invisibleRootContainer()
                    )
                )
                current_container[-1].setType(Qgis.AttributeEditorContainerType.Tab)
                current_editor_form[-1].invisibleRootContainer().addChildElement(
                    current_container[-1]
                )

                relation = QgsRelation(relation_context)
                relation.setName(feature_name)
                relation.setReferencedLayer(current_layer[-2].id())
                relation.setReferencingLayer(current_layer[-1].id())
                relation.addFieldPair("uuid_parent", "uuid")
                relation.generateId()
                self.output_project.relationManager().addRelation(relation)

                editor_relation = QgsAttributeEditorRelation(
                    feature_name,
                    relation.id(),
                    current_editor_form[-2].invisibleRootContainer(),
                )
                editor_relation.setLabel(feature_label)
                editor_relation.setShowLabel(feature_label != "")
                if relevant_container:
                    relevant_container.addChildElement(editor_relation)
                    current_container[-2].addChildElement(relevant_container)
                else:
                    current_container[-2].addChildElement(editor_relation)
            elif feature_type == "end repeat" or feature_type == "end_repeat":
                if len(current_layer) > 1:
                    current_container.pop()
                    current_layer[-1].setEditFormConfig(current_editor_form[-1])
                    current_layer.pop()
                    current_editor_form.pop()
            elif feature_type == "begin group" or feature_type == "begin_group":
                current_container.append(
                    QgsAttributeEditorContainer(feature_label, current_container[-1])
                )
                current_container[-1].setType(
                    Qgis.AttributeEditorContainerType.GroupBox
                )
                current_container[-1].setShowLabel(feature_label != "")
                if relevant_expression != "":
                    current_container[-1].setVisibilityExpression(
                        QgsOptionalExpression(QgsExpression(relevant_expression))
                    )
                current_container[-2].addChildElement(current_container[-1])
            elif feature_type == "end group" or feature_type == "end_group":
                if len(current_container) > 1:
                    current_container.pop()
            elif feature_type == "note":
                editor_text = QgsAttributeEditorTextElement(
                    feature_name, current_container[-1]
                )

                if MARKDOWN_AVAILABLE:
                    feature_label = markdown.markdown(feature_label)

                editor_text.setText(
                    self.convert_expression(
                        feature_label, use_current_value=True, use_insert=True
                    )
                )
                editor_text.setShowLabel(False)
                current_container[-1].addChildElement(editor_text)
            elif field_index >= 0:
                editor_widget = None
                editor_element = None

                editor_widget = self.create_editor_widget(feature)
                if editor_widget:
                    current_layer[-1].setEditorWidgetSetup(field_index, editor_widget)
                    editor_element = QgsAttributeEditorField(
                        feature_name, field_index, current_container[-1]
                    )

                    if (
                        editor_widget.type() != "Hidden"
                        and feature_label.find("${") >= 0
                    ):
                        # Data-defined label
                        prop = QgsProperty()
                        prop.setExpressionString(
                            self.convert_label_expression(feature_label)
                        )
                        props = QgsPropertyCollection()
                        props.setProperty(
                            QgsEditFormConfig.DataDefinedProperty.Alias, prop
                        )
                        current_editor_form[-1].setDataDefinedFieldProperties(
                            feature_name, props
                        )

                    if feature_type == "calculate":
                        editor_element.setShowLabel(editor_widget.type() != "Hidden")
                        current_editor_form[-1].setReadOnly(field_index, True)
                    elif (
                        feature_type == "today"
                        or feature_type == "start"
                        or feature_type == "end"
                        or feature_type == "username"
                        or feature_type == "email"
                    ):
                        editor_element.setShowLabel(False)
                        current_editor_form[-1].setReadOnly(field_index, True)

                        if feature_type == "today":
                            current_layer[-1].setDefaultValueDefinition(
                                field_index,
                                QgsDefaultValue(
                                    "format_date(now(), 'yyyy-MM-dd')", False
                                ),
                            )
                        elif feature_type == "start" or feature_type == "end":
                            current_layer[-1].setDefaultValueDefinition(
                                field_index,
                                QgsDefaultValue(
                                    "format_date(now(), 'yyyy-MM-dd hh:mm:ss')",
                                    feature_type == "end",
                                ),
                            )
                        elif feature_type == "username":
                            current_layer[-1].setDefaultValueDefinition(
                                field_index, QgsDefaultValue("@cloud_username", False)
                            )
                        elif feature_type == "email":
                            current_layer[-1].setDefaultValueDefinition(
                                field_index, QgsDefaultValue("@cloud_useremail", False)
                            )
                    elif self.has_read_only:
                        field_read_only = (
                            str(feature.attribute("read_only")).strip().lower()
                            if feature.attribute("read_only")
                            else ""
                        )
                        current_editor_form[-1].setReadOnly(
                            field_index, field_read_only == "yes"
                        )

                    if relevant_container:
                        relevant_container.addChildElement(editor_element)
                        current_container[-1].addChildElement(relevant_container)
                    else:
                        current_container[-1].addChildElement(editor_element)

                    current_editor_form[-1].setLabelOnTop(field_index, True)

                field_trigger = (
                    str(feature.attribute("trigger")).strip()
                    if self.has_trigger and feature.attribute("trigger")
                    else ""
                )
                if field_trigger != "":
                    self.warning.emit(
                        "Unsupported trigger option for {}, ignored".format(
                            feature_name
                        )
                    )

                field_calculation = (
                    str(feature.attribute("calculation")).strip()
                    if self.has_calculation and feature.attribute("calculation")
                    else ""
                )
                field_default = (
                    str(feature.attribute("default")).strip()
                    if self.has_default and feature.attribute("default")
                    else ""
                )
                if field_calculation != "":
                    current_layer[-1].setDefaultValueDefinition(
                        field_index,
                        QgsDefaultValue(
                            self.convert_expression(field_calculation),
                            feature_type == "calculate",
                        ),
                    )
                elif field_default != "":
                    is_digit = field_default.replace(".", "", 1).isdigit()
                    current_layer[-1].setDefaultValueDefinition(
                        field_index,
                        QgsDefaultValue(
                            field_default if is_digit else "'{}'".format(field_default),
                            False,
                        ),
                    )

            elif (
                feature_type == "geopoint"
                or feature_type == "geotrace"
                or feature_type == "geoshape"
            ):
                continue
            else:
                type_details = str(feature.attribute("type")).split(" ")
                type_details[0] = type_details[0].lower()
                if (
                    type_details[0] not in self.FIELD_TYPES
                    and type_details[0] not in self.METADATA_TYPES
                ):
                    self.warning.emit(
                        self.tr("Unsupported type {}, skipping".format(feature_type))
                    )

        current_layer[0].setEditFormConfig(current_editor_form[0])

        output_project_file = str(
            os.path.join(output_directory, settings_filename + ".qgz")
        )
        self.output_project.writeProject.connect(self.process_project_write)
        self.output_project.write(output_project_file)
        return output_project_file

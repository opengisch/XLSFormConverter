import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from convert2qgis.errors import Convert2QgisBaseError
from qgis.core import QgsProcessingContext, QgsProcessingFeedback, QgsRectangle
from qgis.testing import start_app, unittest

start_app()

from xlsformconverter.xlsform_converter_algorithms import XlsformConverterAlgorithm
from xlsformconverter.tests.utilities import data_folder

BUILDINGS_XLS = Path(data_folder()) / "buildings.xls"


class TestGetBasemapUrl(unittest.TestCase):
    def setUp(self):
        self.alg = XlsformConverterAlgorithm()

    def test_osm_returns_xyz_url(self):
        url = self.alg._get_basemap_url(0)
        self.assertIn("type=xyz", url)
        self.assertIn("openstreetmap.org", url)

    def test_hot_returns_hot_url(self):
        url = self.alg._get_basemap_url(1)
        self.assertIn("openstreetmap.fr/hot", url)

    def test_invalid_index_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.alg._get_basemap_url(99)


class TestRectToCoords(unittest.TestCase):
    def setUp(self):
        self.alg = XlsformConverterAlgorithm()

    def test_format_is_xmin_ymin_xmax_ymax(self):
        rect = QgsRectangle(1.5, 2.5, 3.5, 4.5)
        result = self.alg._rect_to_coords(rect)
        self.assertEqual(result, "1.5, 2.5, 3.5, 4.5")


class TestXlsformConversion(unittest.TestCase):
    def setUp(self):
        self.output_dir = tempfile.mkdtemp()
        self.alg = XlsformConverterAlgorithm()
        self.alg.initAlgorithm()
        self.context = QgsProcessingContext()
        self.feedback = MagicMock(spec=QgsProcessingFeedback)

    def tearDown(self):
        shutil.rmtree(self.output_dir)

    def _run(self, extra_params=None):
        params = {
            "INPUT": str(BUILDINGS_XLS),
            "TITLE": "",
            "LANGUAGE": "",
            "BASEMAP": 0,
            "GROUPS_AS_TABS": False,
            "OUTPUT": self.output_dir,
            "OPEN_PROJECT_AFTER_CONVERSION": False,
        }
        if extra_params:
            params.update(extra_params)
        return self.alg.processAlgorithm(params, self.context, self.feedback)

    def test_output_key_points_to_output_dir(self):
        result = self._run()
        self.assertEqual(result["OUTPUT"], self.output_dir)

    def test_conversion_produces_qgis_project_file(self):
        self._run()
        qgs_files = list(Path(self.output_dir).glob("*.qg[sz]"))
        self.assertGreater(len(qgs_files), 0)

    def test_nonexistent_file_reports_error(self):
        self.alg.processAlgorithm(
            {
                "INPUT": "/nonexistent/form.xlsx",
                "TITLE": "",
                "LANGUAGE": "",
                "BASEMAP": 0,
                "GROUPS_AS_TABS": False,
                "OUTPUT": self.output_dir,
                "OPEN_PROJECT_AFTER_CONVERSION": False,
            },
            self.context,
            self.feedback,
        )
        self.feedback.reportError.assert_called_once()

    def test_invalid_xlsform_reports_fatal_error(self):
        with patch(
            "xlsformconverter.xlsform_converter_algorithms.convert_xlsform_to_qgis_project",
            side_effect=Convert2QgisBaseError("Invalid XLSForm structure"),
        ):
            self._run()
        args, kwargs = self.feedback.reportError.call_args
        fatal = args[1] if len(args) > 1 else kwargs.get("fatal", False)
        self.assertTrue(fatal)


class TestAlgorithmMetadata(unittest.TestCase):
    def setUp(self):
        self.alg = XlsformConverterAlgorithm()

    def test_init_algorithm_registers_expected_parameters(self):
        self.alg.initAlgorithm()
        param_names = {p.name() for p in self.alg.parameterDefinitions()}
        expected = {
            "INPUT", "TITLE", "LANGUAGE", "BASEMAP", "GROUPS_AS_TABS",
            "CRS", "EXTENT", "FEATURES", "SHOW_UNIQUE_LABEL",
            "OUTPUT", "OPEN_PROJECT_AFTER_CONVERSION",
        }
        self.assertEqual(param_names, expected)

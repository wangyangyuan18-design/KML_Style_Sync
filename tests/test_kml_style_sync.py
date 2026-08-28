from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kml_style_sync.kml_parser import analyze_file
from kml_style_sync.matcher import build_match_rows, candidates_for

KML = '''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Style id="lineA"><LineStyle><color>ff0000ff</color><width>2</width></LineStyle></Style>
    <Style id="pointA"><IconStyle><scale>1.2</scale></IconStyle></Style>
    <Folder><name>B1 Line</name>
      <Placemark><name>x</name><styleUrl>#lineA</styleUrl><LineString><coordinates>1,2,0 2,3,0</coordinates></LineString></Placemark>
    </Folder>
    <Folder><name>B2 Point</name>
      <Placemark><name>x</name><styleUrl>#pointA</styleUrl><Point><coordinates>1,2,0</coordinates></Point></Placemark>
      <Folder><name>Nested</name><Placemark><Point><coordinates>3,4,0</coordinates></Point></Placemark></Folder>
    </Folder>
  </Document>
</kml>'''

SOURCE = '''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <Folder><name>B2 Point</name><Placemark><Point><coordinates>1,2,0</coordinates></Point></Placemark></Folder>
  <Folder><name>Other Line</name><Placemark><LineString><coordinates>1,2,0 2,3,0</coordinates></LineString></Placemark></Folder>
</Document></kml>'''


class ParserMatcherTests(unittest.TestCase):
    def test_folder_order_geometry_and_nested_folder(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "x.kml"
            p.write_text(KML, encoding="utf-8")
            info = analyze_file(p)
            self.assertEqual([f.display_path for f in info.folders], ["B1 Line", "B2 Point", "B2 Point / Nested"])
            self.assertEqual([f.geometry_type for f in info.folders], ["LINE", "POINT", "POINT"])
            self.assertEqual(info.folders[0].standard_style_key, "#lineA")
            self.assertEqual(info.folders[0].standard_style_ratio, 1.0)

    def test_match_is_name_plus_geometry_only_and_candidates_are_filtered(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            source = root / "a.kml"
            template = root / "b.kml"
            source.write_text(SOURCE, encoding="utf-8")
            template.write_text(KML, encoding="utf-8")
            a = analyze_file(source).folders
            b = analyze_file(template).folders
            rows = build_match_rows(a, b)
            # A-centric: one row per effective A layer, not one row per B layer.
            self.assertEqual(len(rows), len(a))
            self.assertEqual(rows[0].source.name, "B2 Point")
            self.assertEqual(rows[0].template.name, "B2 Point")
            self.assertIsNone(rows[1].template)  # Other Line has no same-name B
            self.assertEqual([f.name for f in candidates_for(a[1], b)], ["B1 Line"])

    def test_name_match_rejects_wrong_geometry(self):
        a = [
            # Same name as B1 Line, but wrong Geometry: must remain unmatched.
            type("Layer", (), {"name": "B1 Line", "folder_path": ("B1 Line",), "geometry_type": "POINT"})(),
        ]
        b = [
            type("Layer", (), {"name": "B1 Line", "folder_path": ("B1 Line",), "geometry_type": "LINE"})(),
        ]
        rows = build_match_rows(a, b)
        self.assertIsNone(rows[0].template)


if __name__ == "__main__":
    unittest.main()

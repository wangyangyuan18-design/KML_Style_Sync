from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kml_style_sync.kml_parser import analyze_file
from kml_style_sync.matcher import build_match_rows
from kml_style_sync.models import FolderInfo


KML = '''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <Style id="p"><IconStyle><scale>1</scale></IconStyle></Style>
  <Style id="l"><LineStyle><color>ff0000ff</color><width>2</width></LineStyle></Style>
  <Folder>
    <name>Container</name>
    <Folder>
      <name>12C</name>
      <Placemark><styleUrl>#p</styleUrl><Point><coordinates>1,2,0</coordinates></Point></Placemark>
    </Folder>
    <Folder>
      <name>24C</name>
      <Placemark><styleUrl>#l</styleUrl><LineString><coordinates>1,2,0 2,3,0</coordinates></LineString></Placemark>
    </Folder>
  </Folder>
  <Folder>
    <name>Empty</name>
  </Folder>
  <Folder>
    <name>Direct</name>
    <Placemark><styleUrl>#p</styleUrl><Point><coordinates>3,4,0</coordinates></Point></Placemark>
    <Folder><name>Child</name><Placemark><Point><coordinates>5,6,0</coordinates></Point></Placemark></Folder>
  </Folder>
</Document>
</kml>
'''


class EffectiveLayerTests(unittest.TestCase):
    def _write_kml(self, directory: str) -> Path:
        path = Path(directory) / "sample.kml"
        path.write_text(KML, encoding="utf-8")
        return path

    def test_only_folders_with_direct_geometry_are_effective(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            info = analyze_file(self._write_kml(tmp))
            self.assertEqual(
                [(f.display_path, f.geometry_type) for f in info.folders],
                [("Container / 12C", "POINT"), ("Container / 24C", "LINE"), ("Direct", "POINT")],
            )

    def test_parent_geometry_is_based_on_its_own_direct_placemarks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            info = analyze_file(self._write_kml(tmp))
            direct = next(f for f in info.folders if f.display_path == "Direct")
            self.assertEqual(direct.geometry_type, "POINT")
            self.assertEqual(direct.feature_count, 1)

    def test_matcher_does_not_use_geometry_alone(self) -> None:
        a = [
            FolderInfo("FAT", ("FAT",), "POINT", 1),
            FolderInfo("FDT", ("FDT",), "POINT", 1),
        ]
        b = [
            FolderInfo("FDT", ("FDT",), "POINT", 1),
            FolderInfo("NEW", ("NEW",), "POINT", 1),
        ]
        rows = build_match_rows(a, b)
        self.assertEqual(rows[0].source.name, "FDT")
        self.assertIsNone(rows[1].source)


if __name__ == "__main__":
    unittest.main()

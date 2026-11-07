from kml_style_sync.kml_parser import normalize_name


def test_strip_home_pass_units_suffix():
    assert normalize_name("Sdus=1012") == "sdus"


def test_strip_sub_box_count_suffix():
    assert normalize_name("SUB BOX(70/30)=8") == "sub box(70/30)"


def test_strip_plain_numeric_suffix():
    assert normalize_name("Church=3") == "church"


def test_do_not_strip_numbers_inside_base_name():
    assert normalize_name("SUB BOX (70/30)") == "sub box (70/30)"

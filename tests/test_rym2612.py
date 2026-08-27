from xml.etree import ElementTree as ET

from smd_music.ir import FmOperator, FmPatch
from smd_music.ym2612 import patch_to_rym2612


def _patch():
    ops = [
        FmOperator(i, dt, mul, tl, rs, ar, am, dr, sr, sl, rr, ssg)
        for i, dt, mul, tl, rs, ar, am, dr, sr, sl, rr, ssg in [
            (1, 0, 1, 20, 0, 31, 0, 12, 8, 4, 6, 0),
            (3, 5, 2, 30, 1, 30, 1, 11, 7, 5, 5, 8),
            (2, 2, 3, 40, 2, 29, 0, 10, 6, 6, 4, 0),
            (4, 7, 4, 50, 3, 28, 1, 9, 5, 7, 3, 15),
        ]
    ]
    return FmPatch("test", 4, 5, 2, 3, True, True, ops)


def test_rym2612_native_xml_parameters_roundtrip_semantics():
    root = ET.fromstring(patch_to_rym2612(_patch(), name="A&B").decode())
    assert root.tag == "RYM2612Params"
    assert root.attrib["patchName"] == "A&B"
    params = {node.attrib["id"]: node.attrib.get("value") for node in root.findall("PARAM")}
    assert params["Algorithm"] == "5.0"
    assert params["Feedback"] == "5.0"
    assert params["AMS"] == "2.0"
    assert params["FMS"] == "3.0"
    assert params["OP1TL"] == "107.0"  # 127 - YM attenuation 20
    assert params["OP1D2L"] == "11.0"  # 15 - YM sustain level 4
    assert params["OP3DT"] == "-1.0"   # YM DT register 5
    assert params["OP4DT"] == "-3.0"   # YM DT register 7
    assert params["OP3SSGEG"] == "1.0"
    assert params["OP4SSGEG"] == "8.0"
    assert params["OP1Vel"] == "0.0"

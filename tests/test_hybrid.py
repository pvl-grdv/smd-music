from smd_music.ir import FmOperator, FmPatch
from smd_music.hybrid import patch_distance


def patch(tl=10):
    return FmPatch(
        id='x', algorithm=4, feedback=3, ams=0, fms=0,
        pan_left=True, pan_right=True,
        operators=[FmOperator(i, 0, i, tl, 0, 31, 0, 10, 5, 4, 6, 0) for i in range(1,5)],
    )


def test_patch_distance_allows_volume_change():
    assert patch_distance(patch(10), patch(20)) < 20


def test_patch_distance_penalizes_algorithm():
    a = patch()
    b = patch()
    b.algorithm = 7
    assert patch_distance(a, b) >= 1000

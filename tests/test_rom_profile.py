from smd_music.genesis_rom import SOR1_WORLD_REV00


def test_known_sor1_profile_constants():
    assert SOR1_WORLD_REV00.size == 0x80000
    assert SOR1_WORLD_REV00.sound_driver_kosinski_offset == 0x795A2
    assert SOR1_WORLD_REV00.sound_driver_copy_length == 0x1EC7
    assert SOR1_WORLD_REV00.sound_driver_decompressed_length == 0x1F00

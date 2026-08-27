from smd_music.kosinski import decompress


def test_literal_stream():
    # Descriptor bits LSB first: 1,1,1,0,1, then long-copy terminator.
    # This deliberately tests only decoder mechanics; game data is not vendored.
    data = bytes([0x17, 0x00, ord("A"), ord("B"), ord("C"), 0x00, 0x00, 0x00])
    out, _ = decompress(data)
    assert out == b"ABC"

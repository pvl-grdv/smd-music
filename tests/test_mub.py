import mido

from smd_music.mub import MUB


def test_minimal_legacy_mub_to_midi(tmp_path):
    # Legacy-style sequence header at offset 1. FM1 pointer = 0x2F,
    # matching the conventional MUCOM88 header layout. Other tracks are empty.
    data = bytearray(0x40)
    header = 1
    data[header] = 198
    data[header + 1:header + 3] = (0x2F).to_bytes(2, "little")
    eof_pos = header + 1 + 11 * 4
    data[eof_pos:eof_pos + 2] = (0x38).to_bytes(2, "little")
    start = header + 0x2F
    data[start:start + 3] = bytes([24, 0x40, 0x00])

    mub = MUB.parse(bytes(data))
    out = tmp_path / "x.mid"
    mub.to_midi(out, loops=1)
    mid = mido.MidiFile(out)
    assert mid.type == 1
    assert mid.ticks_per_beat == 96
    assert any(msg.type == "note_on" for msg in mid.tracks[1])

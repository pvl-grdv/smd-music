from smd_music.mucom_voice import MucomVoice, MucomVoiceBank


def test_mucom_voice_decodes_opn_layout(tmp_path):
    d = bytearray(32)
    # Logical OP2 maps to MUCOM offset 2 -> register-group byte index 3.
    d[3] = (5 << 4) | 7
    d[7] = 42
    d[11] = (2 << 6) | 29
    d[15] = 0x80 | 17
    d[19] = 11
    d[23] = (9 << 4) | 6
    d[25] = (6 << 3) | 4
    d[26:32] = b"BASS  "
    voice = MucomVoice(12, bytes(d))
    patch = voice.to_patch()
    op2 = next(op for op in patch.operators if op.logical_operator == 2)
    assert (op2.detune, op2.multiple, op2.total_level) == (5, 7, 42)
    assert (op2.rate_scale, op2.attack_rate) == (2, 29)
    assert (op2.am_enable, op2.decay_rate) == (1, 17)
    assert (op2.sustain_rate, op2.sustain_level, op2.release_rate) == (11, 9, 6)
    assert (patch.algorithm, patch.feedback) == (4, 6)
    assert voice.display_name == "MUCOM88-012-BASS"

    path = tmp_path / "voice.dat"
    path.write_bytes(bytes(d) * 2)
    bank = MucomVoiceBank.load(path)
    assert len(bank.voices) == 2

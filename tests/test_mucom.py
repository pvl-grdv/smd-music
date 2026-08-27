from smd_music.mucom import MucProject


def test_muc_metadata(tmp_path):
    p = tmp_path / "song.muc"
    p.write_text("#mucom88 1.5\n#title Demo\n#voice voice.dat\n#pcm pcm.bin\n", encoding="utf-8")
    project = MucProject.load(p)
    assert project.metadata["title"] == "Demo"
    assert project.companion("voice").name == "voice.dat"
    assert project.companion("pcm").name == "pcm.bin"

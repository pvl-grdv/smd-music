from smd_music.mucom import MucProject


def test_muc_metadata(tmp_path):
    p = tmp_path / "song.muc"
    p.write_text("#mucom88 1.5\n#title Demo\n#voice voice.dat\n#pcm pcm.bin\n", encoding="utf-8")
    project = MucProject.load(p)
    assert project.metadata["title"] == "Demo"
    assert project.companion("voice").name == "voice.dat"
    assert project.companion("pcm").name == "pcm.bin"


def test_find_mucom88_js_local_node_modules(tmp_path):
    from smd_music.mucom import find_mucom88_js

    module = tmp_path / "node_modules" / "mucom88-js" / "dist" / "index.js"
    module.parent.mkdir(parents=True)
    module.write_text("export class Mucom88 {}")
    assert find_mucom88_js(tmp_path) == module.resolve()

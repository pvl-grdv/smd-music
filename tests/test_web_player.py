from pathlib import Path
import mido

from smd_music.web_player import _midi_notes


def test_midi_notes_reads_track_and_duration(tmp_path: Path):
    midi = mido.MidiFile(type=1, ticks_per_beat=96)
    tr = mido.MidiTrack(); midi.tracks.append(tr)
    tr.append(mido.MetaMessage('track_name', name='Bass', time=0))
    tr.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(100), time=0))
    tr.append(mido.Message('note_on', note=45, velocity=100, time=0))
    tr.append(mido.Message('note_off', note=45, velocity=0, time=96))
    p = tmp_path/'x.mid'; midi.save(p)
    duration, ppq, tracks = _midi_notes(p)
    assert ppq == 96
    assert abs(duration - .6) < 1e-6
    assert tracks[0]['name'] == 'Bass'
    assert tracks[0]['notes'][0]['pitch'] == 45

from __future__ import annotations

import base64
import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

import mido

from .mucom_pcm import MucomPcmBank
from .mucom_voice import MucomVoiceBank


def _midi_notes(path: str | Path) -> tuple[float, int, list[dict[str, Any]]]:
    midi = mido.MidiFile(path)
    tempo = 500000
    tracks: list[dict[str, Any]] = []
    max_end = 0.0

    # This viewer currently targets constant-tempo Type-1 DAW MIDI.  The
    # existing SoR arrangement is 100 BPM.  We still read the first tempo from
    # the file rather than hard-coding it.
    for tr in midi.tracks:
        for msg in tr:
            if msg.type == 'set_tempo':
                tempo = msg.tempo
                break
        else:
            continue
        break
    sec_per_tick = (tempo / 1_000_000.0) / midi.ticks_per_beat

    for index, tr in enumerate(midi.tracks):
        abs_tick = 0
        name = f'Track {index}'
        pending: dict[tuple[int, int], list[tuple[int, int]]] = {}
        notes: list[dict[str, Any]] = []
        for msg in tr:
            abs_tick += msg.time
            if msg.type == 'track_name':
                name = msg.name.strip() or name
            elif msg.type == 'note_on' and msg.velocity > 0:
                key = (getattr(msg, 'channel', 0), msg.note)
                pending.setdefault(key, []).append((abs_tick, msg.velocity))
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                key = (getattr(msg, 'channel', 0), msg.note)
                stack = pending.get(key)
                if not stack:
                    continue
                start_tick, velocity = stack.pop(0)
                start = start_tick * sec_per_tick
                end = max(start + sec_per_tick, abs_tick * sec_per_tick)
                notes.append({
                    'start': round(start, 6),
                    'duration': round(end - start, 6),
                    'pitch': msg.note,
                    'velocity': velocity,
                    'channel': key[0],
                })
                max_end = max(max_end, end)
        if notes:
            notes.sort(key=lambda n: (n['start'], n['pitch']))
            tracks.append({'name': name, 'notes': notes})
    return max(max_end, midi.length), midi.ticks_per_beat, tracks


def _patch_json(bank: MucomVoiceBank, program: int) -> dict[str, Any]:
    voice = bank.by_program(program)
    patch = voice.to_patch()
    return {
        'program': program,
        'name': voice.name or f'@{program}',
        'algorithm': patch.algorithm,
        'feedback': patch.feedback,
        'ams': patch.ams,
        'fms': patch.fms,
        'operators': [asdict(op) for op in sorted(patch.operators, key=lambda op: op.logical_operator)],
    }


def build_web_player(
    arrangement_midi: str | Path,
    voice_dat: str | Path,
    pcm_bin: str | Path,
    out_dir: str | Path,
    *,
    title: str = 'Sega Mega Drive reconstruction',
    reference_vgm: str | Path | None = None,
    fm_track_programs: dict[str, int] | None = None,
    psg_tracks: set[str] | None = None,
    drum_tracks: set[str] | None = None,
) -> dict[str, Any]:
    """Build an offline WebAudio timeline/player bundle.

    The browser synth is intentionally a preview renderer, not a cycle-accurate
    YM2612 emulator.  It preserves real MUCOM voice parameters and PCM samples
    so a future libvgm/ymfm AudioWorklet can replace the synth without changing
    the project JSON or UI.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    samples_dir = out / 'samples'
    presets_dir = out / 'presets'
    reference_dir = out / 'reference'
    samples_dir.mkdir(exist_ok=True)
    presets_dir.mkdir(exist_ok=True)

    duration, ppq, tracks = _midi_notes(arrangement_midi)
    bank = MucomVoiceBank.load(voice_dat)
    fm_track_programs = fm_track_programs or {}
    psg_tracks = psg_tracks or set()
    drum_tracks = drum_tracks or set()

    used_programs = sorted(set(fm_track_programs.values()))
    patches = {str(p): _patch_json(bank, p) for p in used_programs}
    for p in used_programs:
        voice = bank.by_program(p)
        (presets_dir / f'{voice.display_name}.rym2612').write_bytes(voice.to_rym2612())

    pcm_bank = MucomPcmBank.load(pcm_bin)
    pcm_meta: dict[str, Any] = {}
    for sample in pcm_bank.samples:
        # For the current SoR source @1/@2 are the two samples used by the song.
        safe = ''.join(ch if ch.isalnum() or ch in '-_ ' else '_' for ch in sample.name).strip()
        wav_name = f'{sample.number:02d}-{safe}.wav'
        sample.write_wav(samples_dir / wav_name)
        wav_path = samples_dir / wav_name
        pcm_meta[str(sample.number)] = {
            'number': sample.number,
            'name': sample.name,
            'url': f'samples/{wav_name}',
            'data_base64': base64.b64encode(wav_path.read_bytes()).decode('ascii'),
        }

    for tr in tracks:
        name = tr['name']
        if name in fm_track_programs:
            tr['kind'] = 'fm'
            tr['program'] = fm_track_programs[name]
        elif name in psg_tracks:
            tr['kind'] = 'psg'
        elif name in drum_tracks:
            tr['kind'] = 'drums'
        else:
            tr['kind'] = 'midi'

    midi_name = 'arrangement.mid'
    shutil.copy2(arrangement_midi, out / midi_name)
    reference_name = None
    if reference_vgm:
        reference_dir.mkdir(exist_ok=True)
        src = Path(reference_vgm)
        reference_name = f'reference/{src.name}'
        shutil.copy2(src, out / reference_name)

    project = {
        'format': 'smd-music-web-player-v1',
        'title': title,
        'duration': round(duration, 6),
        'ppq': ppq,
        'bpm': 100.0,
        'tracks': tracks,
        'patches': patches,
        'pcm': pcm_meta,
        'assets': {
            'midi': midi_name,
            'reference_vgm': reference_name,
        },
        'engine': {
            'name': 'WebAudio FM preview',
            'accuracy': 'approximate',
            'note': 'Uses real MUCOM voice parameters and PCM samples; intended to be replaced by a libvgm/ymfm AudioWorklet for bit-accurate playback.',
        },
    }
    packed = json.dumps(project, ensure_ascii=False, separators=(',', ':'))
    (out / 'project.json').write_text(packed, encoding='utf-8')
    (out / 'project.js').write_text('window.SMD_PROJECT=' + packed + ';\n', encoding='utf-8')

    template_root = Path(__file__).with_name('web')
    for filename in ('index.html', 'app.js', 'style.css'):
        shutil.copy2(template_root / filename, out / filename)
    return project

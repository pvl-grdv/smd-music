from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import mido

from .muc_sequence import MucNote, MucSong, _merge_ties
from .mucom_pcm import MucomPcmBank
from .mucom_voice import MucomVoiceBank


@dataclass(frozen=True, slots=True)
class ResolvedFmNote:
    source_channel: str
    program: int
    patch_name: str
    note: MucNote


def _ascii_marker(value: str) -> str:
    return value.encode("ascii", errors="backslashreplace").decode("ascii")


def _midi_channel(index: int) -> int:
    # Reserve MIDI channel 10 (zero-based 9) for percussion.
    value = index % 15
    return value if value < 9 else value + 1


def _ticks_per_clock(ppq: int, bpm: float, clocks_per_second: float) -> float:
    return (ppq * bpm / 60.0) / clocks_per_second


def _velocity(volume: int, kind: str) -> int:
    maximum = 255 if kind == "adpcm" else 15
    return max(1, min(127, round(max(0, min(maximum, volume)) / maximum * 127)))


def _note_gate_duration(note: MucNote) -> float:
    """Return key-on duration in MUCOM clocks."""
    duration = float(note.duration_clock)
    if note.tied_to_next or note.tied_from_previous:
        return duration
    return max(1e-9, duration - max(0, note.gate))


def _append_absolute(track: mido.MidiTrack, events: list[tuple[int, int, mido.Message | mido.MetaMessage]]) -> None:
    events.sort(key=lambda item: (item[0], item[1]))
    previous = 0
    for tick, _, msg in events:
        msg.time = max(0, tick - previous)
        track.append(msg)
        previous = tick


def resolve_fm_notes(song: MucSong, bank: MucomVoiceBank) -> list[ResolvedFmNote]:
    out: list[ResolvedFmNote] = []
    for source_ch, track in song.tracks.items():
        if track.kind != "fm":
            continue
        for note in _merge_ties(track.notes):
            if note.patch is None:
                continue
            voice = bank.resolve(note.patch)
            out.append(ResolvedFmNote(source_ch, voice.program, voice.name, note))
    return out


def write_plugin_midi(
    song: MucSong,
    bank: MucomVoiceBank,
    output: str | Path,
    *,
    bpm: float = 100.0,
    ppq: int = 96,
    clocks_per_second: float = 60.0,
    max_clock: float | None = None,
) -> dict[str, object]:
    """Write a DAW/plugin-oriented MIDI from MUC source.

    FM notes are grouped by native MUCOM voice program, so one RYM2612
    instance/preset can be placed on each DAW track. SSG stays one track per
    source channel; ADPCM is exposed as MIDI percussion triggers and WAVs.
    """
    midi = mido.MidiFile(type=1, ticks_per_beat=ppq)
    conductor = mido.MidiTrack()
    midi.tracks.append(conductor)
    conductor.append(mido.MetaMessage("track_name", name="Conductor", time=0))
    conductor.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    conductor.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    tpc = _ticks_per_clock(ppq, bpm, clocks_per_second)

    fm_notes = resolve_fm_notes(song, bank)
    grouped: dict[int, list[ResolvedFmNote]] = {}
    for item in fm_notes:
        if max_clock is not None and float(item.note.start_clock) >= max_clock:
            continue
        grouped.setdefault(item.program, []).append(item)

    track_manifest: list[dict[str, object]] = []
    track_index = 0
    for program in sorted(grouped):
        items = grouped[program]
        voice = bank.by_program(program)
        tr = mido.MidiTrack()
        midi.tracks.append(tr)
        label = f"FM @{program:03d} {voice.name or 'unnamed'}"
        # MIDI track-name text is safest as ASCII for broad DAW compatibility.
        tr.append(mido.MetaMessage("track_name", name=_ascii_marker(label), time=0))
        tr.append(mido.MetaMessage("instrument_name", name="RYM2612", time=0))
        tr.append(mido.MetaMessage("marker", text=f"MUCOM_PATCH={program}", time=0))
        events: list[tuple[int, int, mido.Message | mido.MetaMessage]] = []
        ch = _midi_channel(track_index)
        track_index += 1
        source_channels: set[str] = set()
        for item in items:
            note = item.note
            source_channels.add(item.source_channel)
            start_clock = float(note.start_clock)
            end_clock = start_clock + _note_gate_duration(note)
            if max_clock is not None:
                end_clock = min(end_clock, max_clock)
            if end_clock <= start_clock:
                continue
            start = round(start_clock * tpc)
            end = max(start + 1, round(end_clock * tpc))
            pitch = max(0, min(127, note.pitch))
            velocity = _velocity(note.volume, "fm")
            pan_cc = 0 if note.pan == 2 else 127 if note.pan == 1 else 64
            events.append((start, 0, mido.Message("control_change", channel=ch, control=10, value=pan_cc, time=0)))
            events.append((start, 2, mido.Message("note_on", channel=ch, note=pitch, velocity=velocity, time=0)))
            events.append((end, 1, mido.Message("note_off", channel=ch, note=pitch, velocity=0, time=0)))
        _append_absolute(tr, events)
        tr.append(mido.MetaMessage("end_of_track", time=0))
        track_manifest.append({
            "midi_track": len(midi.tracks) - 1,
            "name": label,
            "kind": "fm",
            "mucom_program": program,
            "mucom_voice_name": voice.name,
            "preset": f"FM/{voice.display_name}.rym2612",
            "source_channels": sorted(source_channels),
            "note_count": len(items),
        })

    for source_ch, src in sorted(song.tracks.items()):
        if src.kind != "ssg" or not src.notes:
            continue
        tr = mido.MidiTrack()
        midi.tracks.append(tr)
        label = f"PSG {source_ch}"
        tr.append(mido.MetaMessage("track_name", name=label, time=0))
        tr.append(mido.MetaMessage("instrument_name", name="SN76489 / PSG", time=0))
        events = []
        ch = _midi_channel(track_index)
        track_index += 1
        notes = _merge_ties(src.notes)
        count = 0
        for note in notes:
            start_clock = float(note.start_clock)
            if max_clock is not None and start_clock >= max_clock:
                continue
            end_clock = start_clock + _note_gate_duration(note)
            if max_clock is not None:
                end_clock = min(end_clock, max_clock)
            if end_clock <= start_clock:
                continue
            start = round(start_clock * tpc)
            end = max(start + 1, round(end_clock * tpc))
            pitch = max(0, min(127, note.pitch))
            events.append((start, 2, mido.Message("note_on", channel=ch, note=pitch, velocity=_velocity(note.volume, "ssg"), time=0)))
            events.append((end, 1, mido.Message("note_off", channel=ch, note=pitch, velocity=0, time=0)))
            count += 1
        _append_absolute(tr, events)
        tr.append(mido.MetaMessage("end_of_track", time=0))
        track_manifest.append({
            "midi_track": len(midi.tracks) - 1,
            "name": label,
            "kind": "psg",
            "source_channels": [source_ch],
            "note_count": count,
        })

    # One editable percussion track. MUCOM K-track @1/@2 are mapped to GM
    # kick/snare positions only as trigger locations; audio comes from WAVs.
    k = song.tracks.get("K")
    if k and k.notes:
        tr = mido.MidiTrack()
        midi.tracks.append(tr)
        tr.append(mido.MetaMessage("track_name", name="PCM Drums", time=0))
        tr.append(mido.MetaMessage("instrument_name", name="GarageBand Sampler", time=0))
        events = []
        mapping = {1: 36, 2: 38, 3: 39, 4: 46, 5: 49}
        count = 0
        for note in _merge_ties(k.notes):
            start_clock = float(note.start_clock)
            if max_clock is not None and start_clock >= max_clock:
                continue
            sample_no = int(note.patch) if isinstance(note.patch, int) else 1
            midi_note = mapping.get(sample_no, 39)
            start = round(start_clock * tpc)
            end = start + max(1, round(min(3.0, _note_gate_duration(note)) * tpc))
            events.append((start, 2, mido.Message("note_on", channel=9, note=midi_note, velocity=_velocity(note.volume, "adpcm"), time=0)))
            events.append((end, 1, mido.Message("note_off", channel=9, note=midi_note, velocity=0, time=0)))
            count += 1
        _append_absolute(tr, events)
        tr.append(mido.MetaMessage("end_of_track", time=0))
        track_manifest.append({
            "midi_track": len(midi.tracks) - 1,
            "name": "PCM Drums",
            "kind": "adpcm",
            "source_channels": ["K"],
            "note_count": count,
            "sample_note_map": {str(key): value for key, value in mapping.items()},
        })

    conductor.append(mido.MetaMessage("end_of_track", time=0))
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    midi.save(out)
    return {
        "path": str(out),
        "bpm": bpm,
        "ppq": ppq,
        "clocks_per_second": clocks_per_second,
        "max_clock": max_clock,
        "tracks": track_manifest,
    }


def build_muc_daw_pack(
    muc_path: str | Path,
    out_dir: str | Path,
    *,
    bpm: float = 100.0,
    ppq: int = 96,
    clocks_per_second: float = 60.0,
    max_clock: float | None = None,
) -> dict[str, object]:
    """Build an editable MUC-source pack for GarageBand/RYM2612."""
    muc = Path(muc_path)
    song = MucSong.load(muc)
    voice_name = song.metadata.get("voice")
    pcm_name = song.metadata.get("pcm")
    if not voice_name:
        raise ValueError("MUC source has no #voice companion")
    voice_path = muc.parent / voice_name
    if not voice_path.exists():
        raise FileNotFoundError(voice_path)
    bank = MucomVoiceBank.load(voice_path)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    midi_info = write_plugin_midi(
        song, bank, out / f"{song.metadata.get('title', muc.stem)} - plugin.mid",
        bpm=bpm, ppq=ppq, clocks_per_second=clocks_per_second,
        max_clock=max_clock,
    )

    used_programs = sorted({item.program for item in resolve_fm_notes(song, bank)})
    fm_dir = out / "FM"
    bank.export_rym2612(fm_dir, programs=set(used_programs))

    pcm_manifest: list[dict[str, object]] = []
    if pcm_name:
        pcm_path = muc.parent / pcm_name
        if pcm_path.exists():
            pcm_bank = MucomPcmBank.load(pcm_path)
            used_pcm = {
                int(n.patch) for n in song.tracks["K"].notes
                if isinstance(n.patch, int)
            } if "K" in song.tracks else set()
            pcm_dir = out / "PCM"
            pcm_dir.mkdir(exist_ok=True)
            for sample in pcm_bank.samples:
                if used_pcm and sample.number not in used_pcm:
                    continue
                safe = ''.join(ch if ch.isalnum() or ch in '-_ ' else '_' for ch in sample.name).strip()
                path = sample.write_wav(pcm_dir / f"{sample.number:02d}-{safe}.wav")
                pcm_manifest.append({
                    "mucom_program": sample.number,
                    "name": sample.name,
                    "wav": str(path.relative_to(out)),
                    "midi_note": {1: 36, 2: 38, 3: 39, 4: 46, 5: 49}.get(sample.number, 39),
                })

    manifest = {
        "format": "smd-music-mucom-daw-pack-v1",
        "title": song.metadata.get("title", muc.stem),
        "composer": song.metadata.get("composer"),
        "source": {
            "muc": muc.name,
            "muc_sha256": hashlib.sha256(muc.read_bytes()).hexdigest(),
            "voice": voice_name,
            "voice_sha256": hashlib.sha256(voice_path.read_bytes()).hexdigest(),
            "pcm": pcm_name,
        },
        "timing": {
            "bpm": bpm,
            "ppq": ppq,
            "clocks_per_second": clocks_per_second,
            "max_clock": max_clock,
        },
        "used_fm_programs": used_programs,
        "midi": midi_info,
        "pcm": pcm_manifest,
        "notes": [
            "Plugin MIDI preserves MUCOM base note pitch. Do not apply the octave shifts used by General MIDI mockups.",
            "Load the matching .rym2612 preset on each FM track.",
            "PCM drum MIDI notes are trigger positions; load the bundled WAV samples in GarageBand Sampler/Drum Machine Designer.",
            "MUCOM source is a higher-level composition source but may differ from the final Mega Drive port; compare against VGM/ROM for final-game fidelity.",
        ],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest

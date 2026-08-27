from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
import re

import mido


_NOTE_PC = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}
CHANNEL_KIND = {
    "A": "fm", "B": "fm", "C": "fm",
    "D": "ssg", "E": "ssg", "F": "ssg",
    "G": "rhythm",
    "H": "fm", "I": "fm", "J": "fm",
    "K": "adpcm",
}


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp932", errors="replace")


def _read_num(source: str, pos: int, *, signed: bool = False) -> tuple[int | None, int]:
    start = pos
    sign = 1
    if signed and pos < len(source) and source[pos] in "+-":
        sign = -1 if source[pos] == "-" else 1
        pos += 1
    if pos < len(source) and source[pos] == "$":
        pos += 1
        first = pos
        while pos < len(source) and source[pos] in "0123456789abcdefABCDEF":
            pos += 1
        return (sign * int(source[first:pos], 16), pos) if pos > first else (None, start)
    first = pos
    while pos < len(source) and source[pos].isdigit():
        pos += 1
    return (sign * int(source[first:pos]), pos) if pos > first else (None, start)


def _expand_loops(source: str) -> str:
    """Expand MUCOM ``[...]n`` loops and the ``/`` last-iteration escape.

    BARE1 sources do not use macros, so textual expansion is a compact and
    deterministic representation for direct source analysis.
    """
    def group(pos: int, nested: bool) -> tuple[str, int]:
        pieces: list[str] = []
        slash_index: int | None = None
        while pos < len(source):
            ch = source[pos]
            if ch == '"':
                end = source.find('"', pos + 1)
                if end < 0:
                    end = len(source) - 1
                pieces.append(source[pos:end + 1])
                pos = end + 1
                continue
            if ch == "[":
                expanded, pos = group(pos + 1, True)
                pieces.append(expanded)
                continue
            if ch == "]" and nested:
                pos += 1
                count, next_pos = _read_num(source, pos)
                count = count if count is not None else 2
                pos = next_pos if next_pos > pos else pos
                full = "".join(pieces)
                if slash_index is None:
                    return full * count, pos
                prefix = "".join(pieces[:slash_index])
                return full * (count - 1) + prefix, pos
            if ch == "/" and nested and slash_index is None:
                slash_index = len(pieces)
                pos += 1
                continue
            pieces.append(ch)
            pos += 1
        return "".join(pieces), pos

    return group(0, False)[0]


@dataclass(slots=True)
class MucNote:
    channel: str
    start_clock: Fraction
    duration_clock: Fraction
    pitch: int
    patch: int | str | None
    volume: int
    pan: int
    gate: int
    detune: int
    tied_from_previous: bool = False
    tied_to_next: bool = False


@dataclass(slots=True)
class MucTrack:
    channel: str
    kind: str
    notes: list[MucNote] = field(default_factory=list)
    end_clock: Fraction = Fraction(0)
    loop_clock: Fraction | None = None
    tempo_events: list[tuple[Fraction, str, int]] = field(default_factory=list)


@dataclass(slots=True)
class MucSong:
    path: Path
    metadata: dict[str, str]
    tracks: dict[str, MucTrack]

    @classmethod
    def load(cls, path: str | Path) -> "MucSong":
        p = Path(path)
        text = _read_text(p)
        metadata: dict[str, str] = {}
        source_by_channel = {ch: [] for ch in CHANNEL_KIND}
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("#"):
                m = re.match(r"#([A-Za-z0-9_]+)\s+(.*)", stripped)
                if m:
                    metadata[m.group(1).lower()] = m.group(2).strip()
                continue
            if not raw_line:
                continue
            ch = raw_line[0]
            if ch not in source_by_channel or (len(raw_line) > 1 and not raw_line[1].isspace()):
                continue
            body = raw_line[1:]
            if ";" in body:
                body = body.split(";", 1)[0]
            source_by_channel[ch].append(body)

        tracks: dict[str, MucTrack] = {}
        for ch, lines in source_by_channel.items():
            if lines:
                tracks[ch] = _parse_track(ch, " ".join(lines))
        return cls(p, metadata, tracks)

    def timer_b(self, default: int = 198) -> int:
        events = [event for track in self.tracks.values() for event in track.tempo_events
                  if event[1] == "timer_b" and event[0] == 0]
        return events[0][2] if events else default

    def used_patches(self, *, kinds: set[str] | None = None) -> set[int | str]:
        values: set[int | str] = set()
        for track in self.tracks.values():
            if kinds is not None and track.kind not in kinds:
                continue
            values.update(note.patch for note in track.notes if note.patch is not None)
        return values

    def to_source_midi(
        self,
        output: str | Path,
        *,
        bpm: float = 100.0,
        ppq: int = 96,
        clocks_per_second: float = 60.0,
        merge_same_pitch_ties: bool = True,
        voice_bank=None,
        max_clock: float | None = None,
    ) -> Path:
        """Write one editable MIDI track per MUCOM channel.

        This is intentionally source-oriented: native patch IDs are emitted as
        text markers, not as misleading General MIDI Program Change values.
        """
        midi = mido.MidiFile(type=1, ticks_per_beat=ppq)
        conductor = mido.MidiTrack()
        midi.tracks.append(conductor)
        conductor.append(mido.MetaMessage("track_name", name="Conductor", time=0))
        conductor.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
        conductor.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))

        ticks_per_second = ppq * bpm / 60.0
        ticks_per_clock = ticks_per_second / clocks_per_second

        for channel_index, (source_ch, track) in enumerate(sorted(self.tracks.items())):
            if not track.notes:
                continue
            midi_track = mido.MidiTrack()
            midi.tracks.append(midi_track)
            midi_track.append(mido.MetaMessage(
                "track_name", name=f"MUCOM {source_ch} ({track.kind.upper()})", time=0
            ))
            events: list[tuple[int, int, mido.Message | mido.MetaMessage]] = []
            notes = _merge_ties(track.notes) if merge_same_pitch_ties else list(track.notes)
            last_patch: int | str | None | object = object()
            for note in notes:
                if max_clock is not None and float(note.start_clock) >= max_clock:
                    continue
                start = round(float(note.start_clock) * ticks_per_clock)
                key_duration = float(note.duration_clock)
                if not note.tied_from_previous and not note.tied_to_next:
                    key_duration = max(1e-9, key_duration - max(0, note.gate))
                if max_clock is not None:
                    key_duration = min(key_duration, max_clock - float(note.start_clock))
                duration = max(1, round(key_duration * ticks_per_clock))
                patch_value = note.patch
                if voice_bank is not None and patch_value is not None and track.kind == "fm":
                    try:
                        patch_value = voice_bank.resolve(patch_value).program
                    except KeyError:
                        pass
                if patch_value != last_patch:
                    if patch_value is not None:
                        marker = f"MUCOM_PATCH={patch_value}"
                        marker = marker.encode("ascii", errors="backslashreplace").decode("ascii")
                        events.append((start, 0, mido.MetaMessage(
                            "marker", text=marker, time=0
                        )))
                    last_patch = patch_value
                velocity = _velocity(note.volume, track.kind)
                ch = 9 if track.kind in {"rhythm", "adpcm"} else (channel_index % 9)
                pitch = note.pitch
                if track.kind == "adpcm":
                    pitch = 36 if note.patch == 1 else 38 if note.patch == 2 else 42
                events.append((start, 2, mido.Message("note_on", channel=ch, note=max(0, min(127, pitch)), velocity=velocity, time=0)))
                events.append((start + duration, 1, mido.Message("note_off", channel=ch, note=max(0, min(127, pitch)), velocity=0, time=0)))
            _append_absolute_events(midi_track, events)
            midi_track.append(mido.MetaMessage("end_of_track", time=0))
        conductor.append(mido.MetaMessage("end_of_track", time=0))
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        midi.save(out)
        return out


def _velocity(volume: int, kind: str) -> int:
    if kind == "adpcm":
        return max(1, min(127, round(volume / 255 * 127)))
    return max(1, min(127, round(volume / 15 * 127)))


def _append_absolute_events(track: mido.MidiTrack, events: list[tuple[int, int, mido.Message | mido.MetaMessage]]) -> None:
    events.sort(key=lambda item: (item[0], item[1]))
    previous = 0
    for tick, _, msg in events:
        msg.time = max(0, tick - previous)
        track.append(msg)
        previous = tick


def _merge_ties(notes: list[MucNote]) -> list[MucNote]:
    out: list[MucNote] = []
    for note in notes:
        if (out and note.tied_from_previous and out[-1].tied_to_next
                and out[-1].pitch == note.pitch and out[-1].patch == note.patch
                and out[-1].start_clock + out[-1].duration_clock == note.start_clock):
            prev = out[-1]
            prev.duration_clock += note.duration_clock
            prev.tied_to_next = note.tied_to_next
        else:
            out.append(MucNote(
                note.channel, note.start_clock, note.duration_clock, note.pitch,
                note.patch, note.volume, note.pan, note.gate, note.detune,
                note.tied_from_previous, note.tied_to_next,
            ))
    return out


def _note_length(source: str, pos: int, clock: int, default_len: int,
                 prefix: int | None) -> tuple[Fraction, int]:
    if prefix is not None:
        value = Fraction(prefix)
    elif pos < len(source) and source[pos] == "%":
        number, pos2 = _read_num(source, pos + 1)
        value = Fraction(number or 0)
        pos = pos2
    elif pos < len(source) and source[pos].isdigit():
        number, pos2 = _read_num(source, pos)
        value = Fraction(clock, number) if number else Fraction(0)
        pos = pos2
    else:
        value = Fraction(clock, default_len)
    add = value / 2
    while pos < len(source) and source[pos] == ".":
        value += add
        add /= 2
        pos += 1
    return value, pos


def _parse_track(channel: str, raw_source: str) -> MucTrack:
    source = _expand_loops(raw_source)
    kind = CHANNEL_KIND[channel]
    track = MucTrack(channel=channel, kind=kind)
    clock = 128
    default_len = 4
    octave = 6
    transpose = 0
    current = Fraction(0)
    prefix: int | None = None
    volume = 255 if kind == "adpcm" else 15
    pan = 3
    patch: int | str | None = None
    gate = 0
    detune = 0
    pending_tie = False
    pos = 0

    def skip_numeric_args(p: int) -> int:
        while p < len(source) and (source[p].isdigit() or source[p] in "+-$,"):
            p += 1
        return p

    while pos < len(source):
        ch = source[pos]
        if ch.isspace() or ch == "|":
            pos += 1
            continue
        if ch == "%":
            number, next_pos = _read_num(source, pos + 1)
            prefix = number
            pos = next_pos
            continue
        if ch in _NOTE_PC or ch == "r":
            tied_from = pending_tie
            pending_tie = False
            if ch == "r":
                pitch = None
                pos += 1
            else:
                pc = _NOTE_PC[ch]
                pos += 1
                if pos < len(source) and source[pos] in "+-":
                    pc += 1 if source[pos] == "+" else -1
                    pos += 1
                if kind == "adpcm":
                    pitch = (1 - octave) * 12 + pc + transpose
                else:
                    pitch = (octave - 1) * 12 + pc + transpose
            duration, pos = _note_length(source, pos, clock, default_len, prefix)
            prefix = None
            tied_to = pos < len(source) and source[pos] == "&"
            if tied_to:
                pos += 1
            if pitch is None:
                current += duration
                pending_tie = False
            else:
                track.notes.append(MucNote(
                    channel, current, duration, pitch, patch, volume, pan,
                    gate, detune, tied_from, tied_to,
                ))
                current += duration
                pending_tie = tied_to
            continue
        if ch == "C":
            number, next_pos = _read_num(source, pos + 1)
            if number is not None:
                clock = number
            pos = next_pos
            continue
        if ch == "l":
            number, next_pos = _read_num(source, pos + 1)
            if number is not None:
                default_len = number
            pos = next_pos
            while pos < len(source) and source[pos] == ".":
                pos += 1
            continue
        if ch == "o":
            number, next_pos = _read_num(source, pos + 1)
            if number is not None:
                octave = number
            pos = next_pos
            continue
        if ch == ">":
            octave += -1 if kind == "adpcm" else 1
            pos += 1
            continue
        if ch == "<":
            octave += 1 if kind == "adpcm" else -1
            pos += 1
            continue
        if ch in {"K", "k"}:
            number, next_pos = _read_num(source, pos + 1, signed=True)
            if number is not None:
                if ch == "K":
                    transpose = number
                else:
                    transpose += number
            pos = next_pos
            continue
        if ch == "@":
            pos += 1
            if pos < len(source) and source[pos] == '"':
                end = source.find('"', pos + 1)
                if end < 0:
                    end = len(source)
                patch = source[pos + 1:end]
                pos = min(end + 1, len(source))
            else:
                number, next_pos = _read_num(source, pos)
                if number is not None:
                    patch = number
                pos = next_pos if next_pos > pos else pos + 1
            continue
        if ch == "v":
            number, next_pos = _read_num(source, pos + 1, signed=True)
            if number is not None:
                volume = number
            pos = skip_numeric_args(next_pos)
            continue
        if ch == "q":
            number, next_pos = _read_num(source, pos + 1)
            gate = number or 0
            pos = next_pos
            continue
        if ch == "p":
            number, next_pos = _read_num(source, pos + 1)
            if number is not None:
                pan = number
            pos = next_pos
            continue
        if ch == "D":
            number, next_pos = _read_num(source, pos + 1, signed=True)
            if number is not None:
                detune = number
            pos = next_pos
            continue
        if ch == "T":
            number, next_pos = _read_num(source, pos + 1)
            if number is not None:
                track.tempo_events.append((current, "bpm", number))
            pos = next_pos
            continue
        if ch == "t":
            number, next_pos = _read_num(source, pos + 1)
            if number is not None:
                track.tempo_events.append((current, "timer_b", number))
            pos = next_pos
            continue
        if ch == "L":
            track.loop_clock = current
            pos += 1
            continue
        if ch in "()":
            sign = 1 if ch == ")" else -1
            pos += 1
            number, next_pos = _read_num(source, pos)
            volume += sign * (number if number is not None else 1)
            if number is not None:
                pos = next_pos
            continue
        if ch in "&^":
            pending_tie = True
            pos += 1
            continue
        if ch == "y":
            pos += 1
            while pos < len(source) and source[pos].isalpha():
                pos += 1
            if pos < len(source) and source[pos] == ",":
                pos += 1
            pos = skip_numeric_args(pos)
            continue
        # Controls that affect synthesis/expression rather than note identity.
        if ch in "VHMESPRswm":
            pos += 1
            while pos < len(source) and source[pos].isalpha() and source[pos] not in "cdefgabr":
                pos += 1
            pos = skip_numeric_args(pos)
            continue
        if ch in {":", "!"}:
            break
        pos += 1

    track.end_clock = current
    return track

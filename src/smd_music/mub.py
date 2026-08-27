from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from pathlib import Path

import mido


NOTE_NIBBLE = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, None, None, None, None]
TRACK_NAMES = ["FM1", "FM2", "FM3", "SSG1", "SSG2", "SSG3", "Rhythm", "FM4", "FM5", "FM6", "ADPCM"]
TRACK_CHANNELS = [0, 1, 2, 10, 11, 12, 9, 3, 4, 5, 9]
TRACK_MODES = ["fm", "fm", "fm", "ssg", "ssg", "ssg", "rhythm", "fm", "fm", "fm", "adpcm"]
RHYTHM_NOTES = [36, 38, 51, 42, 45, 37]


def _le16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def timer_b_to_tempo_us(timer_b: int) -> int:
    """Convert MUCOM/YM Timer-B value to microseconds per quarter.

    MUCOM sequence timing uses a 24-tick musical quarter. The output MIDI may
    use a higher PPQ for DAW editing; event ticks are scaled separately.
    """
    timer_value = (0x100 - timer_b) << 4
    ticks_per_second = 2_000_000.0 / (6 * 12 * timer_value)
    return round(500_000 * 24 / ticks_per_second)


def _fm_velocity(volume: int, pan_boost: bool = False) -> int:
    db = (20 - volume) * -2.0 if volume < 20 else 0.0
    if pan_boost:
        db -= 3.0
    db = min(0.0, db + 6.0)
    return max(1, min(127, round((10 ** (db / 40.0)) * 127)))


def _ssg_velocity(volume: int, pan_boost: bool = False) -> int:
    if volume <= 0:
        return 1
    db = (0x0F - min(volume, 0x0F)) * -3.0
    if pan_boost:
        db -= 3.0
    db = min(0.0, db + 6.0)
    return max(1, min(127, round((10 ** (db / 40.0)) * 127)))


@dataclass(slots=True)
class TrackPointer:
    start: int
    loop: int


@dataclass(slots=True)
class MUB:
    data: bytes
    header_offset: int
    mucom88win: bool
    timer_b: int
    tracks: list[TrackPointer]
    eof: int

    @classmethod
    def load(cls, path: str | Path) -> "MUB":
        return cls.parse(Path(path).read_bytes())

    @classmethod
    def parse(cls, data: bytes) -> "MUB":
        if data[:4] == b"MUB8":
            win = True
            header = _le16(data, 4) + 5
        else:
            win = False
            header = 0
            for pos in range(min(8, len(data) - 2)):
                if _le16(data, pos + 1) == 0x002F:
                    header = pos
                    break
            if not header:
                raise ValueError("unable to locate MUCOM88 sequence header")
        timer_b = data[header]
        tracks: list[TrackPointer] = []
        pos = header + 1
        for _ in range(11):
            start = _le16(data, pos)
            loop = _le16(data, pos + 2)
            tracks.append(
                TrackPointer(
                    start=header + start if start else 0,
                    loop=header + loop if loop else 0,
                )
            )
            pos += 4
        eof = header + _le16(data, pos)
        return cls(data, header, win, timer_b, tracks, eof)

    def to_midi(self, output: str | Path, *, loops: int = 2, ppq: int = 96) -> Path:
        if ppq % 24 != 0:
            raise ValueError("output PPQ must be a multiple of MUCOM source PPQ 24")
        tick_scale = ppq // 24
        mid = mido.MidiFile(type=1, ticks_per_beat=ppq)
        tempo_track = mido.MidiTrack()
        mid.tracks.append(tempo_track)
        tempo_events: list[tuple[int, int]] = [(0, timer_b_to_tempo_us(self.timer_b))]

        for index, pointer in enumerate(self.tracks):
            track, changes = self._decode_track(index, pointer, loops, tick_scale)
            mid.tracks.append(track)
            tempo_events.extend(changes)

        # Type-1 MIDI convention: global tempo map lives in track 0.
        tempo_track.append(mido.MetaMessage("track_name", name="Tempo", time=0))
        dedup: dict[int, int] = {}
        for tick, tempo in tempo_events:
            dedup[tick] = tempo
        last = 0
        for tick, tempo in sorted(dedup.items()):
            tempo_track.append(mido.MetaMessage("set_tempo", tempo=tempo, time=tick - last))
            last = tick

        out = Path(output)
        mid.save(out)
        return out

    def _decode_track(self, index: int, pointer: TrackPointer, loops: int, tick_scale: int) -> tuple[mido.MidiTrack, list[tuple[int, int]]]:
        track = mido.MidiTrack()
        name = TRACK_NAMES[index]
        channel = TRACK_CHANNELS[index]
        mode = TRACK_MODES[index]
        track.append(mido.MetaMessage("track_name", name=name, time=0))
        if not pointer.start:
            return track, []

        events: list[tuple[int, int, mido.Message | mido.MetaMessage]] = []
        tempo_changes: list[tuple[int, int]] = []
        pos = pointer.start
        tick = 0
        last_note: int | None = None
        hold = False
        note_stop = 0
        volume = 0
        velocity = 100
        pan_boost = False
        rhythm_mask = 0
        rhythm_on: set[int] = set()
        master_loops = 0
        loop_stack: list[dict[str, int]] = []
        steps = 0

        def ev(at: int, priority: int, message):
            events.append((at, priority, message))

        def note_off(at: int) -> None:
            nonlocal last_note
            if last_note is not None:
                ev(at, 1, mido.Message("note_off", channel=channel, note=last_note, velocity=0, time=0))
                last_note = None

        while pos < len(self.data) and steps < 2_000_000:
            steps += 1
            if pointer.loop and pos == pointer.loop:
                master_loops = max(master_loops, 1)
            cmd = self.data[pos]
            pos += 1

            if cmd == 0x00:
                if pointer.loop and master_loops < loops:
                    pos = pointer.loop
                    master_loops += 1
                    continue
                break

            if cmd < 0x80:
                if pos >= len(self.data):
                    break
                encoded = self.data[pos]; pos += 1
                semitone = NOTE_NIBBLE[encoded & 0x0F]
                note = None if semitone is None else semitone + ((encoded >> 4) * 12) + 12
                if mode in ("ssg", "adpcm", "rhythm") and note is not None:
                    note += 12

                if mode == "rhythm":
                    if not hold:
                        for n in list(rhythm_on):
                            ev(tick, 1, mido.Message("note_off", channel=9, note=n, velocity=0, time=0))
                        rhythm_on.clear()
                        for bit, drum_note in enumerate(RHYTHM_NOTES):
                            if rhythm_mask & (1 << bit):
                                rhythm_on.add(drum_note)
                                ev(tick, 2, mido.Message("note_on", channel=9, note=drum_note, velocity=velocity, time=0))
                elif note is not None and (last_note != note or not hold):
                    if not hold:
                        note_off(tick)
                    ev(tick, 2, mido.Message("note_on", channel=channel, note=note, velocity=velocity, time=0))
                    last_note = note

                hold = False
                duration = cmd * tick_scale
                if note_stop and duration > note_stop and (pos >= len(self.data) or self.data[pos] != 0xFD):
                    stop_at = tick + duration - note_stop
                    if mode == "rhythm":
                        for n in list(rhythm_on):
                            ev(stop_at, 1, mido.Message("note_off", channel=9, note=n, velocity=0, time=0))
                        rhythm_on.clear()
                    else:
                        note_off(stop_at)
                tick += duration
                continue

            if cmd < 0xF0:
                if not hold:
                    if mode == "rhythm":
                        for n in list(rhythm_on):
                            ev(tick, 1, mido.Message("note_off", channel=9, note=n, velocity=0, time=0))
                        rhythm_on.clear()
                    else:
                        note_off(tick)
                hold = False
                tick += (cmd & 0x7F) * tick_scale
                continue

            if cmd == 0xF0:
                value = self.data[pos]; pos += 1
                if mode == "rhythm" and self.mucom88win:
                    rhythm_mask = value
                elif mode != "rhythm":
                    # MUCOM instrument numbers are native patch IDs, not GM programs.
                    ev(tick, 0, mido.MetaMessage("marker", text=f"MUCOM_PATCH={value & 0x7F}", time=0))
            elif cmd == 0xF1:
                volume = self.data[pos]; pos += 1
                if mode == "rhythm":
                    pos += 6
                if mode == "fm":
                    velocity = _fm_velocity(volume, pan_boost)
                elif mode == "ssg":
                    velocity = _ssg_velocity(volume, pan_boost)
                else:
                    velocity = max(1, min(127, volume // 2 if volume else 1))
            elif cmd == 0xF2:
                raw = _le16(self.data, pos)
                bend = 0x2000 - (raw << 5)
                bend = max(0, min(0x3FFF, bend))
                ev(tick, 0, mido.Message("pitchwheel", channel=channel, pitch=bend - 8192, time=0))
                pos += 3
            elif cmd == 0xF3:
                value = self.data[pos]; pos += 1
                if mode == "rhythm":
                    rhythm_mask = value
                else:
                    note_stop = value * tick_scale
            elif cmd == 0xF4:
                enabled = self.data[pos]
                if enabled == 0:
                    pos += 6
                else:
                    pos += 1
            elif cmd == 0xF5:
                rel = _le16(self.data, pos)
                target = pos + rel
                count = self.data[target] if 0 <= target < len(self.data) else 0
                loop_stack.append({"count": count})
                pos += 2
            elif cmd == 0xF6:
                repeat = self.data[pos + 1]
                if not loop_stack:
                    loop_stack.append({"count": repeat})
                elif loop_stack[-1]["count"] == 0:
                    loop_stack[-1]["count"] = repeat
                pos += 2
                rel = _le16(self.data, pos)
                loop_stack[-1]["count"] -= 1
                if loop_stack[-1]["count"] > 0:
                    pos -= rel
                else:
                    loop_stack.pop()
                    pos += 2
            elif cmd == 0xF7:
                pos += 1
            elif cmd in (0xF8, 0xF9):
                if (self.mucom88win and cmd == 0xF8) or ((not self.mucom88win) and cmd == 0xF9):
                    value = self.data[pos]; pos += 1
                    p = value & 3
                    pan = 127 if p == 1 else 0 if p == 2 else 64
                    pan_boost = pan != 64
                    ev(tick, 0, mido.Message("control_change", channel=channel, control=10, value=pan, time=0))
                else:
                    pos += 1
            elif cmd == 0xFA:
                if mode == "ssg":
                    pos += 6
                else:
                    reg = self.data[pos]
                    value = self.data[pos + 1]
                    pos += 2
                    if reg == 0x26:
                        tempo_changes.append((tick, timer_b_to_tempo_us(value)))
            elif cmd == 0xFB:
                delta = self.data[pos]; pos += 1
                volume = (volume + delta) & 0xFF
                if mode == "fm":
                    velocity = _fm_velocity(volume, pan_boost)
                elif mode == "ssg":
                    velocity = _ssg_velocity(volume, pan_boost)
            elif cmd == 0xFC:
                pos += 3
            elif cmd == 0xFD:
                hold = True
            elif cmd == 0xFE:
                rel = _le16(self.data, pos)
                target = pos + rel
                target_count = self.data[target] if target < len(self.data) else 0
                if loop_stack and loop_stack[-1]["count"] == 1:
                    loop_stack.pop()
                    pos += rel + 4
                else:
                    pos += 2
                _ = target_count
            elif cmd == 0xFF:
                if self.mucom88win:
                    extra = self.data[pos]; pos += 1
                    if 0xF0 <= extra <= 0xF5:
                        pos += 1
            else:
                raise ValueError(f"unknown MUCOM command 0x{cmd:02X} at 0x{pos-1:X}")

        if mode == "rhythm":
            for n in rhythm_on:
                ev(tick, 1, mido.Message("note_off", channel=9, note=n, velocity=0, time=0))
        else:
            note_off(tick)

        events.sort(key=lambda item: (item[0], item[1]))
        last_tick = 0
        for at, _, message in events:
            message.time = max(0, at - last_tick)
            track.append(message)
            last_tick = at
        return track, tempo_changes

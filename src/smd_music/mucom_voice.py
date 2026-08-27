from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .ir import FmOperator, FmPatch
from .ym2612 import patch_to_rym2612


VOICE_SIZE = 32


def _op_offset(logical_zero_based: int) -> int:
    # MUCOM/OPN memory order is 1,3,2,4.
    return ((logical_zero_based & 1) << 1) | ((logical_zero_based & 2) >> 1)


@dataclass(frozen=True, slots=True)
class MucomVoice:
    program: int
    data: bytes

    def __post_init__(self) -> None:
        if len(self.data) != VOICE_SIZE:
            raise ValueError(f"MUCOM voice must be {VOICE_SIZE} bytes")

    @property
    def raw_name(self) -> bytes:
        return self.data[26:32].split(b"\0", 1)[0].rstrip()

    @property
    def name(self) -> str:
        # ASCII names are common and safe. Original PC-88 kana uses a custom
        # glyph table; keep non-ASCII names deterministic rather than guessing.
        raw = self.raw_name
        if raw and all(0x20 <= b < 0x7F for b in raw):
            return raw.decode("ascii")
        return ""

    @property
    def display_name(self) -> str:
        suffix = f"-{self.name}" if self.name else ""
        return f"MUCOM88-{self.program:03d}{suffix}"

    def to_patch(self) -> FmPatch:
        ops: list[FmOperator] = []
        for logical_zero in range(4):
            off = _op_offset(logical_zero)
            r30 = self.data[1 + off]
            r40 = self.data[5 + off]
            r50 = self.data[9 + off]
            r60 = self.data[13 + off]
            r70 = self.data[17 + off]
            r80 = self.data[21 + off]
            ops.append(
                FmOperator(
                    logical_operator=logical_zero + 1,
                    detune=(r30 >> 4) & 7,
                    multiple=r30 & 15,
                    total_level=r40 & 127,
                    rate_scale=(r50 >> 6) & 3,
                    attack_rate=r50 & 31,
                    am_enable=(r60 >> 7) & 1,
                    decay_rate=r60 & 31,
                    sustain_rate=r70 & 31,
                    sustain_level=(r80 >> 4) & 15,
                    release_rate=r80 & 15,
                    ssg_eg=0,
                )
            )
        b0 = self.data[25]
        return FmPatch(
            id=f"mucom88-{self.program:03d}",
            algorithm=b0 & 7,
            feedback=(b0 >> 3) & 7,
            ams=0,
            fms=0,
            pan_left=True,
            pan_right=True,
            operators=ops,
            use_count=0,
        )

    def to_rym2612(self, *, carrier_velocity: bool = False) -> bytes:
        return patch_to_rym2612(
            self.to_patch(),
            name=self.display_name,
            category="Video Games",
            carrier_velocity=carrier_velocity,
        )


@dataclass(slots=True)
class MucomVoiceBank:
    voices: list[MucomVoice]

    @classmethod
    def load(cls, path: str | Path) -> "MucomVoiceBank":
        data = Path(path).read_bytes()
        if len(data) % VOICE_SIZE:
            raise ValueError(
                f"MUCOM voice bank size {len(data)} is not divisible by {VOICE_SIZE}"
            )
        return cls([
            MucomVoice(i // VOICE_SIZE, data[i:i + VOICE_SIZE])
            for i in range(0, len(data), VOICE_SIZE)
        ])

    def export_rym2612(
        self,
        out_dir: str | Path,
        *,
        programs: set[int] | None = None,
        carrier_velocity: bool = False,
    ) -> list[Path]:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for voice in self.voices:
            if programs is not None and voice.program not in programs:
                continue
            path = out / f"{voice.display_name}.rym2612"
            path.write_bytes(voice.to_rym2612(carrier_velocity=carrier_velocity))
            written.append(path)
        return written

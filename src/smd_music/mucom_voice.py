from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import unicodedata

from .ir import FmOperator, FmPatch
from .ym2612 import patch_to_rym2612


VOICE_SIZE = 32

# PC-8801/MUCOM88 six-character voice-name glyph table. Bytes below 0x80
# are ASCII; bytes 0x80.. are indexes into this table.
_PC88_VOICE_CHARS = (
    "▁▂▃▄▅▆▇█▏▎▍▌▋▊▉┼"
    "┴┬┤├▔─│▕┌┐└┘╭╮╰╯"
    " 。「」、・ヲァィゥェォャュョッ"
    "ーアイウエオカキクケコサシスセソ"
    "タチツテトナニヌネノハヒフヘホマ"
    "ミムメモヤユヨラリルレロワン゛゜"
    "═╞╪╡◢◣◥◤♠♥♦♣●○╱╲"
    "╳円年月日時分秒        "
)


def _decode_voice_name(raw: bytes) -> str:
    chars: list[str] = []
    for byte in raw:
        if byte == 0:
            break
        if byte < 0x80:
            chars.append(chr(byte))
        else:
            index = byte - 0x80
            chars.append(_PC88_VOICE_CHARS[index] if index < len(_PC88_VOICE_CHARS) else "�")
    text = "".join(chars).rstrip().replace("゛", "\u3099").replace("゜", "\u309A")
    return unicodedata.normalize("NFKC", unicodedata.normalize("NFC", text)).strip()


def normalize_voice_name(name: str) -> str:
    return unicodedata.normalize("NFKC", name).strip().casefold()


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
        return _decode_voice_name(self.raw_name)

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

    def by_program(self, program: int) -> MucomVoice:
        if not 0 <= program < len(self.voices):
            raise KeyError(program)
        return self.voices[program]

    def find_by_name(self, name: str) -> MucomVoice | None:
        target = normalize_voice_name(name)
        for voice in self.voices:
            if normalize_voice_name(voice.name) == target:
                return voice
        return None

    def resolve(self, program_or_name: int | str) -> MucomVoice:
        if isinstance(program_or_name, int):
            return self.by_program(program_or_name)
        voice = self.find_by_name(program_or_name)
        if voice is None:
            raise KeyError(program_or_name)
        return voice

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

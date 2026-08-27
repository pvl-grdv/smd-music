from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .kosinski import decompress as kosinski_decompress


@dataclass(frozen=True, slots=True)
class RomProfile:
    id: str
    md5: str
    title: str
    size: int
    sound_driver_kosinski_offset: int | None = None
    sound_driver_copy_length: int | None = None
    sound_driver_decompressed_length: int | None = None


SOR1_WORLD_REV00 = RomProfile(
    id="sor1-world-rev00",
    md5="569cfec15813294a8f0cf88cccc8c151",
    title="Streets of Rage / Bare Knuckle (JUE, rev 00)",
    size=0x80000,
    sound_driver_kosinski_offset=0x795A2,
    # The 68000 loader sets d2=0x1EC6 and uses DBF, therefore copies 0x1EC7 bytes.
    sound_driver_copy_length=0x1EC7,
    # The Kosinski stream itself expands to 0x1F00 bytes.
    sound_driver_decompressed_length=0x1F00,
)

PROFILES_BY_MD5 = {SOR1_WORLD_REV00.md5: SOR1_WORLD_REV00}


@dataclass(slots=True)
class GenesisRom:
    data: bytes
    path: Path | None = None

    @classmethod
    def load(cls, path: str | Path) -> "GenesisRom":
        p = Path(path)
        return cls(p.read_bytes(), p)

    @property
    def md5(self) -> str:
        return hashlib.md5(self.data).hexdigest()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def profile(self) -> RomProfile | None:
        return PROFILES_BY_MD5.get(self.md5)

    def text_field(self, start: int, length: int) -> str:
        return self.data[start:start + length].decode("ascii", errors="replace").rstrip(" \0")

    def header(self) -> dict[str, object]:
        if len(self.data) < 0x200:
            raise ValueError("file is too small to be a Mega Drive ROM")
        return {
            "console": self.text_field(0x100, 16),
            "copyright": self.text_field(0x110, 16),
            "domestic_title": self.text_field(0x120, 48),
            "international_title": self.text_field(0x150, 48),
            "serial": self.text_field(0x180, 14),
            "region": self.text_field(0x1F0, 16),
            "size": len(self.data),
            "md5": self.md5,
            "sha256": self.sha256,
            "profile": self.profile.id if self.profile else None,
        }

    def extract_sor1_sound_driver(self) -> dict[str, bytes | int | str]:
        profile = self.profile
        if profile != SOR1_WORLD_REV00:
            raise ValueError(
                "unsupported ROM for the SoR1 extractor; expected MD5 "
                f"{SOR1_WORLD_REV00.md5}"
            )
        assert profile.sound_driver_kosinski_offset is not None
        full, consumed = kosinski_decompress(self.data, profile.sound_driver_kosinski_offset)
        if len(full) != profile.sound_driver_decompressed_length:
            raise ValueError(
                f"unexpected decompressed driver size 0x{len(full):X}; "
                f"expected 0x{profile.sound_driver_decompressed_length:X}"
            )
        copy_len = profile.sound_driver_copy_length or len(full)
        return {
            "profile": profile.id,
            "compressed_offset": profile.sound_driver_kosinski_offset,
            "compressed_bytes_consumed": consumed,
            "decompressed_full": full,
            "z80_loaded_image": full[:copy_len],
            "z80_loaded_length": copy_len,
        }

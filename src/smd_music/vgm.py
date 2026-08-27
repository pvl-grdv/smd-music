from __future__ import annotations

import gzip
import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True, slots=True)
class VgmHeader:
    version: int
    data_offset: int
    total_samples: int
    loop_offset: int
    loop_samples: int
    sn76489_clock: int
    ym2612_clock: int


@dataclass(frozen=True, slots=True)
class VgmCommand:
    sample: int
    kind: str
    values: tuple[int, ...] = ()
    data: bytes | None = None


class VgmFile:
    def __init__(self, raw: bytes, source_name: str = ""):
        if raw[:4] != b"Vgm ":
            raise ValueError("not a VGM file")
        self.raw = raw
        self.source_name = source_name
        self.sha256 = hashlib.sha256(raw).hexdigest()
        version = struct.unpack_from("<I", raw, 0x08)[0]
        rel_data = struct.unpack_from("<I", raw, 0x34)[0] if version >= 0x150 else 0
        data_offset = 0x34 + rel_data if rel_data else 0x40
        self.header = VgmHeader(
            version=version,
            data_offset=data_offset,
            total_samples=struct.unpack_from("<I", raw, 0x18)[0],
            loop_offset=struct.unpack_from("<I", raw, 0x1C)[0],
            loop_samples=struct.unpack_from("<I", raw, 0x20)[0],
            sn76489_clock=struct.unpack_from("<I", raw, 0x0C)[0] & 0x3FFFFFFF,
            ym2612_clock=struct.unpack_from("<I", raw, 0x2C)[0] & 0x3FFFFFFF,
        )

    @classmethod
    def load(cls, path: str | Path) -> "VgmFile":
        p = Path(path)
        payload = p.read_bytes()
        if payload[:2] == b"\x1f\x8b" or p.suffix.lower() == ".vgz":
            payload = gzip.decompress(payload)
        return cls(payload, p.name)

    def commands(self) -> Iterator[VgmCommand]:
        raw = self.raw
        pos = self.header.data_offset
        sample = 0
        while pos < len(raw):
            cmd = raw[pos]
            pos += 1
            if cmd == 0x4F:
                value = raw[pos]; pos += 1
                yield VgmCommand(sample, "gg_stereo", (value,))
            elif cmd == 0x50:
                value = raw[pos]; pos += 1
                yield VgmCommand(sample, "sn76489", (value,))
            elif cmd in (0x52, 0x53):
                reg, value = raw[pos], raw[pos + 1]; pos += 2
                yield VgmCommand(sample, "ym2612", (0 if cmd == 0x52 else 1, reg, value))
            elif cmd == 0x61:
                wait = struct.unpack_from("<H", raw, pos)[0]; pos += 2
                sample += wait
                yield VgmCommand(sample, "wait", (wait,))
            elif cmd == 0x62:
                sample += 735
                yield VgmCommand(sample, "wait", (735,))
            elif cmd == 0x63:
                sample += 882
                yield VgmCommand(sample, "wait", (882,))
            elif cmd == 0x66:
                yield VgmCommand(sample, "end")
                break
            elif cmd == 0x67:
                if raw[pos] != 0x66:
                    raise ValueError("malformed VGM data block")
                pos += 1
                block_type = raw[pos]; pos += 1
                size = struct.unpack_from("<I", raw, pos)[0] & 0x7FFFFFFF; pos += 4
                block = bytes(raw[pos:pos + size]); pos += size
                yield VgmCommand(sample, "data_block", (block_type,), block)
            elif 0x70 <= cmd <= 0x7F:
                wait = (cmd & 0x0F) + 1
                sample += wait
                yield VgmCommand(sample, "wait", (wait,))
            elif 0x80 <= cmd <= 0x8F:
                wait = cmd & 0x0F
                yield VgmCommand(sample, "dac_stream_byte", (wait,))
                sample += wait
                if wait:
                    yield VgmCommand(sample, "wait", (wait,))
            elif cmd == 0xE0:
                offset = struct.unpack_from("<I", raw, pos)[0]; pos += 4
                yield VgmCommand(sample, "pcm_seek", (offset,))
            elif 0x51 <= cmd <= 0x5F:
                reg, value = raw[pos], raw[pos + 1]; pos += 2
                yield VgmCommand(sample, "other_chip_write", (cmd, reg, value))
            else:
                raise ValueError(f"unsupported VGM command 0x{cmd:02X} at 0x{pos - 1:X}")

    def summary(self) -> dict[str, object]:
        counts: dict[str, int] = {}
        blocks: list[dict[str, int]] = []
        end_sample = 0
        for command in self.commands():
            counts[command.kind] = counts.get(command.kind, 0) + 1
            end_sample = max(end_sample, command.sample)
            if command.kind == "data_block":
                blocks.append({"type": command.values[0], "size": len(command.data or b"")})
        return {
            "source": self.source_name,
            "sha256": self.sha256,
            "version": f"0x{self.header.version:08X}",
            "sn76489_clock": self.header.sn76489_clock,
            "ym2612_clock": self.header.ym2612_clock,
            "header_total_samples": self.header.total_samples,
            "parsed_end_sample": end_sample,
            "duration_seconds": end_sample / 44100.0,
            "commands": counts,
            "data_blocks": blocks,
        }

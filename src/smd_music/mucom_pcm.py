from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
import wave


HEADER_SIZE = 0x400
RECORD_SIZE = 0x20
SAMPLE_RATE = 16000
_STEP_TABLE = (57, 57, 57, 57, 77, 102, 128, 153,
               57, 57, 57, 57, 77, 102, 128, 153)


@dataclass(frozen=True, slots=True)
class MucomPcmSample:
    number: int  # MML @ number, 1-based
    name: str
    adpcm: bytes
    data_offset: int

    def decode_pcm16(self) -> list[int]:
        """Decode MUCOM/OPNA Yamaha ADPCM-B (DELTA) to signed PCM16."""
        xn = 0
        step = 127
        pcm: list[int] = []
        for packed in self.adpcm:
            for code in ((packed >> 4) & 0x0F, packed & 0x0F):
                delta = ((code & 7) * 2 + 1) * step >> 3
                xn = xn - delta if code & 8 else xn + delta
                xn = max(-32768, min(32767, xn))
                pcm.append(xn)
                step = (_STEP_TABLE[code] * step) // 64
                step = max(127, min(24576, step))
        return pcm

    def write_wav(self, path: str | Path, *, sample_rate: int = SAMPLE_RATE) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        pcm = self.decode_pcm16()
        payload = struct.pack('<' + 'h' * len(pcm), *pcm)
        with wave.open(str(output), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(payload)
        return output


@dataclass(slots=True)
class MucomPcmBank:
    samples: list[MucomPcmSample]

    @classmethod
    def load(cls, path: str | Path) -> "MucomPcmBank":
        data = Path(path).read_bytes()
        if len(data) < HEADER_SIZE:
            raise ValueError('MUCOM PCM bank is shorter than its 0x400-byte header')
        samples: list[MucomPcmSample] = []
        for rec_off in range(0, HEADER_SIZE, RECORD_SIZE):
            rec = data[rec_off:rec_off + RECORD_SIZE]
            raw_name = rec[:16].split(b'\0', 1)[0].rstrip(b' ')
            if not raw_name:
                continue
            name = raw_name.decode('cp932', errors='replace').strip()
            # MUCOM88 PCM bank records store the packed-data offset in units
            # of four bytes at 0x1c and the ADPCM byte length at 0x1e.
            # The encoded stream itself follows the 0x400-byte directory.
            offset_units = int.from_bytes(rec[0x1C:0x1E], 'little')
            length = int.from_bytes(rec[0x1E:0x20], 'little')
            data_offset = HEADER_SIZE + offset_units * 4
            end = data_offset + length
            if length <= 0 or end > len(data):
                raise ValueError(
                    f'invalid PCM record {rec_off // RECORD_SIZE}: '
                    f'offset={data_offset:#x}, length={length:#x}'
                )
            samples.append(MucomPcmSample(
                number=rec_off // RECORD_SIZE + 1,
                name=name,
                adpcm=data[data_offset:end],
                data_offset=data_offset,
            ))
        return cls(samples)

    def export_wav(self, out_dir: str | Path) -> list[Path]:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        result: list[Path] = []
        for sample in self.samples:
            safe = ''.join(ch if ch.isalnum() or ch in '-_ ' else '_' for ch in sample.name).strip()
            result.append(sample.write_wav(out / f'{sample.number:02d}-{safe}.wav'))
        return result

from __future__ import annotations

import hashlib
import json
import wave
from dataclasses import asdict
from pathlib import Path

from .vgm import VgmFile
from .ym2612 import Ym2612State, patch_to_dmp, patch_to_tfi


def extract_vgm_assets(vgm_path: str | Path, out_dir: str | Path) -> dict[str, object]:
    """Create an editable-assets pack from a Genesis VGM/VGZ.

    Current assets:
    - deduplicated YM2612 patch snapshots (JSON), captured at key-on;
    - .DMP and .TFI FM-patch files;
    - raw VGM PCM data-bank bytes;
    - an exact 44.1 kHz unsigned-8-bit DAC register timeline as WAV;
    - a provenance/manifest JSON.

    The DAC WAV is the digital value stream sent to YM2612 DAC. It is not an
    analog-model render of a Model 1/2 Mega Drive output stage.
    """

    source = Path(vgm_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    vgm = VgmFile.load(source)
    ym = Ym2612State()
    pcm_bank = bytearray()
    pcm_ptr = 0
    dac_value = 0x80
    dac_audio = bytearray()
    cursor_sample = 0

    def advance_to(sample: int) -> None:
        nonlocal cursor_sample
        if sample > cursor_sample:
            dac_audio.extend(bytes([dac_value]) * (sample - cursor_sample))
            cursor_sample = sample

    for command in vgm.commands():
        advance_to(command.sample)
        if command.kind == "ym2612":
            port, reg, value = command.values
            ym.write(port, reg, value, command.sample)
            if port == 0 and reg == 0x2A:
                dac_value = value
        elif command.kind == "data_block" and command.values[0] == 0x00:
            pcm_bank.extend(command.data or b"")
        elif command.kind == "pcm_seek":
            pcm_ptr = command.values[0]
        elif command.kind == "dac_stream_byte":
            if pcm_ptr < len(pcm_bank):
                dac_value = pcm_bank[pcm_ptr]
                pcm_ptr += 1

    if pcm_bank:
        (out / "pcm_bank_00.bin").write_bytes(pcm_bank)
    if dac_audio:
        with wave.open(str(out / "dac_timeline_u8.wav"), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(1)
            wav.setframerate(44100)
            wav.writeframes(bytes(dac_audio))

    patch_dir = out / "fm_patches"
    patch_dir.mkdir(exist_ok=True)
    patch_objects = list(ym.patches.values())
    for index, patch in enumerate(patch_objects, start=1):
        stem = f"{index:02d}_{patch.id}"
        (patch_dir / f"{stem}.tfi").write_bytes(patch_to_tfi(patch))
        (patch_dir / f"{stem}.dmp").write_bytes(patch_to_dmp(patch))

    patches = [asdict(p) for p in patch_objects]
    (out / "ym2612_patches.json").write_text(
        json.dumps(patches, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    source_bytes = source.read_bytes()
    manifest: dict[str, object] = {
        "format": "smd-music-daw-pack-v1",
        "source": {
            "name": source.name,
            "sha256_file": hashlib.sha256(source_bytes).hexdigest(),
            "sha256_uncompressed_vgm": vgm.sha256,
        },
        "vgm": vgm.summary(),
        "assets": {
            "ym2612_patch_count": len(patches),
            "ym2612_patch_formats": ["json", "tfi", "dmp"],
            "pcm_bank_bytes": len(pcm_bank),
            "dac_timeline_samples": len(dac_audio),
        },
        "notes": [
            "MIDI cannot preserve native YM2612 operator parameters; keep ym2612_patches.json and fm_patches beside the MIDI export.",
            "TFI is compact but loses AM/FMS/AMS/pan; DMP preserves more YM2612 modulation data but still not stereo pan.",
            "dac_timeline_u8.wav is the digital DAC register stream, not an analog console-emulation render.",
        ],
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest

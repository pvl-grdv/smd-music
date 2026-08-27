from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from .daw_pack import extract_vgm_assets
from .genesis_rom import GenesisRom
from .mub import MUB
from .mucom import MucProject, compile_muc
from .vgm import VgmFile


def _json(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="smd-music")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("rom-info", help="inspect a Mega Drive/Genesis ROM header")
    p.add_argument("rom")

    p = sub.add_parser("sor1-driver", help="extract the SoR1 Z80 sound-driver image")
    p.add_argument("rom")
    p.add_argument("--output", "-o", required=True)
    p.add_argument("--full", action="store_true", help="write the full 0x1F00 decompressed block")

    p = sub.add_parser("vgm-info", help="inspect a VGM/VGZ")
    p.add_argument("vgm")

    p = sub.add_parser("vgm-assets", help="extract YM2612 patches + PCM/DAC assets")
    p.add_argument("vgm")
    p.add_argument("--out", "-o", required=True)

    p = sub.add_parser("muc-info", help="show MUCOM88 source metadata and companion files")
    p.add_argument("muc")

    p = sub.add_parser("muc-compile", help="compile MUC to MUB using installed Open MUCOM88")
    p.add_argument("muc")
    p.add_argument("--output", "-o", required=True)
    p.add_argument("--mucom88")

    p = sub.add_parser("muc-midi", help="compile MUC with Open MUCOM88 and convert to editable MIDI")
    p.add_argument("muc")
    p.add_argument("--output", "-o", required=True)
    p.add_argument("--loops", type=int, default=2)
    p.add_argument("--mucom88")
    p.add_argument("--keep-mub")

    p = sub.add_parser("mub-midi", help="convert compiled MUCOM88 sequence data to editable MIDI")
    p.add_argument("mub")
    p.add_argument("--output", "-o", required=True)
    p.add_argument("--loops", type=int, default=2)

    args = parser.parse_args(argv)

    if args.command == "rom-info":
        _json(GenesisRom.load(args.rom).header())
    elif args.command == "sor1-driver":
        rom = GenesisRom.load(args.rom)
        result = rom.extract_sor1_sound_driver()
        payload = result["decompressed_full"] if args.full else result["z80_loaded_image"]
        Path(args.output).write_bytes(payload)  # type: ignore[arg-type]
        _json({k: v for k, v in result.items() if not isinstance(v, bytes)})
    elif args.command == "vgm-info":
        _json(VgmFile.load(args.vgm).summary())
    elif args.command == "vgm-assets":
        _json(extract_vgm_assets(args.vgm, args.out))
    elif args.command == "muc-info":
        project = MucProject.load(args.muc)
        _json({
            "path": str(project.path),
            "metadata": project.metadata,
            "voice": str(project.companion("voice")) if project.companion("voice") else None,
            "pcm": str(project.companion("pcm")) if project.companion("pcm") else None,
        })
    elif args.command == "muc-compile":
        print(compile_muc(args.muc, args.output, executable=args.mucom88))
    elif args.command == "muc-midi":
        if args.keep_mub:
            mub_path = Path(args.keep_mub)
            compile_muc(args.muc, mub_path, executable=args.mucom88)
            print(MUB.load(mub_path).to_midi(args.output, loops=args.loops))
        else:
            with tempfile.TemporaryDirectory(prefix="smd-music-") as tmp:
                mub_path = Path(tmp) / "source.mub"
                compile_muc(args.muc, mub_path, executable=args.mucom88)
                print(MUB.load(mub_path).to_midi(args.output, loops=args.loops))
    elif args.command == "mub-midi":
        print(MUB.load(args.mub).to_midi(args.output, loops=args.loops))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

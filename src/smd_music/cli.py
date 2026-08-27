from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from .daw_pack import extract_vgm_assets
from .genesis_rom import GenesisRom
from .hybrid import build_hybrid_pack, match_muc_to_vgm
from .mub import MUB
from .mucom import MucProject, compile_muc
from .muc_sequence import MucSong
from .mucom_daw import build_muc_daw_pack
from .mucom_pcm import MucomPcmBank
from .mucom_voice import MucomVoiceBank
from .vgm import VgmFile
from .web_player import build_web_player


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

    p = sub.add_parser("hybrid-map", help="match published MUCOM voices to final YM2612 voices in VGM/VGZ")
    p.add_argument("muc")
    p.add_argument("vgm")
    p.add_argument("--output", "-o")

    p = sub.add_parser("hybrid-pack", help="build MUC source assets + final VGM assets + cross-map")
    p.add_argument("muc")
    p.add_argument("vgm")
    p.add_argument("--out", "-o", required=True)
    p.add_argument("--bpm", type=float, default=100.0)

    p = sub.add_parser("muc-info", help="show MUCOM88 source metadata and companion files")
    p.add_argument("muc")

    p = sub.add_parser("muc-source-midi", help="convert MUC directly to source-oriented MIDI without a compiler")
    p.add_argument("muc")
    p.add_argument("--output", "-o", required=True)
    p.add_argument("--bpm", type=float, default=100.0)
    p.add_argument("--max-clock", type=float)

    p = sub.add_parser("muc-daw-pack", help="build plugin MIDI + RYM2612 presets + PCM WAVs from MUC companions")
    p.add_argument("muc")
    p.add_argument("--out", "-o", required=True)
    p.add_argument("--bpm", type=float, default=100.0)
    p.add_argument("--max-clock", type=float)

    p = sub.add_parser("pcm-wav", help="decode a MUCOM88 PCM bank to WAV files")
    p.add_argument("pcm")
    p.add_argument("--out", "-o", required=True)

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

    p = sub.add_parser("voice-rym2612", help="convert a MUCOM88 voice.dat bank to native RYM2612 presets")
    p.add_argument("voice")
    p.add_argument("--out", "-o", required=True)
    p.add_argument("--program", type=int, action="append", help="export only this program number; repeatable")
    p.add_argument("--playable-velocity", action="store_true", help="add carrier velocity sensitivity like mucom88torym2612")

    p = sub.add_parser("web-player", help="build an offline interactive WebAudio timeline/player")
    p.add_argument("midi", help="editable arrangement MIDI")
    p.add_argument("--voice", required=True, help="MUCOM88 voice.dat")
    p.add_argument("--pcm", required=True, help="MUCOM88 PCM .bin")
    p.add_argument("--out", "-o", required=True)
    p.add_argument("--title", default="Sega Mega Drive reconstruction")
    p.add_argument("--vgm", help="optional reference VGM/VGZ copied into the bundle")
    p.add_argument("--fm", action="append", default=[], metavar="TRACK=PROGRAM", help="map MIDI track name to MUCOM FM program")
    p.add_argument("--psg", action="append", default=[], metavar="TRACK", help="mark a MIDI track as PSG")
    p.add_argument("--drums", action="append", default=[], metavar="TRACK", help="mark a MIDI track as percussion")

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
    elif args.command == "hybrid-map":
        result = match_muc_to_vgm(args.muc, args.vgm)
        if args.output:
            Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        _json(result)
    elif args.command == "hybrid-pack":
        _json(build_hybrid_pack(args.muc, args.vgm, args.out, bpm=args.bpm))
    elif args.command == "muc-info":
        project = MucProject.load(args.muc)
        _json({
            "path": str(project.path),
            "metadata": project.metadata,
            "voice": str(project.companion("voice")) if project.companion("voice") else None,
            "pcm": str(project.companion("pcm")) if project.companion("pcm") else None,
        })
    elif args.command == "muc-source-midi":
        song = MucSong.load(args.muc)
        voice = song.metadata.get("voice")
        bank = MucomVoiceBank.load(Path(args.muc).parent / voice) if voice else None
        print(song.to_source_midi(args.output, bpm=args.bpm, voice_bank=bank, max_clock=args.max_clock))
    elif args.command == "muc-daw-pack":
        _json(build_muc_daw_pack(args.muc, args.out, bpm=args.bpm, max_clock=args.max_clock))
    elif args.command == "pcm-wav":
        files = MucomPcmBank.load(args.pcm).export_wav(args.out)
        _json({"exported": len(files), "files": [str(p) for p in files]})
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
    elif args.command == "voice-rym2612":
        bank = MucomVoiceBank.load(args.voice)
        programs = set(args.program) if args.program else None
        written = bank.export_rym2612(
            args.out, programs=programs, carrier_velocity=args.playable_velocity
        )
        _json({"voice_count": len(bank.voices), "exported": len(written), "files": [str(p) for p in written]})
    elif args.command == "web-player":
        fm_map = {}
        for item in args.fm:
            if "=" not in item:
                parser.error(f"--fm expects TRACK=PROGRAM, got {item!r}")
            name, program = item.rsplit("=", 1)
            fm_map[name] = int(program, 0)
        result = build_web_player(
            args.midi, args.voice, args.pcm, args.out,
            title=args.title, reference_vgm=args.vgm,
            fm_track_programs=fm_map,
            psg_tracks=set(args.psg), drum_tracks=set(args.drums),
        )
        _json({
            "path": str(Path(args.out)),
            "title": result["title"],
            "duration": result["duration"],
            "tracks": len(result["tracks"]),
        })
    elif args.command == "mub-midi":
        print(MUB.load(args.mub).to_midi(args.output, loops=args.loops))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from .daw_pack import extract_vgm_assets
from .muc_sequence import MucSong
from .mucom_daw import build_muc_daw_pack
from .mucom_voice import MucomVoiceBank
from .vgm import VgmFile
from .ym2612 import Ym2612State, group_volume_variants
from .ir import FmPatch


def _ops(patch: FmPatch):
    return {op.logical_operator: op for op in patch.operators}


def patch_distance(vgm: FmPatch, source: FmPatch) -> float:
    """Heuristic distance between a final VGM voice and a MUCOM source voice.

    Carrier TL is allowed to move substantially because game drivers use it
    for volume. Envelope/rate/ratio topology receives much higher weight.
    """
    score = 0.0
    if vgm.algorithm != source.algorithm:
        score += 1000.0
    score += 30.0 * abs(vgm.feedback - source.feedback)
    a = _ops(vgm)
    b = _ops(source)
    for logical in range(1, 5):
        x, y = a[logical], b[logical]
        score += 40.0 if x.multiple != y.multiple else 0.0
        score += 25.0 if x.detune != y.detune else 0.0
        score += 4.0 * abs(x.attack_rate - y.attack_rate)
        score += 3.0 * abs(x.decay_rate - y.decay_rate)
        score += 2.0 * abs(x.sustain_rate - y.sustain_rate)
        score += 2.0 * abs(x.release_rate - y.release_rate)
        score += 2.0 * abs(x.sustain_level - y.sustain_level)
        score += 3.0 * abs(x.rate_scale - y.rate_scale)
        score += 0.3 * abs(x.total_level - y.total_level)
    return round(score, 3)


def _confidence(score: float) -> str:
    if score <= 20:
        return "strong"
    if score <= 80:
        return "likely"
    if score <= 160:
        return "modified/possible"
    return "weak"


def match_muc_to_vgm(muc_path: str | Path, vgm_path: str | Path) -> dict[str, object]:
    muc = Path(muc_path)
    song = MucSong.load(muc)
    voice_name = song.metadata.get("voice")
    if not voice_name:
        raise ValueError("MUC source has no #voice companion")
    bank = MucomVoiceBank.load(muc.parent / voice_name)
    used_programs = sorted({bank.resolve(p).program for p in song.used_patches(kinds={"fm"})})
    source_patches = {program: bank.by_program(program).to_patch() for program in used_programs}

    vgm = VgmFile.load(vgm_path)
    state = Ym2612State()
    for command in vgm.commands():
        if command.kind == "ym2612":
            port, reg, value = command.values
            state.write(port, reg, value, command.sample)
    final_patches = group_volume_variants(list(state.patches.values()))

    matches: list[dict[str, object]] = []
    for index, patch in enumerate(final_patches, start=1):
        ranked = sorted((patch_distance(patch, source_patches[p]), p) for p in used_programs)
        best_score, program = ranked[0]
        voice = bank.by_program(program)
        matches.append({
            "vgm_index": index,
            "vgm_patch_id": patch.id,
            "vgm_source_channels": patch.source_channels,
            "vgm_use_count": patch.use_count,
            "mucom_program": program,
            "mucom_voice_name": voice.name,
            "mucom_preset": f"MUC/FM/{voice.display_name}.rym2612",
            "score": best_score,
            "confidence": _confidence(best_score),
            "runner_up": {
                "program": ranked[1][1],
                "name": bank.by_program(ranked[1][1]).name,
                "score": ranked[1][0],
            } if len(ranked) > 1 else None,
        })

    return {
        "format": "smd-music-hybrid-map-v1",
        "title": song.metadata.get("title", muc.stem),
        "muc": muc.name,
        "vgm": Path(vgm_path).name,
        "used_mucom_programs": used_programs,
        "vgm_patch_count": len(final_patches),
        "matches": matches,
        "notes": [
            "Low scores mean the final VGM patch closely matches the published MUCOM source voice.",
            "Scores in modified/possible range often reflect deliberate yDR/ySR/TL edits made while the source voice is active.",
            "This mapping links source semantics to final Genesis hardware state; it is not used as a copyright/source-file substitute.",
        ],
    }


def build_hybrid_pack(
    muc_path: str | Path,
    vgm_path: str | Path,
    out_dir: str | Path,
    *,
    bpm: float = 100.0,
) -> dict[str, object]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    muc_manifest = build_muc_daw_pack(muc_path, out / "MUC", bpm=bpm)
    vgm_manifest = extract_vgm_assets(vgm_path, out / "VGM")
    mapping = match_muc_to_vgm(muc_path, vgm_path)
    (out / "hybrid_map.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest = {
        "format": "smd-music-hybrid-pack-v1",
        "title": mapping["title"],
        "muc_pack": "MUC/manifest.json",
        "vgm_pack": "VGM/manifest.json",
        "hybrid_map": "hybrid_map.json",
        "summary": {
            "mucom_programs": len(mapping["used_mucom_programs"]),
            "final_vgm_voices": mapping["vgm_patch_count"],
            "muc_midi_tracks": len(muc_manifest["midi"]["tracks"]),
            "vgm_duration_seconds": vgm_manifest["vgm"]["duration_seconds"],
        },
        "workflow": [
            "Use MUC/plugin MIDI for editable semantic notes and original MUCOM voice identities.",
            "Use VGM assets and hybrid_map.json to verify which voice state actually reached YM2612 in the Mega Drive port.",
            "Use the VGM-derived/GM arrangement for convenient stock GarageBand instruments when exact FM synthesis is not needed.",
        ],
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest

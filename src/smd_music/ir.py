from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


SourceKind = Literal["rom", "vgm", "muc", "mub", "manual"]
TrackKind = Literal["fm", "psg", "dac", "pcm", "rhythm", "midi", "unknown"]


@dataclass(slots=True)
class Provenance:
    source_kind: SourceKind
    source_name: str
    source_sha256: str | None = None
    source_offset: int | None = None
    notes: str | None = None


@dataclass(slots=True)
class NoteEvent:
    start: float
    duration: float
    pitch: int
    velocity: int = 100
    patch_id: str | None = None
    source_channel: str | None = None
    gate: float | None = None


@dataclass(slots=True)
class ControlEvent:
    time: float
    kind: str
    value: Any


@dataclass(slots=True)
class FmOperator:
    # OPN register slot order. logical_operator is supplied separately because
    # YM2612 register slot ordering is 1,3,2,4 rather than 1,2,3,4.
    logical_operator: int
    detune: int
    multiple: int
    total_level: int
    rate_scale: int
    attack_rate: int
    am_enable: int
    decay_rate: int
    sustain_rate: int
    sustain_level: int
    release_rate: int
    ssg_eg: int


@dataclass(slots=True)
class FmPatch:
    id: str
    algorithm: int
    feedback: int
    ams: int
    fms: int
    pan_left: bool
    pan_right: bool
    operators: list[FmOperator]
    first_seen_sample: int | None = None
    use_count: int = 0
    source_channels: list[int] = field(default_factory=list)


@dataclass(slots=True)
class Track:
    name: str
    kind: TrackKind
    chip: str | None = None
    source_channel: str | None = None
    notes: list[NoteEvent] = field(default_factory=list)
    controls: list[ControlEvent] = field(default_factory=list)


@dataclass(slots=True)
class Song:
    title: str
    ppq: int = 96
    bpm: float | None = None
    tracks: list[Track] = field(default_factory=list)
    fm_patches: list[FmPatch] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    provenance: list[Provenance] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

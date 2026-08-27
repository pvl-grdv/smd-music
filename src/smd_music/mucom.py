from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


_HEADER_RE = re.compile(r"^#(?P<key>[A-Za-z0-9_]+)\s+(?P<value>.*)$")


@dataclass(slots=True)
class MucProject:
    path: Path
    metadata: dict[str, str]

    @classmethod
    def load(cls, path: str | Path) -> "MucProject":
        p = Path(path)
        raw = p.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp932", errors="replace")
        metadata: dict[str, str] = {}
        for line in text.splitlines():
            match = _HEADER_RE.match(line.strip())
            if match:
                metadata[match.group("key").lower()] = match.group("value").strip()
        return cls(p, metadata)

    def companion(self, key: str) -> Path | None:
        value = self.metadata.get(key.lower())
        return self.path.parent / value if value else None


def find_mucom88() -> str | None:
    return shutil.which("mucom88")


def compile_muc(
    source: str | Path,
    output: str | Path,
    *,
    executable: str | None = None,
) -> Path:
    """Compile MUC to MUB using an installed Open MUCOM88 CLI.

    Open MUCOM88 is intentionally not vendored: it has its own CC BY-NC-SA
    licensing and bundled-component terms. The user installs it separately.
    """

    exe = executable or find_mucom88()
    if not exe:
        raise RuntimeError("mucom88 executable not found in PATH")
    src = Path(source)
    out = Path(output)
    project = MucProject.load(src)
    cmd = [exe, "-c", "-g", "-o", str(out)]
    voice = project.companion("voice")
    pcm = project.companion("pcm")
    if voice and voice.exists():
        cmd += ["-v", str(voice)]
    if pcm and pcm.exists():
        cmd += ["-p", str(pcm)]
    cmd += [str(src)]
    subprocess.run(cmd, check=True, cwd=src.parent)
    return out

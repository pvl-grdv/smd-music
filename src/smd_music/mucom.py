from __future__ import annotations

import os
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
        # Historical MUC sources are frequently Shift-JIS, while newer sample
        # archives may be UTF-8. Try UTF-8 first, then CP932.
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


def _candidate_node_modules(start: Path) -> list[Path]:
    candidates: list[Path] = []
    for base in [start, Path.cwd(), Path(__file__).resolve().parents[2]]:
        base = base.resolve()
        for parent in [base, *base.parents]:
            p = parent / "node_modules" / "mucom88-js" / "dist" / "index.js"
            if p not in candidates:
                candidates.append(p)
    return candidates


def find_mucom88_js(source_dir: str | Path | None = None) -> Path | None:
    """Find an installed ``mucom88-js`` ESM entry point.

    This is an optional external backend. It is deliberately not vendored into
    smd-music because Open MUCOM88/mucom88-js has its own CC BY-NC-SA license.
    """
    override = os.environ.get("SMD_MUSIC_MUCOM88_JS")
    if override:
        p = Path(override).expanduser()
        if p.is_dir():
            p = p / "dist" / "index.js"
        if p.exists():
            return p.resolve()

    start = Path(source_dir) if source_dir is not None else Path.cwd()
    for candidate in _candidate_node_modules(start):
        if candidate.exists():
            return candidate

    npm = shutil.which("npm")
    if npm:
        try:
            root = subprocess.run(
                [npm, "root", "-g"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            candidate = Path(root) / "mucom88-js" / "dist" / "index.js"
            if candidate.exists():
                return candidate.resolve()
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def _compile_with_native(src: Path, out: Path, executable: str) -> Path:
    project = MucProject.load(src)
    cmd = [executable, "-c", "-g", "-o", str(out)]
    voice = project.companion("voice")
    pcm = project.companion("pcm")
    if voice and voice.exists():
        cmd += ["-v", str(voice)]
    if pcm and pcm.exists():
        cmd += ["-p", str(pcm)]
    cmd += [str(src)]
    subprocess.run(cmd, check=True, cwd=src.parent)
    return out


def _compile_with_js(src: Path, out: Path, module: Path) -> Path:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node executable not found; cannot use mucom88-js backend")
    helper = Path(__file__).with_name("_mucom_compile.mjs")
    subprocess.run(
        [node, str(helper), str(module), str(src), str(out)],
        check=True,
        cwd=src.parent,
    )
    return out


def compile_muc(
    source: str | Path,
    output: str | Path,
    *,
    executable: str | None = None,
) -> Path:
    """Compile MUC to MUB with the best available Open MUCOM88 backend.

    Preference order:
      1. an explicitly supplied/native ``mucom88`` CLI;
      2. a native ``mucom88`` found in PATH;
      3. Node + an installed ``mucom88-js`` package.

    Both Open MUCOM88 and mucom88-js remain external dependencies because they
    carry their own CC BY-NC-SA licensing/component terms.
    """
    src = Path(source).resolve()
    out = Path(output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    exe = executable or find_mucom88()
    if exe:
        return _compile_with_native(src, out, exe)

    module = find_mucom88_js(src.parent)
    if module:
        return _compile_with_js(src, out, module)

    raise RuntimeError(
        "No MUCOM88 compiler backend found. Install Open MUCOM88, or run "
        "`npm install --no-save mucom88-js` in the smd-music checkout, or set "
        "SMD_MUSIC_MUCOM88_JS to the mucom88-js package directory."
    )

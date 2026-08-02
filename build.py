"""Build script for discord_messages_reader NVDA addon.

Creates a distributable .nvda-addon file (ZIP with specific structure).
Usage:  python build.py
Output: dist/discord_messages_reader-<version>.nvda-addon
"""

import configparser
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import NamedTemporaryFile

PROJECT_ROOT = Path(__file__).resolve().parent

# Stored in lexical order so archive member order is stable.
INCLUDED_FILES = (
    "LICENSE",
    "README.md",
    "THREAT_MODEL.md",
    "appModules/discord/__init__.py",
    "appModules/discordcanary/__init__.py",
    "appModules/discordptb/__init__.py",
    "doc/en/readme.html",
    "manifest.ini",
)

# Output directory
_DIST = "dist"
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_ZIP_MODE = stat.S_IFREG | 0o644
_VERSION_RE = re.compile(
    r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)


def _validated_archive_path(archive_name: str) -> PurePosixPath:
    parts = archive_name.split("/")
    path = PurePosixPath(archive_name)
    if (
        not archive_name
        or "\\" in archive_name
        or any(part in {"", ".", ".."} for part in parts)
        or path.is_absolute()
        or PureWindowsPath(archive_name).drive
    ):
        raise ValueError(f"unsafe archive path: {archive_name}")
    return path


def _collect_sources(root: Path) -> list[tuple[str, Path]]:
    sources = []
    for archive_name in INCLUDED_FILES:
        archive_path = _validated_archive_path(archive_name)
        source = root.joinpath(*archive_path.parts)
        current = root
        for part in archive_path.parts:
            current /= part
            if current.is_symlink():
                raise ValueError(f"required file is a symbolic link: {archive_name}")
            if current.is_junction():
                raise ValueError(f"required path is a symbolic link or junction: {archive_name}")
        if not source.is_file():
            raise FileNotFoundError(f"missing required file: {archive_name}")
        sources.append((archive_name, source))
    return sources


def read_version(root: Path = PROJECT_ROOT) -> str:
    with (root / "manifest.ini").open(encoding="utf-8") as f:
        content = "[manifest]\n" + f.read()
    cfg = configparser.ConfigParser()
    cfg.read_string(content)
    version = cfg["manifest"]["version"].strip()
    if _VERSION_RE.fullmatch(version) is None:
        raise ValueError(f"unsafe version in manifest.ini: {version!r}")
    return version


def build(root: Path = PROJECT_ROOT) -> Path:
    root = Path(root).resolve()
    version = read_version(root)
    sources = _collect_sources(root)
    out_name = f"discord_messages_reader-{version}.nvda-addon"
    dist = root / _DIST
    if dist.is_symlink() or dist.is_junction():
        raise ValueError("output directory is a symbolic link or junction")
    if dist.exists() and not dist.resolve().is_relative_to(root):
        raise ValueError("output directory escapes project root")
    dist.mkdir(exist_ok=True)
    out_path = dist / out_name
    temporary_path = None
    try:
        with NamedTemporaryFile(
            mode="w+b",
            dir=dist,
            prefix=f".{out_name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            with zipfile.ZipFile(
                temporary_file,
                "w",
                compression=zipfile.ZIP_STORED,
            ) as zf:
                for archive_name, source in sources:
                    info = zipfile.ZipInfo(archive_name, date_time=_ZIP_TIMESTAMP)
                    info.create_system = 3
                    info.external_attr = _ZIP_MODE << 16
                    info.compress_type = zipfile.ZIP_STORED
                    zf.writestr(info, source.read_bytes())
                    print(f"  added {archive_name}")
        temporary_path.replace(out_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    print(f"\nBuilt: {out_path}")
    return out_path


if __name__ == "__main__":
    build()

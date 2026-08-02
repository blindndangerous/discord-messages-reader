"""Tests for deterministic, safe NVDA add-on packaging."""

from __future__ import annotations

import hashlib
import os
import zipfile
from pathlib import Path

import pytest

import build as build_module

REQUIRED_ARCHIVE_FILES = [
    "LICENSE",
    "README.md",
    "THREAT_MODEL.md",
    "appModules/discord/__init__.py",
    "appModules/discordcanary/__init__.py",
    "appModules/discordptb/__init__.py",
    "doc/en/readme.html",
    "manifest.ini",
]


def _create_project(root: Path) -> None:
    contents = {
        "LICENSE": "license\n",
        "README.md": "readme\n",
        "THREAT_MODEL.md": "threat model\n",
        "appModules/discord/__init__.py": "stable = True\n",
        "appModules/discordcanary/__init__.py": "canary = True\n",
        "appModules/discordptb/__init__.py": "ptb = True\n",
        "doc/en/readme.html": "<!doctype html><title>Help</title>\n",
        "manifest.ini": "name = discord_messages_reader\nversion = 1.2.3\n",
    }
    for relative_path, content in contents.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")


def test_build_includes_required_files_in_stable_order(tmp_path: Path) -> None:
    _create_project(tmp_path)

    archive_path = build_module.build(tmp_path)

    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == REQUIRED_ARCHIVE_FILES
        assert archive.read("LICENSE") == b"license\n"


def test_build_identifies_missing_required_file(tmp_path: Path) -> None:
    _create_project(tmp_path)
    (tmp_path / "LICENSE").unlink()

    with pytest.raises(FileNotFoundError, match=r"missing required file: LICENSE"):
        build_module.build(tmp_path)

    assert not (tmp_path / "dist" / "discord_messages_reader-1.2.3.nvda-addon").exists()


def test_build_rejects_symlinked_required_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _create_project(tmp_path)
    license_path = tmp_path / "LICENSE"
    target = tmp_path / "license-target"
    license_path.rename(target)
    try:
        license_path.symlink_to(target)
    except OSError:
        # Windows requires an optional privilege to create symlinks. Preserve
        # the real build path while substituting only that unavailable OS fact.
        target.rename(license_path)
        monkeypatch.setattr(Path, "is_symlink", lambda path: path == license_path)

    with pytest.raises(ValueError, match=r"symbolic link: LICENSE"):
        build_module.build(tmp_path)


def test_build_rejects_path_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _create_project(tmp_path)
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("private\n", encoding="utf-8")
    monkeypatch.setattr(build_module, "INCLUDED_FILES", ("../outside.txt",))

    with pytest.raises(ValueError, match=r"unsafe archive path: ../outside.txt"):
        build_module.build(tmp_path)


def test_build_rejects_symlinked_parent_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _create_project(tmp_path)
    discord_dir = tmp_path / "appModules" / "discord"
    target = tmp_path / "discord-target"
    discord_dir.rename(target)
    try:
        discord_dir.symlink_to(target, target_is_directory=True)
    except OSError:
        target.rename(discord_dir)
        monkeypatch.setattr(Path, "is_symlink", lambda path: path == discord_dir)

    with pytest.raises(ValueError, match=r"symbolic link: appModules/discord/__init__.py"):
        build_module.build(tmp_path)


def test_build_rejects_junctioned_parent_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _create_project(tmp_path)
    discord_dir = tmp_path / "appModules" / "discord"
    monkeypatch.setattr(Path, "is_junction", lambda path: path == discord_dir)

    with pytest.raises(ValueError, match=r"symbolic link or junction: appModules/discord/__init__.py"):
        build_module.build(tmp_path)


def test_build_normalizes_zip_metadata(tmp_path: Path) -> None:
    _create_project(tmp_path)

    archive_path = build_module.build(tmp_path)

    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.create_system == 3
            assert info.external_attr >> 16 == 0o100644
            assert info.compress_type == zipfile.ZIP_STORED


def test_repeated_build_hash_is_independent_of_source_mtime(tmp_path: Path) -> None:
    _create_project(tmp_path)
    archive_path = build_module.build(tmp_path)
    first_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    os.utime(tmp_path / "LICENSE", (2_000_000_000, 2_000_000_000))

    archive_path = build_module.build(tmp_path)
    second_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()

    assert second_hash == first_hash


def test_build_rejects_version_that_escapes_dist(tmp_path: Path) -> None:
    _create_project(tmp_path)
    escaped_name = f"escaped-{tmp_path.name}"
    (tmp_path / "manifest.ini").write_text(
        f"name = discord_messages_reader\nversion = 1.2.3/../../../{escaped_name}\n",
        encoding="utf-8",
    )
    (tmp_path / "dist" / "discord_messages_reader-1.2.3").mkdir(parents=True)
    escaped_archive = tmp_path.parent / f"{escaped_name}.nvda-addon"

    with pytest.raises(ValueError, match=r"unsafe version"):
        build_module.build(tmp_path)

    assert not escaped_archive.exists()


def test_build_rejects_symlinked_output_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _create_project(tmp_path)
    dist = tmp_path / "dist"
    target = tmp_path.parent / f"dist-target-{tmp_path.name}"
    target.mkdir()
    try:
        dist.symlink_to(target, target_is_directory=True)
    except OSError:
        dist.mkdir()
        monkeypatch.setattr(Path, "is_symlink", lambda path: path == dist)

    with pytest.raises(ValueError, match=r"output directory is a symbolic link"):
        build_module.build(tmp_path)


def test_failed_rebuild_preserves_final_archive_and_removes_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_project(tmp_path)
    archive_path = build_module.build(tmp_path)
    original_archive = archive_path.read_bytes()
    original_writestr = zipfile.ZipFile.writestr
    writes = 0

    def fail_during_second_write(self, *args, **kwargs):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("simulated disk failure")
        return original_writestr(self, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "writestr", fail_during_second_write)

    with pytest.raises(OSError, match=r"simulated disk failure"):
        build_module.build(tmp_path)

    assert archive_path.read_bytes() == original_archive
    assert list((tmp_path / "dist").glob("*.tmp")) == []


def test_interrupted_rebuild_preserves_final_archive_and_removes_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_project(tmp_path)
    archive_path = build_module.build(tmp_path)
    original_archive = archive_path.read_bytes()
    original_writestr = zipfile.ZipFile.writestr
    writes = 0

    def interrupt_during_second_write(self, *args, **kwargs):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise KeyboardInterrupt
        return original_writestr(self, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "writestr", interrupt_during_second_write)

    with pytest.raises(KeyboardInterrupt):
        build_module.build(tmp_path)

    assert archive_path.read_bytes() == original_archive
    assert list((tmp_path / "dist").glob("*.tmp")) == []

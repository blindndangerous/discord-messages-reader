"""Compatibility tests for NVDA's ``appModules`` package namespace."""

import importlib
import sys
from pathlib import Path


def _import_alias_from_nvda_namespace(monkeypatch, alias: str):
    app_modules_dir = Path(__file__).parents[1] / "appModules"
    search_path = [entry for entry in sys.path if Path(entry or ".").resolve() != app_modules_dir.resolve()]
    monkeypatch.setattr(sys, "path", search_path)
    monkeypatch.delitem(sys.modules, "discord", raising=False)
    monkeypatch.delitem(sys.modules, f"appModules.{alias}", raising=False)

    stable = importlib.import_module("appModules.discord")
    alias_module = importlib.import_module(f"appModules.{alias}")

    assert alias_module.AppModule is stable.AppModule


def test_discord_ptb_imports_stable_module_from_nvda_namespace(monkeypatch):
    _import_alias_from_nvda_namespace(monkeypatch, "discordptb")


def test_discord_canary_imports_stable_module_from_nvda_namespace(monkeypatch):
    _import_alias_from_nvda_namespace(monkeypatch, "discordcanary")

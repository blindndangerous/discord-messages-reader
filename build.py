"""Build script for discord_messages_reader NVDA addon.

Creates a distributable .nvda-addon file (ZIP with specific structure).
Usage:  python build.py
Output: dist/discord_messages_reader-<version>.nvda-addon
"""
import configparser
import os
import sys
import zipfile

# Files/directories to include relative to the project root
_INCLUDE = [
    ("manifest.ini",                            "manifest.ini"),
    ("appModules/discord/__init__.py",          "appModules/discord/__init__.py"),
    ("appModules/discordptb/__init__.py",       "appModules/discordptb/__init__.py"),
    ("appModules/discordcanary/__init__.py",    "appModules/discordcanary/__init__.py"),
]

# Output directory
_DIST = "dist"


def read_version():
    with open("manifest.ini", encoding="utf-8") as f:
        content = "[manifest]\n" + f.read()
    cfg = configparser.ConfigParser()
    cfg.read_string(content)
    return cfg["manifest"]["version"].strip()


def build():
    root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root)

    version = read_version()
    out_name = "discord_messages_reader-%s.nvda-addon" % version
    os.makedirs(_DIST, exist_ok=True)
    out_path = os.path.join(_DIST, out_name)

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for src, arc in _INCLUDE:
            if not os.path.isfile(src):
                print("ERROR: missing required file: %s" % src, file=sys.stderr)
                sys.exit(1)
            zf.write(src, arc)
            print("  added %s" % arc)

    print("\nBuilt: %s" % out_path)
    return out_path


if __name__ == "__main__":
    build()

"""Create a portable Windows ZIP from the already-built executable."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from codex_rate import __version__


def main():
    root = Path(__file__).resolve().parent
    executable = root / "dist" / "CodexRate.exe"
    if not executable.is_file():
        raise SystemExit("Run build.cmd before creating the release ZIP.")
    files = [(executable, "CodexRate.exe")]
    for name in ("README.md", "Start-Codex-Rate.cmd", "THIRD_PARTY_NOTICES.md", "RELEASE_NOTES.md"):
        files.append((root / name, name))
    files.extend((path, "licenses/" + path.name) for path in sorted((root / "licenses").glob("*.txt")))
    for path, _ in files:
        if not path.is_file():
            raise SystemExit(f"Missing release file: {path.name}")
    archive = root / "dist" / f"CodexRate-v{__version__}-windows-x64.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
        for path, name in files:
            bundle.write(path, name)
    print(archive)


if __name__ == "__main__":
    main()

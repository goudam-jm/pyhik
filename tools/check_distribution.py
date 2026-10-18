"""Fail if a wheel/sdist accidentally ships vendor libraries or the legacy shim."""

from pathlib import Path
import tarfile
import zipfile


def main():
    archives = list(Path("dist").glob("*.whl")) + list(Path("dist").glob("*.tar.gz"))
    if not any(p.suffix == ".whl" for p in archives) or not any(p.name.endswith(".tar.gz") for p in archives):
        raise SystemExit("Build both a wheel and sdist first")
    for archive in archives:
        if archive.suffix == ".whl":
            with zipfile.ZipFile(archive) as file:
                names = file.namelist()
        else:
            with tarfile.open(archive) as file:
                names = file.getnames()
        forbidden = [
            name
            for name in names
            if Path(name).suffix.lower() in (".dll", ".so", ".dylib") or Path(name).name == "pyhik.py"
        ]
        if forbidden:
            raise SystemExit(f"Unexpected distributed files in {archive}: {forbidden}")
        for required in ("hikvision_native.py", "hikvision_isapi.py", "THIRD_PARTY_NOTICES.md"):
            if not any(Path(name).name == required for name in names):
                raise SystemExit(f"{required} missing from {archive}")
        if archive.name.endswith(".tar.gz"):
            for required in ("tools/abi_probe.c", "tools/check_abi.py", "tools/check_distribution.py"):
                if not any(name.endswith("/" + required) for name in names):
                    raise SystemExit(f"Validation tool {required} missing from {archive}")
        print(f"Distribution boundary checked: {archive.name}")


if __name__ == "__main__":
    main()

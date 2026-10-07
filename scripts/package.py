import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {"work", ".venv", ".git", "__pycache__", ".pytest_cache", ".ruff_cache", "target", "logs"}


def files():
    return sorted(
        p
        for p in ROOT.rglob("*")
        if p.is_file()
        and not any(x in SKIP or x.endswith(".egg-info") for x in p.relative_to(ROOT).parts)
        and p.name not in {"package-manifest.json", ".user.yml", ".env"}
        and p.suffix not in {".pyc", ".sqlite", ".duckdb"}
    )


def manifest():
    body = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files()}
    (ROOT / "package-manifest.json").write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return body


def package():
    hashes = manifest()
    target = ROOT.parent / "Richard_Butts_Customer_Signal_Activation_B2B_GitHub_Ready.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for name in [*hashes, "package-manifest.json"]:
            z.write(ROOT / name, ROOT.name + "/" + name)
    with zipfile.ZipFile(target) as z:
        assert set(z.namelist()) == {ROOT.name + "/" + n for n in [*hashes, "package-manifest.json"]}
        assert all(hashlib.sha256(z.read(ROOT.name + "/" + n)).hexdigest() == h for n, h in hashes.items())
    print(f"Verified {len(hashes)} file hashes: {target}")


if __name__ == "__main__":
    package()

"""Download the pinned official model; verify SHA-256 before it can be used."""

import argparse
import hashlib
import urllib.request
from pathlib import Path

MODEL = "Qwen3-14B-Q4_K_M.gguf"
REVISION = "530227a7d994db8eca5ab5ced2fb692b614357fd"
SHA256 = "500a8806e85ee9c83f3ae08420295592451379b4f8cf2d0f41c15dffeb6b81f0"
URL = f"https://huggingface.co/Qwen/Qwen3-14B-GGUF/resolve/{REVISION}/{MODEL}?download=true"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--directory", type=Path, default=Path("work/models"))
    args = p.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    target = args.directory / MODEL
    if not target.exists():
        partial = target.with_suffix(".partial")
        print("Downloading pinned model (9.0 GB); weights are excluded from repository packages.", flush=True)
        urllib.request.urlretrieve(URL, partial)
        target = partial
    sha = hashlib.file_digest(target.open("rb"), "sha256").hexdigest()
    if sha != SHA256:
        raise RuntimeError("Model SHA-256 mismatch; model must not be used")
    if target.suffix == ".partial":
        target.rename(args.directory / MODEL)
    print(f"Verified {MODEL}: {sha}")


if __name__ == "__main__":
    main()

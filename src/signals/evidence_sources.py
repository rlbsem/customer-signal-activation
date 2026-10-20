"""Check historical executable bytes without treating today's checkout as native-tested."""
from contextlib import contextmanager
import hashlib
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile


@contextmanager
def historical_source_tree(repository, fingerprints, revision):
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("immutable_source_revision_required")
    if not fingerprints:
        raise ValueError("source_fingerprints_required")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for name, expected in fingerprints.items():
            parts = PurePosixPath(name).parts
            if (not parts or any(part in (".", "..") for part in parts)
                    or PurePosixPath(name).is_absolute() or "\\" in name or ":" in name):
                raise ValueError("unsafe_source_path")
            raw = subprocess.check_output(["git", "show", revision + ":" + name], cwd=repository)
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError("historical_executable_fingerprint_mismatch:" + name)
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        yield root

import hashlib

import pytest

from signals.evidence_sources import historical_source_tree


def test_historical_executable_bytes_are_independently_checked(tmp_path, monkeypatch):
    raw = b"historical source, not current source"
    monkeypatch.setattr("signals.evidence_sources.subprocess.check_output", lambda *args, **kwargs: raw)
    with historical_source_tree(tmp_path, {"src/module.py": hashlib.sha256(raw).hexdigest()}, "a" * 40) as tree:
        assert (tree / "src/module.py").read_bytes() == raw
    with pytest.raises(ValueError, match="fingerprint_mismatch"):
        with historical_source_tree(tmp_path, {"src/module.py": "0" * 64}, "a" * 40):
            pass


@pytest.mark.parametrize("name", ["../source.py", "/source.py", "C:/source.py", "src\\source.py"])
def test_historical_source_paths_cannot_escape_temporary_tree(tmp_path, name):
    with pytest.raises(ValueError, match="unsafe_source_path"):
        with historical_source_tree(tmp_path, {name: "0" * 64}, "a" * 40):
            pass


def test_historical_source_requires_immutable_commit(tmp_path):
    with pytest.raises(ValueError, match="immutable_source_revision"):
        with historical_source_tree(tmp_path, {"source.py": "0" * 64}, "main"):
            pass

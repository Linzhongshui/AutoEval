import hashlib

import pytest

from autoeval.aisbench_native import verify_source


def test_changed_or_extra_python_source_rejects_native_execution(tmp_path):
    source = tmp_path / "ais_bench"
    source.mkdir()
    scorer = source / "scorer.py"
    scorer.write_bytes(b"original source")
    lock = {"files": {"ais_bench/scorer.py": hashlib.sha256(scorer.read_bytes()).hexdigest()}}
    verify_source(tmp_path, lock)
    scorer.write_bytes(b"changed scoring rules")
    with pytest.raises(ValueError, match="checksum"):
        verify_source(tmp_path, lock)
    scorer.write_bytes(b"original source")
    (source / "extra.py").write_text("shadow source")
    with pytest.raises(ValueError, match="tree"):
        verify_source(tmp_path, lock)

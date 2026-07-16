import json
import os
from pathlib import Path

import backup


def test_backup_to_copies_history_and_single_files(tmp_path, monkeypatch):
    # Susun project palsu: history/ + config.json + sparing.log
    project = tmp_path / "project"
    project.mkdir()
    hist_dir = project / "history"
    hist_dir.mkdir()
    (hist_dir / "2026-01-01.csv").write_text("timestamp_iso\n1\n", encoding="utf-8")
    (project / "config.json").write_text("{}", encoding="utf-8")
    (project / "sparing.log").write_text("log line\n", encoding="utf-8")

    dest = tmp_path / "flashdisk"
    dest.mkdir()

    monkeypatch.chdir(project)
    result = backup.backup_to(str(dest), {"history_dir": "history"})

    out_dir = Path(result["dest"])
    assert out_dir.parent == dest
    assert out_dir.name.startswith("SPARING_backup_")
    assert (out_dir / "history" / "2026-01-01.csv").exists()
    assert (out_dir / "config.json").exists()
    assert (out_dir / "sparing.log").exists()
    assert result["files"] == 3
    assert result["bytes"] > 0


def test_backup_to_skips_missing_optional_files(tmp_path, monkeypatch):
    project = tmp_path / "project2"
    project.mkdir()
    dest = tmp_path / "flashdisk2"
    dest.mkdir()

    monkeypatch.chdir(project)
    result = backup.backup_to(str(dest), {"history_dir": "history"})

    assert result["files"] == 0
    assert Path(result["dest"]).exists()


def test_list_removable_drives_returns_list_no_crash():
    # Tidak ada flashdisk tercolok saat test — hanya pastikan tidak exception
    # dan tipe kembaliannya benar.
    drives = backup.list_removable_drives()
    assert isinstance(drives, list)
    for d in drives:
        assert hasattr(d, "path") and hasattr(d, "label") and hasattr(d, "free_gb")

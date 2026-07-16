import csv
from pathlib import Path

import history
from models import SensorReading


def test_append_reading_creates_daily_csv_with_header(tmp_path):
    hist_dir = tmp_path / "history"
    r = SensorReading(timestamp=1750000000.0, ph=7.1, tss=50.2, debit=1.23,
                      cod=18.4, nh3n=1.1, temp=27.5)
    history.append_reading(r, op_mode="normal", history_dir=str(hist_dir))

    files = list(hist_dir.glob("*.csv"))
    assert len(files) == 1
    with open(files[0], encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == history._FIELDS
    assert rows[1][2:] == ["7.1", "50.2", "1.23", "18.4", "1.1", "27.5", "normal"]


def test_append_reading_appends_without_duplicate_header(tmp_path):
    hist_dir = tmp_path / "history"
    r1 = SensorReading(timestamp=1750000000.0, ph=7.0)
    r2 = SensorReading(timestamp=1750000120.0, ph=7.2)
    history.append_reading(r1, history_dir=str(hist_dir))
    history.append_reading(r2, history_dir=str(hist_dir))

    files = list(hist_dir.glob("*.csv"))
    assert len(files) == 1
    with open(files[0], encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 3  # header + 2 data rows


def test_prune_old_removes_files_past_retention(tmp_path):
    hist_dir = tmp_path / "history"
    hist_dir.mkdir()
    (hist_dir / "2020-01-01.csv").write_text("timestamp_iso\n", encoding="utf-8")
    (hist_dir / "2099-01-01.csv").write_text("timestamp_iso\n", encoding="utf-8")

    removed = history.prune_old(history_dir=str(hist_dir), retention_days=180)

    assert removed == 1
    remaining = {f.name for f in hist_dir.glob("*.csv")}
    assert remaining == {"2099-01-01.csv"}


def test_prune_old_missing_dir_is_noop(tmp_path):
    assert history.prune_old(history_dir=str(tmp_path / "nope")) == 0

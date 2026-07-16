"""
history.py — Arsip riwayat pembacaan sensor (CSV harian), independen dari
status pengiriman ke server. Berfungsi sebagai catatan black-box untuk
keperluan audit/inspeksi lapangan (ditarik via backup ke flashdisk).
"""

import csv
import logging
from datetime import datetime, timedelta
from pathlib import Path

from models import SensorReading

log = logging.getLogger(__name__)

_FIELDS = ["timestamp_iso", "timestamp_unix", "ph", "tss", "debit",
           "cod", "nh3n", "temp", "op_mode"]


def _day_file(history_dir: Path, ts: float) -> Path:
    d = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    return history_dir / f"{d}.csv"


def append_reading(r: SensorReading, op_mode: str = "normal",
                   history_dir: str = "history") -> None:
    """
    Tambahkan satu baris pembacaan ke CSV harian (buat file baru + header
    bila belum ada). Dipanggil setiap siklus sensor, terlepas dari
    sukses/gagalnya pengiriman ke server — ini arsip permanen, bukan buffer
    kirim ulang.
    """
    try:
        d = Path(history_dir)
        d.mkdir(parents=True, exist_ok=True)
        f = _day_file(d, r.timestamp)
        is_new = not f.exists()
        with open(f, "a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if is_new:
                w.writerow(_FIELDS)
            w.writerow([
                datetime.fromtimestamp(r.timestamp).strftime("%Y-%m-%d %H:%M:%S"),
                f"{r.timestamp:.0f}",
                r.ph, r.tss, r.debit, r.cod, r.nh3n, r.temp, op_mode,
            ])
    except Exception as e:
        log.error(f"Gagal menulis riwayat CSV: {e}")


def prune_old(history_dir: str = "history", retention_days: int = 180) -> int:
    """
    Hapus file CSV harian yang lebih tua dari retention_days.
    Kembalikan jumlah file yang dihapus.
    """
    d = Path(history_dir)
    if not d.exists():
        return 0
    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0
    for f in d.glob("*.csv"):
        try:
            day = datetime.strptime(f.stem, "%Y-%m-%d")
        except ValueError:
            continue
        if day < cutoff:
            try:
                f.unlink()
                removed += 1
            except OSError as e:
                log.warning(f"Gagal hapus {f.name}: {e}")
    return removed

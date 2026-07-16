"""
backup.py — Backup data ke media eksternal (flashdisk USB) agar bisa
ditarik secara offline oleh operator/inspektur, tanpa perlu akses jaringan.

Menyalin: riwayat CSV (history.py), config.json, sparing.log,
resource.log, buffer offline (data_buffer_s1/s2.json), gap_state.json —
ke folder bertanggal di flashdisk tujuan.
"""

import logging
import shutil
import string
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

from constants import IS_LINUX, IS_WINDOWS

log = logging.getLogger(__name__)

# File tunggal (di root project) yang disertakan dalam backup bila ada.
_SINGLE_FILES = (
    "config.json", "sparing.log", "resource.log",
    "data_buffer_s1.json", "data_buffer_s2.json", "gap_state.json",
)


@dataclass
class DriveInfo:
    path: str          # mount point / huruf drive, siap dipakai sebagai dest_root
    label: str         # nama tampilan untuk GUI
    free_gb: float


def list_removable_drives() -> List[DriveInfo]:
    """Deteksi drive yang bisa dijadikan tujuan backup (flashdisk/USB)."""
    drives: List[DriveInfo] = []
    if IS_WINDOWS:
        import ctypes
        DRIVE_REMOVABLE = 2
        try:
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        except Exception as e:
            log.warning(f"GetLogicalDrives gagal: {e}")
            return drives
        for i, letter in enumerate(string.ascii_uppercase):
            if not (bitmask >> i) & 1:
                continue
            root = f"{letter}:\\"
            try:
                if ctypes.windll.kernel32.GetDriveTypeW(root) != DRIVE_REMOVABLE:
                    continue
                free, _total, _ = shutil.disk_usage(root)
                drives.append(DriveInfo(path=root, label=root,
                                        free_gb=round(free / 1e9, 2)))
            except OSError:
                continue
    elif IS_LINUX:
        candidates: List[Path] = []
        media = Path("/media")
        if media.exists():
            for user_dir in media.iterdir():
                if user_dir.is_dir():
                    candidates.extend(p for p in user_dir.iterdir() if p.is_dir())
        run_media = Path("/run/media")
        if run_media.exists():
            for user_dir in run_media.iterdir():
                if user_dir.is_dir():
                    candidates.extend(p for p in user_dir.iterdir() if p.is_dir())
        mnt = Path("/mnt")
        if mnt.exists():
            candidates.extend(p for p in mnt.iterdir() if p.is_dir())
        for c in candidates:
            try:
                free, total, _ = shutil.disk_usage(c)
            except OSError:
                continue
            if total == 0:
                continue
            drives.append(DriveInfo(path=str(c), label=c.name,
                                    free_gb=round(free / 1e9, 2)))
    return drives


def backup_to(dest_root: str, cfg: dict) -> dict:
    """
    Salin riwayat CSV + file penting lain ke folder bertanggal di dest_root
    (mis. akar flashdisk). Kembalikan {"dest", "files", "bytes"}.
    Melempar exception bila dest_root tidak bisa ditulisi (mis. flashdisk
    dicabut di tengah proses) — pemanggil menangani & melaporkan ke log GUI.
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = Path(dest_root) / f"SPARING_backup_{stamp}"
    dest.mkdir(parents=True, exist_ok=True)

    files_copied = 0
    bytes_copied = 0

    history_dir = Path(cfg.get("history_dir", "history"))
    if history_dir.exists():
        hist_dest = dest / "history"
        hist_dest.mkdir(exist_ok=True)
        for f in sorted(history_dir.glob("*.csv")):
            shutil.copy2(f, hist_dest / f.name)
            files_copied += 1
            bytes_copied += f.stat().st_size

    for name in _SINGLE_FILES:
        f = Path(name)
        if f.exists():
            shutil.copy2(f, dest / name)
            files_copied += 1
            bytes_copied += f.stat().st_size

    log.info(f"Backup selesai: {files_copied} file, "
            f"{bytes_copied / 1e6:.1f} MB -> {dest}")
    return {"dest": str(dest), "files": files_copied, "bytes": bytes_copied}

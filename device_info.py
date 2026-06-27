"""device_info.py — Serial number & MAC address perangkat (lintas-platform)."""

import re
import uuid
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def get_serial(fallback: str = "—") -> str:
    """Serial number perangkat. Linux: /proc/cpuinfo atau device-tree.
    Platform lain / gagal baca: fallback."""
    try:
        cpu = Path("/proc/cpuinfo")
        if cpu.exists():
            for line in cpu.read_text(errors="ignore").splitlines():
                if line.lower().startswith("serial"):
                    val = line.split(":", 1)[1].strip()
                    if val:
                        return val
        dt = Path("/sys/firmware/devicetree/base/serial-number")
        if dt.exists():
            val = dt.read_text(errors="ignore").strip("\x00").strip()
            if val:
                return val
    except Exception as e:
        log.warning(f"get_serial gagal: {e}")
    return fallback


def _read_iface_mac(name: str) -> str:
    try:
        p = Path(f"/sys/class/net/{name}/address")
        if p.exists():
            return p.read_text().strip().upper()
    except Exception:
        pass
    return ""


def get_macs() -> dict:
    """Kembalikan {'eth0': mac, 'wlan0': mac}. Kosong → fallback dari uuid.getnode()."""
    eth = _read_iface_mac("eth0")
    wlan = _read_iface_mac("wlan0")
    if not eth and not wlan:
        node = uuid.getnode()
        mac = ":".join(re.findall("..", f"{node:012X}"))
        eth = mac
    return {"eth0": eth or "—", "wlan0": wlan or "—"}

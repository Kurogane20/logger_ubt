"""
sensors.py — Pembacaan sensor melalui USB RS485 (Modbus RTU).

Sensor yang didukung:
  - pH    : Modbus slave ID 2, holding register 0-1
  - TSS   : Modbus slave ID 10, holding register 0-4 (float CDAB)
  - Debit : Modbus slave ID 1, holding register 0-29 (double ABCD, reg 15-18)
"""

import inspect
import struct
import threading
import time
import logging
from typing import Optional

from constants import HAS_MODBUS, ModbusSerialClient
from config    import save_config, detect_usb_rs485
from models    import SensorReading

log = logging.getLogger(__name__)


# ─── Modbus Sensor Reader ─────────────────────────────────────────────────────
class SensorReader:
    """
    Membaca tiga sensor kualitas air via Modbus RTU over USB RS485,
    dan sensor arus/tegangan via ADC.

    USB RS485 adapter (CH340/CP210x/FT232/PL2303) mengelola sinyal DE/RE
    secara otomatis — tidak perlu pin GPIO RTS seperti pada Arduino.
    """

    def __init__(self, cfg: dict, on_error=None):
        self.cfg       = cfg
        self._mb       = None
        self._port_ok  = False
        self._on_error = on_error or (lambda msg: None)
        self._lock     = threading.Lock()   # proteksi akses Modbus antar-thread
        self._connect()

    # ── Koneksi Modbus ────────────────────────────────────────────────────────
    def _connect(self) -> None:
        if not HAS_MODBUS:
            return

        use_hat = self.cfg.get("use_rs485_hat", False)

        if use_hat:
            # ── Mode HAT (UART GPIO) ──────────────────────────────────────────
            # Port UART HAT: /dev/ttyAMA0 (RPi), /dev/ttyS0, /dev/serial0
            port = self.cfg.get("rs485_hat_port", "/dev/ttyAMA0")
            kwargs = dict(
                port     = port,
                baudrate = self.cfg["baud_rate"],
                stopbits = 1,
                bytesize = 8,
                parity   = "N",
                timeout  = 1,
                # Kontrol DE/RE via RTS — aktif saat kirim, nonaktif saat terima
                rts_level_for_send = True,
                rts_level_for_recv = False,
                broadcast_enable   = False,
            )
            mode_label = "RS485 HAT"
        else:
            # ── Mode USB RS485 adapter ────────────────────────────────────────
            port = self.cfg["serial_port"]
            if not port or port in ("COM3", "/dev/ttyUSB0"):
                detected = detect_usb_rs485()
                if detected:
                    port = detected
                    self.cfg["serial_port"] = port
                    save_config(self.cfg)
            kwargs = dict(
                port     = port,
                baudrate = self.cfg["baud_rate"],
                stopbits = 1,
                bytesize = 8,
                parity   = "N",
                timeout  = 1,
            )
            mode_label = "USB RS485"

        try:
            self._mb = ModbusSerialClient(**kwargs)
            if self._mb.connect():
                log.info(f"{mode_label} terhubung — port: {port}  baud: {self.cfg['baud_rate']}")
                self._port_ok = True
            else:
                log.warning(f"{mode_label} gagal membuka port {port}")
                self._mb      = None
                self._port_ok = False
        except Exception as e:
            # rts_level_for_send tidak didukung semua versi pymodbus —
            # coba ulang tanpa parameter RTS
            if use_hat and "rts_level" in str(e):
                log.warning(f"HAT RTS tidak didukung pymodbus versi ini, coba tanpa RTS: {e}")
                try:
                    kwargs.pop("rts_level_for_send", None)
                    kwargs.pop("rts_level_for_recv", None)
                    kwargs.pop("broadcast_enable",   None)
                    self._mb = ModbusSerialClient(**kwargs)
                    if self._mb.connect():
                        log.info(f"RS485 HAT terhubung (tanpa RTS) — port: {port}")
                        self._port_ok = True
                        return
                except Exception as e2:
                    log.error(f"RS485 HAT fallback gagal: {e2}")
            log.error(f"{mode_label} init error: {e}")
            self._on_error(f"[RS485] Gagal inisialisasi port {port}: {e}")
            self._mb      = None
            self._port_ok = False

    def _build_rhr(self) -> None:
        """
        Deteksi keyword slave ID dari signature fungsi — tanpa test call ke device.
        Urutan kandidat mencakup semua versi pymodbus yang diketahui:
          2.x   → 'unit'
          3.0+  → 'slave'
          3.12+ → 'device_id'
        """
        try:
            params = list(inspect.signature(
                self._mb.read_holding_registers).parameters.keys())
            log.info(f"rhr params: {params}")
        except Exception:
            params = []

        # Cari keyword yang cocok — gunakan inspeksi saja, tanpa test call
        for kw in ("device_id", "slave", "unit", "dev_id"):
            if kw in params:
                self._rhr_call = lambda a, c, s, k=kw: \
                    self._mb.read_holding_registers(a, count=c, **{k: s})
                log.info(f"pymodbus rhr: pakai keyword '{kw}'")
                return

        # Tidak ada keyword dikenal — coba pakai inspect untuk cari semua params
        # dan pilih parameter ke-3 (setelah self, address)
        slave_param = None
        for i, name in enumerate(params):
            if name not in ("self", "address", "count",
                            "no_response_expected"):
                slave_param = name
                break

        if slave_param:
            self._rhr_call = lambda a, c, s, k=slave_param: \
                self._mb.read_holding_registers(a, count=c, **{k: s})
            log.info(f"pymodbus rhr: auto-detect keyword '{slave_param}'")
            return

        # Fallback akhir: tanpa slave kwarg
        log.warning("pymodbus rhr: tidak ada slave kwarg, device_id diabaikan")
        self._rhr_call = lambda a, c, s: \
            self._mb.read_holding_registers(a, count=c)

    def _rhr(self, address: int, count: int, slave_id: int):
        """read_holding_registers kompatibel semua versi pymodbus."""
        if not hasattr(self, "_rhr_call"):
            self._build_rhr()
        return self._rhr_call(address, count, slave_id)

    def reconnect(self) -> bool:
        """Tutup dan buka ulang koneksi. Dipanggil dari tombol GUI.
        Mengambil _lock agar tidak balapan dengan read_all() yang sedang
        berjalan di thread sensor (yang bisa membuat _mb ditutup di
        tengah transaksi Modbus dan menyebabkan port gagal dibuka ulang)."""
        with self._lock:
            if self._mb:
                try:
                    self._mb.close()
                except Exception:
                    pass
                self._mb = None
            self._port_ok = False
            self._connect()
            return self._port_ok

    # ── pH ────────────────────────────────────────────────────────────────────
    def _read_ph(self) -> float:
        """Slave ID 2, holding register 0-1. Nilai = reg[1] / 100."""
        if self._mb is None:
            return 0.0
        try:
            r = self._rhr(0, 2, self.cfg["slave_id_ph"])
            if not r.isError():
                raw = r.registers[1] / 100.0
                return min(round(raw + self.cfg["offset_ph"], 2), 14.0)
            else:
                msg = f"[SENSOR] pH isError: {r}"
                log.error(msg)
                self._on_error(msg)
        except Exception as e:
            log.error(f"Baca pH gagal: {e}")
            self._on_error(f"[SENSOR] Baca pH gagal: {e}")
        return 0.0

    # ── TSS ───────────────────────────────────────────────────────────────────
    def _read_tss(self) -> float:
        """Slave ID 10, holding register 0-4. Float format CDAB: reg[3]<<16 | reg[2]."""
        if self._mb is None:
            return 0.0
        try:
            r = self._rhr(0, 5, self.cfg["slave_id_tss"])
            if not r.isError():
                combined = (r.registers[3] << 16) | r.registers[2]
                tss = struct.unpack("f", struct.pack("I", combined))[0]
                return round(tss - self.cfg["offset_tss"], 3)
            else:
                msg = f"[SENSOR] TSS isError: {r}"
                log.error(msg)
                self._on_error(msg)
        except Exception as e:
            log.error(f"Baca TSS gagal: {e}")
            self._on_error(f"[SENSOR] Baca TSS gagal: {e}")
        return 0.0

    # ── Debit ─────────────────────────────────────────────────────────────────
    def _read_debit(self) -> float:
        """Pilih tipe pembacaan debit sesuai config (open/closed channel)."""
        if self.cfg.get("debit_channel", "open") == "closed":
            return self._read_debit_closed()
        return self._read_debit_open()

    def _read_debit_open(self) -> float:
        """
        Slave ID 1, holding register 0-29. Double ABCD dari reg[15-18].
        Datasheet flowmeter mengeluarkan nilai dalam m³/jam → dikonversi ke
        m³/menit (÷60) agar sesuai satuan yang ditampilkan di GUI.
        """
        if self._mb is None:
            return 0.0
        try:
            r = self._rhr(0, 30, self.cfg["slave_id_debit"])
            if not r.isError():
                a, b, c, d = (r.registers[15], r.registers[16],
                              r.registers[17], r.registers[18])
                combined = (a << 48) | (b << 32) | (c << 16) | d
                debit_m3h = struct.unpack("d", struct.pack("Q", combined))[0]
                debit = debit_m3h / 60.0   # m³/jam → m³/menit (sesuai GUI)
                return round(debit - self.cfg["offset_debit"], 4)
            else:
                msg = f"[SENSOR] Debit isError: {r}"
                log.error(msg)
                self._on_error(msg)
        except Exception as e:
            log.error(f"Baca Debit gagal: {e}")
            self._on_error(f"[SENSOR] Baca Debit gagal: {e}")
        return 0.0

    def _read_debit_closed(self) -> float:
        """Debit saluran tertutup (closed channel). Float CDAB @ reg 0-1:
        combined = reg[1]<<16 | reg[0]. Nilai m³/jam → ÷60 ke m³/menit (sesuai GUI)."""
        if self._mb is None:
            return 0.0
        try:
            r = self._rhr(0, 2, self.cfg["slave_id_debit"])
            if not r.isError():
                combined = (r.registers[1] << 16) | r.registers[0]
                debit_m3h = struct.unpack("f", struct.pack("I", combined))[0]
                debit = debit_m3h / 60.0   # m³/jam → m³/menit (sesuai GUI)
                return round(debit - self.cfg["offset_debit"], 4)
            else:
                msg = f"[SENSOR] Debit(closed) isError: {r}"
                log.error(msg)
                self._on_error(msg)
        except Exception as e:
            log.error(f"Baca Debit(closed) gagal: {e}")
            self._on_error(f"[SENSOR] Baca Debit(closed) gagal: {e}")
        return 0.0

    # ── COD & NH3-N (generic Modbus scaled reader) ───────────────────────────
    def _read_scaled(self, sensor: str, slave_key: str, addr_key: str,
                     count_key: str, index_key: str, scale_key: str,
                     offset_key: str) -> float:
        """Pembacaan Modbus generik: nilai = reg[index] / scale + offset."""
        if self._mb is None:
            return 0.0
        try:
            addr  = self.cfg[addr_key]
            count = self.cfg[count_key]
            r = self._rhr(addr, count, self.cfg[slave_key])
            if not r.isError():
                idx = self.cfg[index_key]
                # offset bersifat aditif (kalibrasi), konsisten dengan _read_ph
                val = r.registers[idx] / self.cfg[scale_key]
                return round(val + self.cfg.get(offset_key, 0.0), 3)
            else:
                msg = f"[SENSOR] {sensor} isError: {r}"
                log.error(msg)
                self._on_error(msg)
        except Exception as e:
            log.error(f"Baca {sensor} gagal: {e}")
            self._on_error(f"[SENSOR] Baca {sensor} gagal: {e}")
        return 0.0

    def _read_cod(self) -> float:
        """CODS-3000-02: slave_id_cod, reg addr 0, 2 registers, IEEE-754 float
        (CDAB word order: combined = reg[1]<<16 | reg[0]). Satuan mg/L."""
        if self._mb is None:
            return 0.0
        try:
            r = self._rhr(self.cfg["reg_addr_cod"], self.cfg["reg_count_cod"],
                          self.cfg["slave_id_cod"])
            if not r.isError():
                combined = (r.registers[1] << 16) | r.registers[0]
                cod = struct.unpack("f", struct.pack("I", combined))[0]
                return round(cod + self.cfg.get("offset_cod", 0.0), 2)
            else:
                msg = f"[SENSOR] COD isError: {r}"
                log.error(msg)
                self._on_error(msg)
        except Exception as e:
            log.error(f"Baca COD gagal: {e}")
            self._on_error(f"[SENSOR] Baca COD gagal: {e}")
        return 0.0

    def _read_nh3n(self) -> float:
        return self._read_scaled(
            "nh3n", "slave_id_nh3n", "reg_addr_nh3n", "reg_count_nh3n",
            "reg_index_nh3n", "scale_nh3n", "offset_nh3n")

    # ── Suhu air ──────────────────────────────────────────────────────────────
    def _read_temp(self) -> float:
        """
        Slave ID = slave_id_temp (default 5).
        Register address=0, count=1:
          reg[0] / 10 = suhu (°C)
        """
        if self._mb is None:
            return 0.0
        try:
            r = self._rhr(0, 1, self.cfg["slave_id_temp"])
            if not r.isError():
                raw  = r.registers[0]
                temp = round(raw / 10 + self.cfg.get("offset_temp", 0.0), 1)
                return temp
            else:
                msg = f"[SENSOR] Temp isError: {r}"
                log.error(msg)
                self._on_error(msg)
        except Exception as e:
            log.error(f"Baca Temp gagal: {e}")
            self._on_error(f"[SENSOR] Baca Temp gagal: {e}")
        return 0.0

    # ── Baca semua sensor ─────────────────────────────────────────────────────
    def read_all(self) -> SensorReading:
        reading = SensorReading(timestamp=time.time())
        with self._lock:
            if self.cfg.get("sensor_ph_enabled", True):
                reading.ph    = self._read_ph()
                time.sleep(0.1)
            if self.cfg.get("sensor_tss_enabled", True):
                reading.tss   = self._read_tss()
                time.sleep(0.1)
            if self.cfg.get("sensor_debit_enabled", True):
                reading.debit = self._read_debit()
                time.sleep(0.1)
            if self.cfg.get("sensor_cod_enabled", True):
                reading.cod   = self._read_cod()
                time.sleep(0.1)
            if self.cfg.get("sensor_nh3n_enabled", True):
                reading.nh3n  = self._read_nh3n()
                time.sleep(0.1)
            if self.cfg.get("sensor_temp_enabled", True):
                reading.temp  = self._read_temp()
        return reading

    def close(self) -> None:
        if self._mb:
            self._mb.close()

"""
app.py — SparingApp: orkestrator utama yang menghubungkan semua modul.
Menjalankan dua background thread (sensor & network) dan GUI di main thread.
"""

import json
import queue
import time
import threading
import logging
from typing import List, Optional

import tkinter as tk

from config      import load_config
from models      import SensorReading
from sensors     import SensorReader
from network     import NetworkManager
from storage     import DataStorage
from gui         import SparingGUI
import gap_filler
from sysmon      import SystemMonitor

log = logging.getLogger(__name__)


class SparingApp:
    """
    Orkestrator aplikasi SPARING Monitor.

    Thread model:
      main thread  → GUI (tkinter mainloop)
      thread sensor  → baca sensor setiap interval, kirim data saat batch penuh
      thread network → cek internet & ambil secret key setiap 30 detik

    Komunikasi thread → GUI melalui root.after(0, callback).
    Log dari thread dikirim lewat queue dan di-pump ke GUI tiap 150 ms.
    """

    def __init__(self) -> None:
        from datetime import datetime as _dt
        self.started_at = _dt.now()
        self.cfg        = load_config()
        self.sensor_rdr: Optional[SensorReader] = None
        self.net        = NetworkManager(self.cfg, on_log=self._log)
        # Server 1: dikirim setiap pembacaan (2 menit), buffer terpisah
        self.storage_s1 = DataStorage("data_buffer_s1.json")
        # Server 2: dikirim setiap batch penuh (30 data), buffer terpisah
        self.storage_s2 = DataStorage("data_buffer_s2.json")
        self.batch: List[SensorReading] = []
        self.last_tx    = 0.0
        self._running    = True
        self._gap_filled = False   # pastikan gap fill hanya jalan sekali
        self._q: queue.Queue = queue.Queue()
        self._sensor_wake = threading.Event()     # set() untuk mempersingkat sleep sensor loop
        self._last_r: Optional[SensorReading] = None  # reading terakhir untuk sinkronisasi sim
        self._last_r_lock = threading.Lock()
        self._op_mode = "normal"   # normal / stopped / calibrating / malfunction
        self.sysmon   = SystemMonitor()   # monitor resource untuk diagnosa mati

    def start(self) -> None:
        # Inisialisasi sensor reader (gagal graceful → pembacaan 0.0)
        try:
            self.sensor_rdr = SensorReader(self.cfg, on_error=self._log)
        except Exception as e:
            log.warning(f"SensorReader init gagal (pembacaan sensor akan 0.0): {e}")
            self.sensor_rdr = None

        # Bangun GUI
        self.root = tk.Tk()
        self.gui  = SparingGUI(self.root, self)

        # Tampilkan status RS485 setelah GUI selesai dirender
        self.root.after(500, self._post_init)

        # Background threads
        threading.Thread(target=self._sensor_loop,
                         daemon=True, name="sensor").start()
        threading.Thread(target=self._network_loop,
                         daemon=True, name="network").start()
        if self.cfg.get("sysmon_enabled", True):
            threading.Thread(target=self._sysmon_loop,
                             daemon=True, name="sysmon").start()

        # Pompa antrian log ke GUI
        self._pump_log()

        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        self.root.mainloop()

    # ── Post-init: status awal setelah GUI siap ────────────────────────────────
    def _post_init(self) -> None:
        ok   = bool(self.sensor_rdr and self.sensor_rdr._port_ok)
        port = self.cfg.get("serial_port", "—")
        self.gui.update_connection("rs485", ok)
        if ok:
            self.gui.log(f"USB RS485 terhubung pada {port}")
        else:
            self.gui.log(f"USB RS485 tidak terdeteksi — port: {port}")
            self.gui.log("→ Klik  ⌕ Scan Port  untuk mencari port USB RS485 Anda")

    # ── Log pump (main thread, via root.after) ─────────────────────────────────
    def _pump_log(self) -> None:
        while not self._q.empty():
            try:
                self.gui.log(self._q.get_nowait())
            except queue.Empty:
                break
        self.root.after(150, self._pump_log)

    def _log(self, msg: str) -> None:
        log.info(msg)
        self._q.put(msg)
        # Kirim ke server log secara async
        if self.cfg.get("log_url"):
            lvl = ("ERROR"   if "[ERROR]"   in msg else
                   "WARNING" if "[WARN]"    in msg else
                   "DEBUG"   if "[DEBUG]"   in msg else "INFO")
            threading.Thread(
                target=self.net.post_log,
                args=(msg, lvl),
                daemon=True,
                name="log_send",
            ).start()

    # ── Sensor loop (background thread) ───────────────────────────────────────
    def _sensor_loop(self) -> None:
        batch_size = self.cfg["data_batch_size"]
        interval   = self.cfg["interval_seconds"]
        time.sleep(2)   # beri waktu GUI load

        while self._running:
            try:
                r = self.sensor_rdr.read_all() if self.sensor_rdr else SensorReading(timestamp=time.time())
                gap_filler.save_state(r)   # simpan pembacaan terakhir untuk gap fill
                with self._last_r_lock:
                    self._last_r = r
                port_ok = bool(self.sensor_rdr and self.sensor_rdr._port_ok)

                self.root.after(0, self.gui.update_connection, "rs485", port_ok)

                self.batch.append(r)
                n        = len(self.batch)
                mode_tag = ""

                self._log(
                    f"{mode_tag}Data {n}/{batch_size} — "
                    f"pH={r.ph:.2f}  TSS={r.tss:.2f} mg/L  "
                    f"Debit={r.debit:.2f} m³/menit  "
                    f"COD={r.cod:.2f}  NH3-N={r.nh3n:.2f} mg/L"
                )
                self.root.after(0, self.gui.update_sensors, r)
                self.root.after(0, self.gui.update_count, n, batch_size)

                # Server 1: kualitas air (pH, TSS, Debit) — per 2 menit
                self._send_s1_water(r)

                # Server 2: kirim saat batch penuh (jika diaktifkan)
                if n >= batch_size:
                    if self.cfg.get("server2_enabled", True):
                        self._send_s2_batch()
                    else:
                        self._log("[S2] Pengiriman Server 2 dinonaktifkan — batch dibuang")
                    self.batch.clear()
                    self.root.after(0, self.gui.update_count, 0, batch_size)

            except Exception as e:
                self._log(f"[ERROR] sensor loop: {e}")
                self.root.after(0, self.gui.update_connection, "rs485", False)

            self._sensor_wake.wait(timeout=interval)
            self._sensor_wake.clear()

    # ── Network loop (background thread) ──────────────────────────────────────
    def _network_loop(self) -> None:
        time.sleep(3)
        while self._running:
            try:
                # 1. Cek koneksi internet
                internet_ok = self.net.check_internet()
                self.root.after(0, self.gui.update_connection, "internet", internet_ok)

                if internet_ok:
                    # 2. Ambil secret key — retry setiap 30 detik sampai berhasil
                    if not self.net.keys_fetched:
                        self._log("Mengambil secret key dari server...")
                        ok_keys = self.net.fetch_all_keys()
                        if ok_keys:
                            self._log("Secret key berhasil diperoleh")
                            # Gap fill hanya jalan setelah key NYATA tersedia
                            if not self._gap_filled:
                                self._gap_filled = True
                                threading.Thread(
                                    target=self._fill_gaps,
                                    kwargs={"auto": True},
                                    daemon=True, name="gap_fill_auto",
                                ).start()
                        else:
                            self._log("[WARN] Secret key belum diperoleh — retry 30 detik")

                    # 3. Cek keterjangkauan kedua server secara independen
                    s1_ok = self.net.check_server(self.cfg["secret_key_url1"])
                    s2_ok = self.net.check_server(self.cfg["secret_key_url2"])
                else:
                    # Tidak perlu cek server jika internet sudah mati
                    s1_ok = False
                    s2_ok = False

                self.root.after(0, self.gui.update_connection, "server1", s1_ok)
                self.root.after(0, self.gui.update_connection, "server2", s2_ok)

            except Exception as e:
                self._log(f"[ERROR] network loop: {e}")
            time.sleep(30)

    # ── Monitor resource sistem — diagnosa penyebab device mati ──────────────
    def _sysmon_loop(self) -> None:
        """
        Catat snapshot CPU/RAM/disk/suhu ke resource.log (di-fsync ke disk)
        tiap interval. Saat suhu/RAM/disk/undervoltage melewati ambang,
        kirim [WARN] ke log GUI + server. Baris terakhir resource.log
        menunjukkan kondisi device sesaat sebelum mati mendadak.
        """
        interval   = max(10, int(self.cfg.get("sysmon_interval_seconds", 60)))
        temp_warn  = self.cfg.get("sysmon_temp_warn",     75.0)
        temp_crit  = self.cfg.get("sysmon_temp_crit",     82.0)
        mem_warn   = self.cfg.get("sysmon_mem_warn_pct",  90.0)
        disk_warn  = self.cfg.get("sysmon_disk_warn_pct", 90.0)
        summary_n  = max(1, int(self.cfg.get("sysmon_summary_every", 10)))

        # Catat info startup sekali (penanda device baru menyala / habis reboot)
        first = self.sysmon.snapshot()
        self.sysmon.write_line("[BOOT] " + self.sysmon.format_line(first))
        self.root.after(0, self.gui.update_sysmon,
                        first.get("cpu_pct"), first.get("cpu_temp"),
                        first.get("mem_used_pct"), first.get("disk_used_pct"), "ok")
        up = first.get("uptime_s")
        if up is not None:
            self._log(f"[SYS] Monitor resource aktif — uptime {up // 60} menit, "
                      f"interval {interval}s → resource.log")

        count = 0
        while self._running:
            time.sleep(interval)
            try:
                snap = self.sysmon.snapshot()
                line = self.sysmon.format_line(snap)
                self.sysmon.write_line(line)   # selalu tulis (forensik) + fsync

                # ── Deteksi kondisi bahaya ────────────────────────────────────
                warns = []
                severity = "ok"
                temp = snap.get("cpu_temp")
                if temp is not None:
                    if temp >= temp_crit:
                        warns.append(f"SUHU KRITIS {temp}°C — risiko thermal shutdown")
                        severity = "crit"
                    elif temp >= temp_warn:
                        warns.append(f"suhu tinggi {temp}°C")
                        severity = "warn"
                mem = snap.get("mem_used_pct")
                if mem is not None and mem >= mem_warn:
                    warns.append(f"RAM {mem}% (sisa {snap.get('mem_avail_mb','?')}MB) — risiko OOM")
                    if severity != "crit": severity = "warn"
                disk = snap.get("disk_used_pct")
                if disk is not None and disk >= disk_warn:
                    warns.append(f"disk {disk}% (sisa {snap.get('disk_free_gb','?')}GB) — risiko gagal tulis")
                    if severity != "crit": severity = "warn"
                flags = snap.get("throttle_flags")
                if flags:
                    uv = [f for f in flags if "UNDERVOLTAGE" in f or "undervoltage" in f]
                    if uv:
                        warns.append("UNDERVOLTAGE — power supply/kabel lemah")
                        severity = "crit"

                self.root.after(0, self.gui.update_sysmon,
                                snap.get("cpu_pct"), temp, mem, disk, severity)

                if warns:
                    self._log("[WARN] [SYS] " + "  ·  ".join(warns))
                elif count % summary_n == 0:
                    # Ringkasan normal sesekali agar terlihat device sehat
                    self._log(
                        f"[SYS] CPU {snap.get('cpu_pct','?')}%  "
                        f"Suhu {snap.get('cpu_temp','?')}°C  "
                        f"RAM {snap.get('mem_used_pct','?')}%  "
                        f"Disk {snap.get('disk_used_pct','?')}%"
                    )
                count += 1
            except Exception as e:
                self._log(f"[ERROR] sysmon loop: {e}")

    # ── Kirim ke Server 1 — kualitas air, per 2 menit ────────────────────────
    def _send_s1_water(self, r: SensorReading) -> None:
        """
        Kirim data kualitas air (pH, TSS, Debit) ke Server 1 setiap 2 menit.
        Format JWT flat: uid, pH, tss, debit, cod, nh3n, datetime, tl.
        """
        int_on  = self.cfg.get("logger_internal", True)
        klhk_on = self.cfg.get("logger_klhk",     False)

        # Hitung nilai processed sekali untuk log KLHK
        proc_ph, proc_tss, proc_debit, *_ = self.net.get_processed(r)

        op = self._op_mode
        sc = {"stopped": -1, "calibrating": -2, "malfunction": -3}.get(op)
        jwts = []
        if sc is not None:
            if int_on:
                j = self.net.create_jwt1_water_status(sc, r.timestamp, processed=False)
                if j: jwts.append(("Internal", sc, sc, sc, j))
            if klhk_on:
                j = self.net.create_jwt1_water_status(sc, r.timestamp, processed=True)
                if j: jwts.append(("KLHK", sc, sc, sc, j))
        else:
            if int_on:
                j = self.net.create_jwt1_water(r, processed=False)
                if j: jwts.append(("Internal", r.ph, r.tss, r.debit, j))
            if klhk_on:
                j = self.net.create_jwt1_water(r, processed=True)
                if j: jwts.append(("KLHK", proc_ph, proc_tss, proc_debit, j))
        if not jwts:
            return

        online = self.net.check_internet()
        ok_any = False
        for tag, ph_v, tss_v, debit_v, jwt in jwts:
            if not online:
                self.storage_s1.save(jwt_s1=jwt)
                continue
            ok = self.net.post(self.cfg["server_url1"],
                               json.dumps({"token": jwt}))
            self.root.after(0, self.gui.update_connection, "server1", ok)
            if ok:
                ok_any = True
                self._log(f"✓ [S1-W/{tag}] pH={ph_v}  TSS={tss_v}  Debit={debit_v:.2f}")
            else:
                self._log(f"✗ [S1-W/{tag}] Gagal — disimpan ke buffer")
                self.storage_s1.save(jwt_s1=jwt)
        if ok_any:
            self.last_tx = r.timestamp
            self.root.after(0, self.gui.update_last_tx, self.last_tx)
        self.root.after(0, self.gui.update_buffer,
                        self.storage_s1.count() + self.storage_s2.count())

    # ── Kirim batch 30 data ────────────────────────────────────────────────────
    # ── Kirim ke Server 2 — setiap batch penuh (30 data × 2 menit = 60 menit) ─
    def _send_s2_batch(self) -> None:
        """
        Kirim batch 30 data ke Server 2 (data processed dengan filter min/max).
        Jika offline atau gagal, simpan ke buffer_s2.
        """
        batch  = list(self.batch)
        _sc    = {"stopped": -1, "calibrating": -2, "malfunction": -3}.get(self._op_mode)
        jwt2   = (self.net.create_jwt2_status(_sc, len(batch) or self.cfg["data_batch_size"])
                  if _sc is not None else self.net.create_jwt2(batch))
        now    = time.time()

        if not jwt2:
            self._log("[S2] JWT gagal — secret key belum ada, data dibuang")
            self.root.after(0, self.gui.update_send_offline, now)
            self.root.after(0, self.gui.update_buffer,
                            self.storage_s1.count() + self.storage_s2.count())
            return

        online = self.net.check_internet()
        if not online:
            self._log("[S2] Offline — batch disimpan ke buffer")
            self.storage_s2.save(jwt2=jwt2)
            self.root.after(0, self.gui.update_connection, "internet", False)
            self.root.after(0, self.gui.update_send_offline, now)
            self.root.after(0, self.gui.update_buffer,
                            self.storage_s1.count() + self.storage_s2.count())
            return

        # Kirim ulang buffer lama
        flushed = self.storage_s2.flush_s2(self.net)
        if flushed:
            self._log(f"[S2] {flushed} batch lama dari buffer berhasil dikirim ulang")

        ok2 = self.net.post(self.cfg["server_url2"],
                            json.dumps({"token": jwt2}))
        now = time.time()

        self.root.after(0, self.gui.update_connection, "server2", ok2)
        self.root.after(0, self.gui.update_send_status,
                        True, ok2, now)   # S1 selalu True di titik ini

        if ok2:
            self._log(f"✓ [S2] Batch {len(batch)} data berhasil dikirim ke Server 2")
        else:
            self._log(f"✗ [S2] Gagal — batch disimpan ke buffer")
            self.storage_s2.save(jwt2=jwt2)

        self.root.after(0, self.gui.update_buffer,
                        self.storage_s1.count() + self.storage_s2.count())

        # Perbarui secret key setelah setiap siklus kirim
        threading.Thread(target=self.net.fetch_all_keys, daemon=True).start()

    # ── Gap fill — isi slot kosong ke Server 1 ────────────────────────────────
    def _fill_gaps(self, auto: bool = False) -> None:
        """
        Deteksi dan kirim data gap ke Server 1.
        auto=True  → dipanggil otomatis saat startup (tidak update tombol GUI)
        auto=False → dipanggil dari tombol GUI
        """
        interval = self.cfg["interval_seconds"]
        slots    = gap_filler.detect_and_fill(interval)

        if not slots:
            msg = "[GAP] Tidak ada gap data yang perlu diisi"
            self._log(msg)
            if not auto:
                self.root.after(0, self.gui.gap_btn_reset)
            return

        gap_min = (slots[-1].timestamp - slots[0].timestamp + interval) / 60
        self._log(
            f"[GAP] Mengisi {len(slots)} slot "
            f"({gap_min:.0f} menit) → Server 1..."
        )

        online = self.net.check_internet()
        sent = saved = 0

        for i, r in enumerate(slots, 1):
            # ── Kualitas air ──────────────────────────────────────────────────
            jwt_w = self.net.create_jwt1_water(r)
            if jwt_w:
                if online and self.net.post(
                        self.cfg["server_url1"],
                        json.dumps({"token": jwt_w})):
                    sent += 1
                else:
                    self.storage_s1.save(jwt_s1=jwt_w)
                    saved += 1

            # Log setiap 10 slot
            if i % 10 == 0 or i == len(slots):
                self._log(f"[GAP] Progress {i}/{len(slots)} slot")

        self._log(
            f"[GAP] Selesai — {sent} terkirim langsung, "
            f"{saved} disimpan ke buffer"
        )
        self.root.after(0, self.gui.update_buffer,
                        self.storage_s1.count() + self.storage_s2.count())
        if not auto:
            self.root.after(0, self.gui.gap_btn_reset)

    def trigger_gap_fill(self) -> None:
        """Dipanggil dari tombol GUI — jalankan gap fill di background thread."""
        self.root.after(0, self.gui.gap_btn_busy)
        threading.Thread(
            target=self._fill_gaps,
            kwargs={"auto": False},
            daemon=True,
            name="gap_fill",
        ).start()

    def set_operation_mode(self, mode: str) -> None:
        """Set mode operasi sesuai SK 3441/2025 Pasal 6.2.6.6g.
        mode: 'normal' | 'stopped' (-1) | 'calibrating' (-2) | 'malfunction' (-3)
        """
        self._op_mode = mode
        _labels = {
            "normal":      "Normal — data sensor dikirim",
            "stopped":     "Produksi BERHENTI — mengirim kode -1",
            "calibrating": "KALIBRASI/AUDIT — mengirim kode -2",
            "malfunction": "GANGGUAN PERALATAN — mengirim kode -3",
        }
        self._log(f"[STATUS] Mode operasi: {_labels.get(mode, mode)}")
        self.root.after(0, self.gui.update_op_mode_btn, mode)

    def _quit(self) -> None:
        self._running = False
        if self.sensor_rdr:
            self.sensor_rdr.close()
        self.root.destroy()

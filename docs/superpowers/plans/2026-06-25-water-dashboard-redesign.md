# Water Dashboard Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the SPARING Monitor GUI with a water-only dashboard (Variant B layout from the design spec), adding COD & NH3-N parameters and removing air/noise/weather sensors and the PIN lock.

**Architecture:** Two-phase change. Phase 1–2 add COD/NH3-N and a device-info helper additively (app keeps running with the old GUI). Phase 3 rewrites `gui.py` water-only and rewires `app.py` to it. Phase 4 deletes the now-dead air/noise/weather code from the backend (sensors, network, config, models, gap_filler).

**Tech Stack:** Python 3, tkinter, pymodbus, PyJWT, requests, pytest (new, dev-only).

**Spec:** `docs/superpowers/specs/2026-06-25-water-dashboard-redesign-design.md`

**Dependency ordering note (read before starting):** The old `gui.update_sensors(r)` reads `r.pm25` etc., so `SensorReading` env fields cannot be removed until the new GUI is live. Likewise `app._noise_loop` calls `gui.update_noise_instant`, so the GUI rewrite and `app.py` env-loop removal must land together (Tasks 9–10) before any backend env deletion (Phase 4). Do not reorder phases.

---

## File Structure

- `models.py` — `SensorReading`: +`cod`,`nh3n`; later −env fields.
- `config.py` — `DEFAULT_CONFIG`: +COD/NH3-N keys; later −env keys.
- `sensors.py` — +`_read_cod`/`_read_nh3n`/`_sim_cod`/`_sim_nh3n`; later −env readers.
- `network.py` — payloads carry real `cod`/`nh3n`; `_apply_limits` filters 5 water params; later −env JWT methods.
- `app.py` — `_simulate`/`_sensor_loop` carry cod/nh3n; later −env loops & sends.
- `device_info.py` — **new**: `get_serial()`, `get_macs()`.
- `gui.py` — **rewritten**: water-only Variant B dashboard.
- `gap_filler.py` — `save_state`/`detect_and_fill`: −env fields, +cod/nh3n.
- `constants.py` — `C`: +card accent colors.
- `tests/` — **new**: pytest unit tests for the testable logic.

---

## Phase 0 — Test scaffold

### Task 0: Add pytest scaffold

**Files:**
- Create: `tests/__init__.py` (empty)
- Create: `requirements-dev.txt`

- [ ] **Step 1: Create dev requirements**

`requirements-dev.txt`:
```
pytest>=8.0.0
```

- [ ] **Step 2: Create empty package marker**

Create empty file `tests/__init__.py`.

- [ ] **Step 3: Install pytest**

Run: `python -m pip install -r requirements-dev.txt`
Expected: pytest installs successfully.

- [ ] **Step 4: Verify pytest runs**

Run: `python -m pytest -q`
Expected: "no tests ran" (exit code 5) — confirms pytest is wired.

- [ ] **Step 5: Commit**

```bash
git add tests/__init__.py requirements-dev.txt
git commit -m "test: add pytest scaffold"
```

---

## Phase 1 — Add COD & NH3-N (additive)

### Task 1: SensorReading gains cod & nh3n

**Files:**
- Modify: `models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`:
```python
from models import SensorReading


def test_reading_has_cod_and_nh3n_defaults():
    r = SensorReading()
    assert r.cod == 0.0
    assert r.nh3n == 0.0


def test_reading_accepts_cod_and_nh3n():
    r = SensorReading(cod=12.5, nh3n=1.3)
    assert r.cod == 12.5
    assert r.nh3n == 1.3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'cod'`.

- [ ] **Step 3: Add the fields**

In `models.py`, inside `SensorReading`, add after the `debit` field:
```python
    cod:        float = 0.0   # Chemical Oxygen Demand (mg/L)
    nh3n:       float = 0.0   # Amonia nitrogen NH3-N (mg/L)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add models.py tests/test_models.py
git commit -m "feat: add cod and nh3n fields to SensorReading"
```

### Task 2: Config defaults for COD & NH3-N

**Files:**
- Modify: `config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
from config import DEFAULT_CONFIG


def test_cod_nh3n_sensor_flags_present():
    assert DEFAULT_CONFIG["sensor_cod_enabled"] is True
    assert DEFAULT_CONFIG["sensor_nh3n_enabled"] is True


def test_cod_nh3n_modbus_and_sim_keys_present():
    for k in ("slave_id_cod", "reg_addr_cod", "reg_index_cod", "scale_cod",
              "float_cod", "offset_cod", "sim_cod_min", "sim_cod_max",
              "slave_id_nh3n", "reg_addr_nh3n", "reg_index_nh3n", "scale_nh3n",
              "float_nh3n", "offset_nh3n", "sim_nh3n_min", "sim_nh3n_max"):
        assert k in DEFAULT_CONFIG, f"missing {k}"


def test_cod_nh3n_limit_keys_present():
    for p in ("cod", "nh3n"):
        for s in ("min", "max", "float_lo_min", "float_lo_max",
                  "float_hi_min", "float_hi_max"):
            assert f"limit_{p}_{s}" in DEFAULT_CONFIG, f"missing limit_{p}_{s}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — KeyError / assertion on `sensor_cod_enabled`.

- [ ] **Step 3: Add the config keys**

In `config.py` `DEFAULT_CONFIG`, add near the existing `slave_id_*` block:
```python
    "slave_id_cod":           7,
    "slave_id_nh3n":          8,
    # Pembacaan Modbus generik: nilai = reg[reg_index] / scale + offset
    "reg_addr_cod":           0,
    "reg_count_cod":          2,
    "reg_index_cod":          1,
    "scale_cod":              100.0,
    "reg_addr_nh3n":          0,
    "reg_count_nh3n":         2,
    "reg_index_nh3n":         1,
    "scale_nh3n":             100.0,
```
Add to the `sensor_*_enabled` block:
```python
    "sensor_cod_enabled":     True,
    "sensor_nh3n_enabled":    True,
```
Add to the `float_*` block:
```python
    "float_cod":              False,
    "float_nh3n":             False,
```
Add to the `offset_*` block:
```python
    "offset_cod":             0.0,
    "offset_nh3n":            0.0,
```
Add to the `sim_*` block:
```python
    "sim_cod_min":            10.0,
    "sim_cod_max":            30.0,
    "sim_nh3n_min":           0.5,
    "sim_nh3n_max":           2.0,
```
Add to the `limit_*` block:
```python
    "limit_cod_min":             0.0,
    "limit_cod_max":             1000.0,   # mg/L
    "limit_cod_float_lo_min":    1.0,
    "limit_cod_float_lo_max":    5.0,
    "limit_cod_float_hi_min":    995.0,
    "limit_cod_float_hi_max":    999.0,
    "limit_nh3n_min":            0.0,
    "limit_nh3n_max":            100.0,    # mg/L
    "limit_nh3n_float_lo_min":   0.1,
    "limit_nh3n_float_lo_max":   0.5,
    "limit_nh3n_float_hi_min":   99.0,
    "limit_nh3n_float_hi_max":   99.5,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: add COD and NH3-N config defaults"
```

### Task 3: Sensor reading for COD & NH3-N

**Files:**
- Modify: `sensors.py`
- Test: `tests/test_sensors.py`

- [ ] **Step 1: Write the failing test**

`tests/test_sensors.py`:
```python
from config import DEFAULT_CONFIG
from sensors import SensorReader


def _floating_reader():
    cfg = {**DEFAULT_CONFIG, "simulate_sensors": True}
    return SensorReader(cfg), cfg


def test_sim_cod_in_range():
    rdr, cfg = _floating_reader()
    for _ in range(20):
        v = rdr._sim_cod()
        assert cfg["sim_cod_min"] <= v <= cfg["sim_cod_max"]


def test_sim_nh3n_in_range():
    rdr, cfg = _floating_reader()
    for _ in range(20):
        v = rdr._sim_nh3n()
        assert cfg["sim_nh3n_min"] <= v <= cfg["sim_nh3n_max"]


def test_read_all_populates_cod_and_nh3n_when_floating():
    rdr, cfg = _floating_reader()
    reading = rdr.read_all()
    assert reading.cod > 0
    assert reading.nh3n > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sensors.py -v`
Expected: FAIL — `AttributeError: 'SensorReader' object has no attribute '_sim_cod'`.

- [ ] **Step 3: Implement readers + sim + read_all wiring**

In `sensors.py`, add sim helpers next to `_sim_debit`:
```python
    def _sim_cod(self) -> float:
        c = self.cfg
        return round(random.uniform(c.get("sim_cod_min", 10.0),
                                    c.get("sim_cod_max", 30.0)), 2)

    def _sim_nh3n(self) -> float:
        c = self.cfg
        return round(random.uniform(c.get("sim_nh3n_min", 0.5),
                                    c.get("sim_nh3n_max", 2.0)), 2)
```
Add a generic scaled reader + cod/nh3n readers next to `_read_debit`:
```python
    def _read_scaled(self, sensor: str, slave_key: str, addr_key: str,
                     count_key: str, index_key: str, scale_key: str,
                     offset_key: str, sim_fn) -> float:
        """Pembacaan Modbus generik: nilai = reg[index] / scale + offset."""
        if self._is_float(sensor) or self._mb is None:
            return sim_fn()
        try:
            addr  = self.cfg[addr_key]
            count = self.cfg[count_key]
            r = self._rhr(addr, count, self.cfg[slave_key])
            if not r.isError():
                idx = self.cfg[index_key]
                val = r.registers[idx] / self.cfg[scale_key]
                return round(val + self.cfg.get(offset_key, 0.0), 3)
            msg = f"[SENSOR] {sensor} isError: {r}"
            log.error(msg); self._on_error(msg)
        except Exception as e:
            log.error(f"Baca {sensor} gagal: {e}")
            self._on_error(f"[SENSOR] Baca {sensor} gagal: {e}")
        return 0.0

    def _read_cod(self) -> float:
        return self._read_scaled(
            "cod", "slave_id_cod", "reg_addr_cod", "reg_count_cod",
            "reg_index_cod", "scale_cod", "offset_cod", self._sim_cod)

    def _read_nh3n(self) -> float:
        return self._read_scaled(
            "nh3n", "slave_id_nh3n", "reg_addr_nh3n", "reg_count_nh3n",
            "reg_index_nh3n", "scale_nh3n", "offset_nh3n", self._sim_nh3n)
```
In `read_all()`, add inside the `with self._lock:` block after the debit read:
```python
            if self.cfg.get("sensor_cod_enabled", True):
                reading.cod   = self._read_cod()
                time.sleep(0.1)
            if self.cfg.get("sensor_nh3n_enabled", True):
                reading.nh3n  = self._read_nh3n()
                time.sleep(0.1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_sensors.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add sensors.py tests/test_sensors.py
git commit -m "feat: read COD and NH3-N via configurable Modbus"
```

### Task 4: Network payload & limits carry cod/nh3n

**Files:**
- Modify: `network.py:144-161` (`_apply_limits`), `network.py:163-195` (`_build_row`), `network.py:245-288` (`create_jwt1_water`), `network.py:457-459` (`get_processed`)
- Test: `tests/test_network.py`

- [ ] **Step 1: Write the failing test**

`tests/test_network.py`:
```python
import jwt
from config import DEFAULT_CONFIG
from models import SensorReading
from network import NetworkManager


def _net():
    cfg = {**DEFAULT_CONFIG}
    n = NetworkManager(cfg, on_log=lambda m: None)
    n.secret_key1 = "testkey1"
    n.secret_key2 = "testkey2"
    return n, cfg


def test_water_jwt_includes_cod_and_nh3n():
    n, _ = _net()
    r = SensorReading(ph=7.0, tss=50.0, debit=1.2, cod=18.0, nh3n=1.1)
    token = n.create_jwt1_water(r, processed=False)
    payload = jwt.decode(token, "testkey1", algorithms=["HS256"])
    assert payload["cod"] == 18.0
    assert payload["nh3n"] == 1.1


def test_apply_limits_returns_five_water_values():
    n, _ = _net()
    out = n._apply_limits(7.0, 50.0, 1.2, 18.0, 1.1)
    assert len(out) == 5


def test_apply_limits_caps_cod_below_min():
    n, cfg = _net()
    cfg["limit_cod_min"] = 5.0
    cfg["limit_cod_float_lo_min"] = 5.0
    cfg["limit_cod_float_lo_max"] = 6.0
    _, _, _, cod_out, _ = n._apply_limits(7.0, 50.0, 1.2, 1.0, 1.1)
    assert 5.0 <= cod_out <= 6.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_network.py -v`
Expected: FAIL — `test_water_jwt_includes_cod_and_nh3n` sees `cod == 0`.

- [ ] **Step 3: Update network methods**

Replace `_apply_limits` (lines 144-161) with:
```python
    def _apply_limits(self, ph: float, tss: float, debit: float,
                      cod: float = 0.0, nh3n: float = 0.0):
        """Terapkan batas min/max fluktuatif ke 5 parameter air."""
        c = self.cfg
        def _f(key): return (
            c.get(f"limit_{key}_min"),   c.get(f"limit_{key}_max"),
            c.get(f"limit_{key}_float_lo_min"), c.get(f"limit_{key}_float_lo_max"),
            c.get(f"limit_{key}_float_hi_min"), c.get(f"limit_{key}_float_hi_max"),
        )
        return (
            self._cap_fluctuate(ph,    *_f("ph")),
            self._cap_fluctuate(tss,   *_f("tss")),
            self._cap_fluctuate(debit, *_f("debit")),
            self._cap_fluctuate(cod,   *_f("cod")),
            self._cap_fluctuate(nh3n,  *_f("nh3n")),
        )
```
In `_build_row` (lines 163-195), change the unpack + cod/nh3n. Replace the `if processed:` block and the `row` cod/nh3n init so it reads:
```python
        row: dict = {"datetime": int(r.timestamp)}
        cfg = self.cfg

        if processed:
            ph, tss, debit, cod, nh3n = self._apply_limits(
                r.ph, r.tss, r.debit, r.cod, r.nh3n)
        else:
            ph, tss, debit, cod, nh3n = r.ph, r.tss, r.debit, r.cod, r.nh3n

        row["cod"]  = round(cod,  2) if cfg.get("sensor_cod_enabled",  True) else 0
        row["nh3n"] = round(nh3n, 2) if cfg.get("sensor_nh3n_enabled", True) else 0
```
(Leave the existing `if cfg.get("sensor_ph_enabled"...)` lines below; **remove** the later `if include_env:` PM/noise block in Phase 4, not now — for now it still references `pm25` etc. which still exist on the model.)

In `create_jwt1_water` (lines 264-283), change the processed/raw unpack and payload:
```python
        if processed:
            ph_v, tss_v, debit_v, cod_v, nh3n_v = self._apply_limits(
                r.ph, r.tss, r.debit, r.cod, r.nh3n)
            uid = cfg.get("uid1_klhk") or cfg["uid1"]
        else:
            ph_v, tss_v, debit_v, cod_v, nh3n_v = \
                r.ph, r.tss, r.debit, r.cod, r.nh3n
            uid = cfg["uid1"]

        tl = cfg.get("tl_klhk", 2) if processed else cfg.get("tl_water", 1)
        payload: dict = {
            "uid":      uid,
            "cod":      round(cod_v,  2) if cfg.get("sensor_cod_enabled",  True) else 0,
            "nh3n":     round(nh3n_v, 2) if cfg.get("sensor_nh3n_enabled", True) else 0,
            "datetime": int(r.timestamp),
            "tl":       tl,
        }
```
Replace `get_processed` (lines 457-459) with:
```python
    def get_processed(self, r: SensorReading) -> tuple:
        """Kembalikan (ph, tss, debit, cod, nh3n) setelah filter batas."""
        return self._apply_limits(r.ph, r.tss, r.debit, r.cod, r.nh3n)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_network.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add network.py tests/test_network.py
git commit -m "feat: include cod and nh3n in server payload and limits"
```

### Task 5: App simulate & log carry cod/nh3n

**Files:**
- Modify: `app.py:670-701` (`_simulate`), `app.py:168-178` (sensor-loop log line)

- [ ] **Step 1: Add cod/nh3n to _simulate**

In `app.py` `_simulate()`, add to the `SensorReading(...)` constructor:
```python
            cod        = round(random.uniform(c.get("sim_cod_min",  10.0),
                                              c.get("sim_cod_max",  30.0)), 2),
            nh3n       = round(random.uniform(c.get("sim_nh3n_min", 0.5),
                                              c.get("sim_nh3n_max", 2.0)), 2),
```

- [ ] **Step 2: Add cod/nh3n to the sensor-loop log line**

In `_sensor_loop`, in the `self._log(...)` water line (around line 172), extend the format string with:
```python
                    f"COD={r.cod:.2f}  NH3-N={r.nh3n:.2f} mg/L  "
```
(insert right after the `Debit=...` segment).

- [ ] **Step 3: Smoke-run (floating)**

Run: `python -c "from app import SparingApp; a=SparingApp(); print(a._simulate().cod, a._simulate().nh3n)"`
Expected: prints two positive numbers (no exception).

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: simulate and log cod and nh3n readings"
```

**Checkpoint:** App still runs with the OLD GUI; COD/NH3-N now flow to the servers.

---

## Phase 2 — Device info helper

### Task 6: device_info.py

**Files:**
- Create: `device_info.py`
- Test: `tests/test_device_info.py`

- [ ] **Step 1: Write the failing test**

`tests/test_device_info.py`:
```python
import device_info


def test_get_serial_returns_nonempty_string():
    s = device_info.get_serial()
    assert isinstance(s, str)
    assert s != ""


def test_get_macs_returns_eth_and_wlan_keys():
    macs = device_info.get_macs()
    assert "eth0" in macs
    assert "wlan0" in macs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_device_info.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'device_info'`.

- [ ] **Step 3: Implement device_info.py**

`device_info.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_device_info.py -v`
Expected: PASS (2 passed) — on Windows, serial falls back to `"—"`... **note:** the first test asserts non-empty; `"—"` is non-empty so it passes.

- [ ] **Step 5: Commit**

```bash
git add device_info.py tests/test_device_info.py
git commit -m "feat: add device serial and MAC helper"
```

---

## Phase 3 — GUI rewrite (water-only, Variant B) + app rewiring

> Build the new `gui.py` across Tasks 7–9 **without running the app**, then rewire `app.py` in Task 10 and run. The new `SparingGUI` keeps these public methods that `app.py` calls: `log`, `update_connection`, `update_sensors`, `update_count`, `update_last_tx`, `update_buffer`, `update_send_status`, `update_send_offline`, `update_sysmon`, `update_op_mode_btn`, `update_test_mode_btn`, `gap_btn_busy`, `gap_btn_reset`. It does **not** expose `update_sensors_processed`, `update_dust_processed`, `update_noise_processed`, `update_noise_instant`, `update_weather` (removed).

### Task 7: New gui.py — window, helpers, header, footer, clock

**Files:**
- Modify: `gui.py` (replace whole file across Tasks 7–9)
- Modify: `constants.py` (add card colors)

- [ ] **Step 1: Add card accent colors to constants**

In `constants.py` `C` dict, add:
```python
    "s_suhu":       "#E65100",   # Suhu air — orange
    "s_cod":        "#6A1B9A",   # COD — purple
    "s_nh3n":       "#00838F",   # NH3-N — cyan
```

- [ ] **Step 2: Carry over proven helpers verbatim**

From the existing `gui.py`, copy these methods **unchanged** into the new class: `_calc_scale`, `_fs`, `_sp`, `_setup_window`, `_toggle_fullscreen`, `_exit_fullscreen`, `_setup_styles`, `_make_dialog`, `_rounded_canvas`, `_card`, `_info_row`, `_flat_btn`, `_tick_clock`, and the connection-update logic `update_connection` (and its `_conn_dots`/`_conn_chips` maps). Keep the module constants `_FONT_UI`, `_FONT_MONO`, `_REF_W`, `_REF_H`.

- [ ] **Step 3: Write the new `__init__` and `_build`**

```python
    def __init__(self, root, app):
        self.root = root
        self.app  = app
        self.cfg  = app.cfg
        self._sensor_vars: dict = {}     # key -> StringVar (raw value)
        self._conn_dots:  dict = {}
        self._conn_chips: dict = {}
        self._conn_labels: dict = {}
        self._sensor_cards: dict = {}    # cfg_key -> canvas
        self._op_btn_refs: dict = {}
        self._test_mode_btn = None       # no floating button in this layout
        self._test_mode_var = None
        self._setup_window()
        self._calc_scale()
        self._setup_styles()
        self._build()
        self._tick_clock()

    def _build(self):
        self._build_header()
        self._build_footer()             # side="bottom" before content
        self._content = tk.Frame(self.root, bg=C["bg"])
        self._content.pack(fill="both", expand=True)
        body = tk.Frame(self._content, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=self._sp(12), pady=self._sp(8))
        self._left = tk.Frame(body, bg=C["bg"])
        self._left.pack(side="left", fill="both", expand=True, padx=(0, self._sp(8)))
        self._build_sensor_grid(self._left)
        self._build_log_panel(self._left)
        self._build_sidebar(body)
        self.root.after(100, self.apply_sensor_visibility)
```

- [ ] **Step 4: Header (logo + title + connection chips)**

Reuse the existing `_build_header`/`_add_logo` from the old file but keep **only** the four connection chips `("rs485","RS485"), ("internet","Internet"), ("server1","Internal"), ("server2","KLHK")`. Remove the clock from the header (clock now lives in the sidebar). Keep `_app_title_var` set to a static `"SISTEM PEMANTAUAN KUALITAS AIR"`.

- [ ] **Step 5: Footer (sysmon + buttons)**

Reuse the old `_build_footer` but **remove** the op-mode buttons block (those move to the sidebar in Task 9). Keep: left status echo, sysmon resource label (`_sys_var`/`_sys_lbl`), and right-side buttons `⛶ F11` (`_toggle_fullscreen`), `⚙ Sensor` (`_open_sensor_select`), `⚙ Pengaturan` (`_open_settings`). Keep `_statusbar_var`.

- [ ] **Step 6: Verify import (no run yet)**

Run: `python -c "import ast; ast.parse(open('gui.py').read()); print('parse ok')"`
Expected: `parse ok`.

- [ ] **Step 7: Commit**

```bash
git add gui.py constants.py
git commit -m "feat: new gui scaffold - header, footer, helpers"
```

### Task 8: Sensor grid (6 water cards + reflow + update_sensors)

**Files:**
- Modify: `gui.py`

- [ ] **Step 1: Build the grid**

```python
    # (cfg_key, sensor_key, label, unit, color)
    _WATER_DEFS = [
        ("sensor_temp_enabled",  "temp",  "SUHU",  "°C",       "s_suhu"),
        ("sensor_ph_enabled",    "ph",    "pH",    "",         "s_ph"),
        ("sensor_cod_enabled",   "cod",   "COD",   "mg/L",     "s_cod"),
        ("sensor_tss_enabled",   "tss",   "TSS",   "mg/L",     "s_tss"),
        ("sensor_nh3n_enabled",  "nh3n",  "NH3-N", "mg/L",     "s_nh3n"),
        ("sensor_debit_enabled", "debit", "DEBIT", "m³/menit", "s_debit"),
    ]

    def _build_sensor_grid(self, parent):
        self._grid = tk.Frame(parent, bg=C["bg"])
        self._grid.pack(fill="both", expand=True)
        for cfg_key, key, label, unit, color in self._WATER_DEFS:
            self._sensor_cards[cfg_key] = self._water_card(key, label, unit, C[color])

    def _water_card(self, key, label, unit, accent):
        canvas, inner = self._rounded_canvas(self._grid, C["card"],
                                             radius=self._sp(14))
        tk.Frame(inner, bg=accent, height=self._sp(3)).pack(fill="x")
        pad = tk.Frame(inner, bg=C["card"])
        pad.pack(fill="both", expand=True, padx=self._sp(12), pady=self._sp(8))
        tk.Label(pad, text=label, bg=C["card"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(10), "bold")).pack(anchor="w")
        var = tk.StringVar(value="0.00")
        self._sensor_vars[key] = var
        tk.Label(pad, textvariable=var, bg=C["card"], fg=accent,
                 font=(_FONT_MONO, self._fs(30), "bold")).pack(anchor="w")
        tk.Label(pad, text=unit or " ", bg=C["card"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(9))).pack(anchor="w")
        return canvas
```

- [ ] **Step 2: Reflow (2-column grid, only enabled cards)**

```python
    def apply_sensor_visibility(self):
        for card in self._sensor_cards.values():
            card.grid_forget()
        self._grid.columnconfigure(0, weight=1, uniform="c")
        self._grid.columnconfigure(1, weight=1, uniform="c")
        slot = 0
        for cfg_key, key, *_ in self._WATER_DEFS:
            if self.cfg.get(cfg_key, True):
                rr, cc = divmod(slot, 2)
                self._sensor_cards[cfg_key].grid(
                    row=rr, column=cc, sticky="nsew",
                    padx=self._sp(5), pady=self._sp(5))
                self._grid.rowconfigure(rr, weight=1)
                slot += 1
```

- [ ] **Step 3: update_sensors**

```python
    def update_sensors(self, r):
        fmt = {"ph": "{:.2f}", "tss": "{:.1f}", "debit": "{:.3f}",
               "cod": "{:.2f}", "nh3n": "{:.2f}", "temp": "{:.1f}"}
        for key, f in fmt.items():
            if key in self._sensor_vars:
                self._sensor_vars[key].set(f.format(getattr(r, key)))
```

- [ ] **Step 4: Verify parse**

Run: `python -c "import ast; ast.parse(open('gui.py').read()); print('parse ok')"`
Expected: `parse ok`.

- [ ] **Step 5: Commit**

```bash
git add gui.py
git commit -m "feat: water sensor grid with reflow and value updates"
```

### Task 9: Sidebar — clock, device info, mode regulasi, logger toggles, status

**Files:**
- Modify: `gui.py`

- [ ] **Step 1: Build sidebar container + clock + device info**

```python
    def _build_sidebar(self, parent):
        from device_info import get_serial, get_macs
        outer = tk.Frame(parent, bg=C["bg"], width=self._sp(280))
        outer.pack(side="right", fill="y")
        outer.pack_propagate(False)
        _, side = self._rounded_canvas(outer, C["card"], radius=self._sp(14),
                                       fill="both", expand=True)
        inner = tk.Frame(side, bg=C["card"])
        inner.pack(fill="both", expand=True, padx=self._sp(12), pady=self._sp(10))

        self._date_var  = tk.StringVar()
        self._clock_var = tk.StringVar()
        tk.Label(inner, textvariable=self._date_var, bg=C["card"],
                 fg=C["text_muted"], font=(_FONT_UI, self._fs(9))).pack(anchor="w")
        tk.Label(inner, textvariable=self._clock_var, bg=C["card"], fg=C["text"],
                 font=(_FONT_MONO, self._fs(22), "bold")).pack(anchor="w")

        macs = get_macs()
        started = getattr(self.app, "started_at", None)
        started_s = started.strftime("%Y-%m-%d %H:%M") if started else "—"
        self._last_rx_var = tk.StringVar(value="—")
        for lbl, val in [
            ("Started At", started_s),
            ("Serial",     get_serial()),
            ("eth0",       macs["eth0"]),
            ("wlan0",      macs["wlan0"]),
        ]:
            self._meta_row(inner, lbl, val)
        self._meta_row(inner, "Last Rx", self._last_rx_var)

        self._build_mode_section(inner)
        self._build_logger_section(inner)
        self._build_status_section(inner)

    def _meta_row(self, parent, label, value):
        row = tk.Frame(parent, bg=C["card"]); row.pack(fill="x", pady=1)
        tk.Label(row, text=label + ":", bg=C["card"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(7))).pack(side="left")
        kw = {"textvariable": value} if isinstance(value, tk.StringVar) else {"text": value}
        tk.Label(row, bg=C["card"], fg=C["text"],
                 font=(_FONT_MONO, self._fs(7), "bold"), **kw).pack(side="right")
```

- [ ] **Step 2: Mode Regulasi section (moved from footer)**

```python
    _MODE_DEFS = [
        ("normal",      "Normal",                C["primary"]),
        ("stopped",     "−1 Stop Sementara",     "#C62828"),
        ("calibrating", "−2 Kalibrasi/Audit",    "#E65100"),
        ("malfunction", "−3 Tidak Optimal/Rusak","#6A1B9A"),
    ]

    def _build_mode_section(self, parent):
        tk.Label(parent, text="MODE REGULASI", bg=C["card"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(8), "bold")).pack(anchor="w", pady=(self._sp(8), 2))
        cur = getattr(self.app, "_op_mode", "normal")
        for mode, label, bg in self._MODE_DEFS:
            active = (cur == mode)
            btn = tk.Button(parent, text=label,
                            command=lambda m=mode: self.app.set_operation_mode(m),
                            bg=bg if active else C["bg"],
                            fg="white" if active else C["text_muted"],
                            font=(_FONT_UI, self._fs(8), "bold"), relief="flat",
                            cursor="hand2", anchor="w", padx=self._sp(8),
                            pady=self._sp(4))
            btn.pack(fill="x", pady=1)
            self._op_btn_refs[mode] = (bg, btn)
        self._mode_now_var = tk.StringVar(value=f"Mode saat ini: {cur}")
        tk.Label(parent, textvariable=self._mode_now_var, bg=C["card"],
                 fg=C["text_muted"], font=(_FONT_UI, self._fs(7))).pack(anchor="w")

    def update_op_mode_btn(self, mode):
        for m, (bg, btn) in self._op_btn_refs.items():
            active = (m == mode)
            btn.configure(bg=bg if active else C["bg"],
                          fg="white" if active else C["text_muted"])
        if hasattr(self, "_mode_now_var"):
            self._mode_now_var.set(f"Mode saat ini: {mode}")
```

- [ ] **Step 3: Logger toggles (Internal / KLHK)**

```python
    def _build_logger_section(self, parent):
        tk.Label(parent, text="LOGGER", bg=C["card"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(8), "bold")).pack(anchor="w", pady=(self._sp(8), 2))
        row = tk.Frame(parent, bg=C["card"]); row.pack(fill="x")
        for cfg_key, label in [("logger_internal", "Internal"), ("logger_klhk", "KLHK")]:
            var = tk.BooleanVar(value=self.cfg.get(cfg_key, False))
            def _toggle(k=cfg_key, v=var):
                self.cfg[k] = v.get(); save_config(self.cfg)
                self.log(f"Logger {k} = {v.get()}")
            tk.Checkbutton(row, text=label, variable=var, command=_toggle,
                           bg=C["card"], fg=C["text"], activebackground=C["card"],
                           font=(_FONT_UI, self._fs(8)), selectcolor=C["card_alt"]
                           ).pack(side="left", padx=(0, self._sp(10)))
```

- [ ] **Step 4: Status pengiriman section + update methods**

```python
    def _build_status_section(self, parent):
        tk.Label(parent, text="STATUS PENGIRIMAN", bg=C["card"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(8), "bold")).pack(anchor="w", pady=(self._sp(8), 2))
        self._s1_status_var = tk.StringVar(value="Internal (Live): menunggu")
        self._s2_status_var = tk.StringVar(value="KLHK (Hourly): menunggu")
        for var in (self._s1_status_var, self._s2_status_var):
            tk.Label(parent, textvariable=var, bg=C["card"], fg=C["text_muted"],
                     font=(_FONT_UI, self._fs(8))).pack(anchor="w")

    def update_send_status(self, s1_ok, s2_ok, ts):
        from datetime import datetime
        t = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
        self._s2_status_var.set(f"KLHK (Hourly): {'OK' if s2_ok else 'gagal'} {t}")

    def update_send_offline(self, ts):
        from datetime import datetime
        t = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
        self._s2_status_var.set(f"KLHK (Hourly): offline {t}")

    def update_last_tx(self, ts):
        from datetime import datetime
        t = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        self._last_rx_var.set(t)
        self._s1_status_var.set("Internal (Live): OK " +
                                datetime.fromtimestamp(ts).strftime("%H:%M:%S"))

    def update_count(self, n, total):
        if hasattr(self, "_statusbar_var"):
            self._statusbar_var.set(f"Data terkumpul: {n}/{total}")

    def update_buffer(self, n):
        pass
```

- [ ] **Step 5: Update the clock tick to also set the sidebar date/clock**

Ensure `_tick_clock` sets both `_clock_var` and `_date_var` (carry the old body — it already does).

- [ ] **Step 6: Verify parse**

Run: `python -c "import ast; ast.parse(open('gui.py').read()); print('parse ok')"`
Expected: `parse ok`.

- [ ] **Step 7: Commit**

```bash
git add gui.py
git commit -m "feat: sidebar with device info, mode, logger toggles, status"
```

### Task 10: Log panel, dialogs, app rewiring, first run

**Files:**
- Modify: `gui.py` (log panel + dialogs), `app.py` (rewire + started_at + remove env GUI calls)

- [ ] **Step 1: Log panel + Data OK indicator + `log()`**

```python
    def _build_log_panel(self, parent):
        _, outer = self._rounded_canvas(parent, C["card"], radius=self._sp(12),
                                        fill="x", pady=(self._sp(8), 0))
        bar = tk.Frame(outer, bg=C["card"]); bar.pack(fill="x")
        tk.Label(bar, text="LOG PENGIRIMAN", bg=C["card"], fg=C["accent"],
                 font=(_FONT_UI, self._fs(8), "bold"),
                 padx=self._sp(10), pady=self._sp(5)).pack(side="left")
        self._data_ok = tk.Label(bar, text="● Data OK", bg=C["card"],
                                  fg=C["online"], font=(_FONT_UI, self._fs(8), "bold"))
        self._data_ok.pack(side="right", padx=self._sp(8))
        frame = tk.Frame(outer, bg=C["log_bg"]); frame.pack(fill="both")
        sb = ttk.Scrollbar(frame, orient="vertical")
        self._log_txt = tk.Text(frame, state="disabled", height=self._sp(6),
                                font=(_FONT_MONO, self._fs(8)), bg=C["log_bg"],
                                fg=C["log_fg"], relief="flat", padx=10, pady=8,
                                wrap="word", yscrollcommand=sb.set)
        sb.configure(command=self._log_txt.yview)
        sb.pack(side="right", fill="y"); self._log_txt.pack(side="left", fill="both", expand=True)

    def log(self, msg):
        from datetime import datetime
        line = f"[{datetime.now():%H:%M:%S}] {msg}\n"
        self._log_txt.configure(state="normal")
        self._log_txt.insert("end", line)
        self._log_txt.see("end")
        self._log_txt.configure(state="disabled")
        if hasattr(self, "_statusbar_var"):
            self._statusbar_var.set(msg[:80])
```

- [ ] **Step 2: Carry over dialogs + sysmon + safe stubs**

Copy from the old `gui.py` the dialog methods `_open_settings`, `_scan_ports_dialog`, `_reconnect_rs485`, `_open_float_select`, `_open_sensor_select`. **Do not** carry `_show_lock_dialog`, `_unlock`, `_lock`, `_build_locked_*`, gap-fill button code, or the floating-toggle button — those have no widget in this layout.

Ensure `_open_settings` exposes buttons for **Scan Port** (`self._scan_ports_dialog`) and **Hubungkan Ulang** (`self._reconnect_rs485`) so RS485 reconnect/scan stay reachable (the old code put these in the unlocked panel; move them into the settings dialog).

Add `update_sysmon` carried from the old file but **guarded**:
```python
    def update_sysmon(self, cpu, temp, mem, disk, severity):
        if not hasattr(self, "_sys_var"):
            return
        if self._small:
            self._sys_var.set(f"{temp}°C · {mem}% · {disk}%")
        else:
            self._sys_var.set(f"CPU {cpu} · {temp}°C · RAM {mem} · Disk {disk}")
```
Add safe stubs for methods `app.py` still calls but which have no widget here:
```python
    def update_test_mode_btn(self, is_test):
        pass

    def gap_btn_busy(self):
        pass

    def gap_btn_reset(self):
        pass
```
In `_open_float_select` and `_open_sensor_select`, change the `sensors` list to the 6 water params:
```python
        sensors = [
            ("sensor_temp_enabled",  "Suhu Air (°C)",     C["s_suhu"], "#FFCC80"),
            ("sensor_ph_enabled",    "pH",                C["s_ph"],   "#A8CCFF"),
            ("sensor_cod_enabled",   "COD (mg/L)",        C["s_cod"],  "#CE93D8"),
            ("sensor_tss_enabled",   "TSS (mg/L)",        C["s_tss"],  "#A0D8F0"),
            ("sensor_nh3n_enabled",  "NH3-N (mg/L)",      C["s_nh3n"], "#80DEEA"),
            ("sensor_debit_enabled", "Debit (m³/menit)",  C["s_debit"],"#9AECD8"),
        ]
```
(For float select, change the cfg keys to `float_temp/ph/cod/tss/nh3n/debit`.) Ensure `_open_sensor_select._apply` calls `self.apply_sensor_visibility()`.

- [ ] **Step 3: app.py — capture started_at + remove env GUI update calls**

In `app.py` `__init__`, add:
```python
        from datetime import datetime as _dt
        self.started_at = _dt.now()
```
In `_sensor_loop`, **delete** these lines (env/processed GUI updates):
```python
                self.root.after(0, self.gui.update_sensors_processed, proc_ph, proc_tss, proc_debit)
                self.root.after(0, self.gui.update_dust_processed, proc_pm25, proc_pm10, proc_pm100)
                self.root.after(0, self.gui.update_noise_processed, proc_noise)
```
and the `proc_* = self.net.get_processed(r)` unpack line above them. Keep `self.root.after(0, self.gui.update_sensors, r)` and `update_count`.

- [ ] **Step 4: Run the app (floating mode)**

Run: `python main.py`
Expected: New dashboard opens fullscreen — top header with logo + 4 connection chips; left = 6 water cards (Suhu, pH, COD, TSS, NH3-N, Debit) updating every 2 s; log panel filling; right sidebar with clock, device info (serial/MAC fallback on Windows), mode buttons, Internal/KLHK checkboxes, status. Press `Esc` to exit fullscreen, close window. No tracebacks in console.

- [ ] **Step 5: Manual checks**

- Click `⚙ Sensor`, uncheck COD + NH3-N, Apply → grid reflows to 4 cards, no gaps.
- Click each Mode Regulasi button → active button highlights, "Mode saat ini" updates, log line appears.
- Toggle Internal/KLHK → `config.json` updates (check file).

- [ ] **Step 6: Commit**

```bash
git add gui.py app.py
git commit -m "feat: log panel, water dialogs, app rewiring to new gui"
```

**Checkpoint:** New water dashboard fully runs. Backend still has dead env code (removed next).

---

## Phase 4 — Remove air/noise/weather backend

### Task 11: Remove env loops & sends from app.py

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Delete env methods & thread**

Delete methods `_noise_loop`, `_send_s1_env`, `_send_s1_weather`, `_compute_leq`. Remove `_noise_buf`, `_noise_buf_lock` from `__init__`. In `start()`, delete the `threading.Thread(target=self._noise_loop...)` start. In `_sensor_loop`, delete the noise-Leq block (the `if self.cfg.get("sensor_noise_enabled"...)` computing `leq`) and the `self._send_s1_weather(r)` call. In `_fill_gaps`, delete the "Kualitas udara" block that builds `jwt_e = self.net.create_jwt_s1_env(...)`.

- [ ] **Step 2: Run the app**

Run: `python main.py`
Expected: Dashboard runs identically; console shows water send logs only (no `[S1] PM+Noise`). Close.

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "refactor: remove noise/weather/env loops from app"
```

### Task 12: Remove env readers from sensors.py

**Files:**
- Modify: `sensors.py`
- Test: `tests/test_sensors.py`

- [ ] **Step 1: Delete env code**

Delete methods `_read_dust`, `_calc_pm_from_tsp`, `_read_noise`, `read_noise_safe`, `read_dust_safe`, `_read_weather`, `read_weather_safe`, `_to_signed16`, `_sim_dust`, `_sim_noise`, `_sim_weather`. In `read_all`, delete the `dust`, `temp`(keep!), `weather`, and noise branches that reference removed methods — keep only `ph, tss, debit, cod, nh3n, temp`.

- [ ] **Step 2: Run existing sensor tests**

Run: `python -m pytest tests/test_sensors.py -v`
Expected: PASS (3 passed) — cod/nh3n/temp readers intact.

- [ ] **Step 3: Commit**

```bash
git add sensors.py
git commit -m "refactor: remove dust/noise/weather sensor readers"
```

### Task 13: Remove env JWT from network.py

**Files:**
- Modify: `network.py`
- Test: `tests/test_network.py`

- [ ] **Step 1: Delete env JWT methods + env row fields**

Delete `create_jwt_s1_env`, `create_jwt_s1_weather`, `create_jwt_s1_env_status`. In `_build_row`, delete the `include_env` parameter and the `if include_env:` PM/noise block. In `create_jwt2`, change `self._build_row(r, processed=True, include_env=False)` → `self._build_row(r, processed=True)`.

- [ ] **Step 2: Add regression test for Server 2 carrying cod/nh3n**

Append to `tests/test_network.py`:
```python
def test_jwt2_includes_cod_nh3n():
    n, _ = _net()
    r = SensorReading(ph=7.0, tss=50.0, debit=1.2, cod=18.0, nh3n=1.1)
    token = n.create_jwt2([r])
    payload = jwt.decode(token, "testkey2", algorithms=["HS256"])
    assert payload["data"][0]["cod"] == 18.0
    assert payload["data"][0]["nh3n"] == 1.1
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_network.py -v`
Expected: PASS (4 passed).

- [ ] **Step 4: Commit**

```bash
git add network.py tests/test_network.py
git commit -m "refactor: remove env JWT methods, server2 carries cod/nh3n"
```

### Task 14: Remove env config keys

**Files:**
- Modify: `config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Delete env keys from DEFAULT_CONFIG**

Delete: `slave_id_dust`, `slave_id_noise`, `slave_id_weather`, `sensor_dust_enabled`, `sensor_noise_enabled`, `sensor_weather_enabled`, `float_dust`, `float_noise`, `float_weather`, `offset_pm100`, `offset_noise`, `offset_wind_speed`, `offset_air_temp`, `offset_humidity`, `offset_pressure`, `pm25_factor_min/max`, `pm10_factor_min/max`, all `sim_tsp_*`, `sim_noise_*`, `sim_wind_*`, `sim_air_temp_*`, `sim_humidity_*`, `sim_pressure_*`, and all `limit_pm25_*`, `limit_pm10_*`, `limit_pm100_*`, `limit_noise_*`. Keep all `*_temp` keys (water temperature).

- [ ] **Step 2: Add regression test**

Append to `tests/test_config.py`:
```python
def test_env_keys_removed():
    for k in ("sensor_dust_enabled", "sensor_noise_enabled",
              "sensor_weather_enabled", "limit_noise_min", "sim_tsp_min"):
        assert k not in DEFAULT_CONFIG
    assert "sensor_temp_enabled" in DEFAULT_CONFIG
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (4 passed).

- [ ] **Step 4: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "refactor: remove dust/noise/weather config keys"
```

### Task 15: Remove env fields from model & gap_filler

**Files:**
- Modify: `models.py`, `gap_filler.py`
- Test: `tests/test_gap_filler.py`

- [ ] **Step 1: Write the failing test**

`tests/test_gap_filler.py`:
```python
import gap_filler
from models import SensorReading


def test_save_state_roundtrip_water_only(tmp_path, monkeypatch):
    monkeypatch.setattr(gap_filler, "_STATE_FILE", tmp_path / "gap_state.json")
    r = SensorReading(timestamp=1000.0, ph=7.0, tss=50.0, debit=1.2,
                      cod=18.0, nh3n=1.1, temp=27.0)
    gap_filler.save_state(r)
    state = gap_filler._load_state()
    assert state["cod"] == 18.0
    assert state["nh3n"] == 1.1
    assert "pm25" not in state
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_gap_filler.py -v`
Expected: FAIL — `save_state` writes `pm25` and AttributeError-free only after edits; test asserts `pm25` absent.

- [ ] **Step 3: Edit models.py**

Remove fields `pm25, pm10, pm100, noise, wind_speed, wind_dir, air_temp, humidity, pressure` from `SensorReading`. Final fields: `timestamp, ph, tss, debit, cod, nh3n, temp`.

- [ ] **Step 4: Edit gap_filler.py**

In `save_state`, replace the JSON dict body with water-only:
```python
            json.dump({
                "last_ts": r.timestamp,
                "ph":      r.ph,
                "tss":     r.tss,
                "debit":   r.debit,
                "cod":     r.cod,
                "nh3n":    r.nh3n,
                "temp":    r.temp,
            }, f)
```
In `detect_and_fill`, replace the `SensorReading(...)` constructor with water-only:
```python
        slots.append(SensorReading(
            timestamp = slot_ts,
            ph        = _vary(state.get("ph",    7.5)),
            tss       = _vary(state.get("tss",   80.0)),
            debit     = _vary(state.get("debit", 0.05)),
            cod       = _vary(state.get("cod",   18.0)),
            nh3n      = _vary(state.get("nh3n",  1.0)),
            temp      = _vary(state.get("temp",  27.0)),
        ))
```

- [ ] **Step 5: Run all tests**

Run: `python -m pytest -v`
Expected: PASS (all tests green).

- [ ] **Step 6: Commit**

```bash
git add models.py gap_filler.py tests/test_gap_filler.py
git commit -m "refactor: water-only SensorReading and gap_filler"
```

### Task 16: Full regression run

- [ ] **Step 1: Full test suite**

Run: `python -m pytest -v`
Expected: all tests PASS.

- [ ] **Step 2: Grep for dangling env references**

Run: `git grep -nE "pm25|pm10|pm100|\.noise|wind_speed|wind_dir|air_temp|humidity|pressure|update_noise|update_weather|update_dust|create_jwt_s1_env|_send_s1_env|_send_s1_weather|_noise_loop" -- "*.py" ":!tests"`
Expected: **no matches** (every env reference removed). If any appear, fix them and re-run.

- [ ] **Step 3: Final app run (floating)**

Run: `python main.py`
Expected: Water dashboard runs cleanly; 6 cards update; sensor-select reflow works; mode buttons + logger toggles work; log scrolls; no tracebacks. Close.

- [ ] **Step 4: Commit (if any fixes)**

```bash
git add -A
git commit -m "chore: final cleanup of env references"
```

---

## Self-Review Notes

- **Spec coverage:** §4 model (T1,T15); §5 config (T2,T14); §6 sensors (T3,T12); §7 network (T4,T13); §8 app (T5,T11); §9 GUI (T7–T10); §10 device_info (T6); §11 testing (tests throughout + T16). All covered.
- **Type consistency:** `_apply_limits`/`get_processed` return a 5-tuple `(ph, tss, debit, cod, nh3n)` everywhere; `_WATER_DEFS` keys (`temp, ph, cod, tss, nh3n, debit`) match `update_sensors` format keys and `SensorReading` attributes.
- **Phase ordering** enforces: env model/config/network deletions (Phase 4) happen only after the new GUI + app no longer reference env (Phase 3).

"""
gui.py — Antarmuka grafis SPARING Monitor (Variant B: water-only dashboard).
Ditampilkan via HDMI pada Raspberry Pi / Orange Pi / Windows.
Semua update dari thread lain harus menggunakan root.after(0, ...).

Layout Variant B:
  ┌─ Header ─────────────────────────────────────────────────────┐
  │  Logo | Judul | Status Koneksi (4 chips)                    │
  ├─ Body ────────────────────────────────────────────────────────┤
  │  Sensor Grid (6 kartu air, 2 kolom)  │  Sidebar             │
  │  Log Panel (stub)                    │  (clock, info, mode) │
  ├─ Footer ──────────────────────────────────────────────────────┤
  │  Status echo | Sysmon | ⛶ F11 | ⚙ Sensor | ⚙ Pengaturan   │
  └──────────────────────────────────────────────────────────────┘
"""

import tkinter as tk
from tkinter import ttk
from datetime import datetime
from typing import TYPE_CHECKING

from constants import (
    C, LOGO_FILE, SYS_PLATFORM,
    HAS_PIL, HAS_SERIAL_TOOLS,
    Image, ImageTk, list_ports,
)
from config  import save_config, scan_serial_ports
from models  import SensorReading
from device_info import get_serial, get_macs

if TYPE_CHECKING:
    from app import SparingApp


# ── Konstanta visual ──────────────────────────────────────────────────────────
_FONT_UI    = "Segoe UI"
_FONT_MONO  = "Consolas"
_REF_W      = 1280        # resolusi referensi (lebar)
_REF_H      = 720         # resolusi referensi (tinggi)


class SparingGUI:
    """Jendela utama SPARING Monitor — Variant B (water-only dashboard)."""

    # ── Definisi sensor air ────────────────────────────────────────────────────
    # (cfg_key, sensor_key, label, unit, color_key)
    _WATER_DEFS = [
        ("sensor_temp_enabled",  "temp",  "SUHU",  "°C",       "s_suhu"),
        ("sensor_ph_enabled",    "ph",    "pH",    "",         "s_ph"),
        ("sensor_cod_enabled",   "cod",   "COD",   "mg/L",     "s_cod"),
        ("sensor_tss_enabled",   "tss",   "TSS",   "mg/L",     "s_tss"),
        ("sensor_nh3n_enabled",  "nh3n",  "NH3-N", "mg/L",     "s_nh3n"),
        ("sensor_debit_enabled", "debit", "DEBIT", "m³/menit", "s_debit"),
    ]

    def __init__(self, root: tk.Tk, app: "SparingApp"):
        self.root = root
        self.app  = app
        self.cfg  = app.cfg

        self._sensor_vars:  dict = {}      # key → StringVar nilai sensor (raw)
        self._conn_dots:    dict = {}      # key → Canvas (dot indikator)
        self._conn_chips:   dict = {}      # key → (StringVar, Label)
        self._conn_labels:  dict = {}      # alias untuk update_connection()
        self._sensor_cards: dict = {}      # cfg_key → canvas
        self._op_btn_refs:  dict = {}      # mode → (active_bg, Button)

        self._setup_window()
        self._calc_scale()
        self._setup_styles()
        self._build()
        self._tick_clock()

    # ── Scaling ───────────────────────────────────────────────────────────────
    def _calc_scale(self) -> None:
        """
        Hitung faktor skala dari resolusi layar aktual vs referensi 1280×720.
        sc < 1 → layar kecil (7-inch 800×480), sc > 1 → layar besar (1920×1080).
        Layar ≤ 600px tinggi dianggap layar kecil — gunakan layout kompak.
        """
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self._sc    = max(0.50, min(sw / _REF_W, sh / _REF_H, 1.8))
        self._small = sh <= 600          # True untuk layar 7-inch

    def _fs(self, n: int) -> int:
        """Skala font size — minimal 7pt."""
        return max(7, round(n * self._sc))

    def _sp(self, n: int) -> int:
        """Skala pixel (padding, width, height) — minimal 1px."""
        return max(1, round(n * self._sc))

    # ── Window ────────────────────────────────────────────────────────────────
    def _setup_window(self) -> None:
        self.root.title("SPARING Monitor — PT Sucofindo")
        self.root.configure(bg=C["bg"])
        self._is_fullscreen = tk.BooleanVar(value=True)
        self.root.attributes("-fullscreen", True)
        self.root.bind("<F11>",    self._toggle_fullscreen)
        self.root.bind("<Escape>", self._exit_fullscreen)

    def _toggle_fullscreen(self, event=None) -> None:
        v = not self._is_fullscreen.get()
        self._is_fullscreen.set(v)
        self.root.attributes("-fullscreen", v)

    def _exit_fullscreen(self, event=None) -> None:
        self._is_fullscreen.set(False)
        self.root.attributes("-fullscreen", False)

    def _setup_styles(self) -> None:
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure("TProgressbar",
                    troughcolor=C["border"],
                    background=C["progress"],
                    bordercolor=C["border"],
                    lightcolor=C["progress"],
                    darkcolor=C["progress"],
                    thickness=6)
        s.configure("Vertical.TScrollbar",
                    background=C["bg"],
                    troughcolor=C["bg"],
                    arrowcolor=C["text_muted"],
                    bordercolor=C["bg"],
                    gripcount=0)

    # ── Top-level build ───────────────────────────────────────────────────────
    def _build(self) -> None:
        self._build_header()
        self._build_footer()             # side="bottom" before content
        self._content = tk.Frame(self.root, bg=C["bg"])
        self._content.pack(fill="both", expand=True)
        body = tk.Frame(self._content, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=self._sp(12), pady=self._sp(8))
        # Scrollable — pada layar pendek/resolusi rendah, grid sensor + log
        # bisa lebih tinggi dari layar; scroll mencegah konten terpotong.
        _, self._left = self._make_scrollable(
            body, C["bg"], side="left", fill="both", expand=True,
            padx=(0, self._sp(8)))
        self._build_sensor_grid(self._left)
        self._build_log_panel(self._left)
        self._build_sidebar(body)
        self.root.after(100, self.apply_sensor_visibility)

    # ═══════════════════════════════════════════════════════════════════════════
    # HEADER — logo + title + 4 connection chips (NO clock)
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_header(self) -> None:
        # Top accent stripe
        tk.Frame(self.root, bg=C["primary"],
                 height=self._sp(4)).pack(fill="x")

        hdr = tk.Frame(self.root, bg=C["panel"])
        hdr.pack(fill="x")
        tk.Frame(self.root, bg=C["border"], height=1).pack(fill="x")

        row = tk.Frame(hdr, bg=C["panel"])
        row.pack(fill="x", padx=self._sp(18),
                 pady=(self._sp(3) if self._small else self._sp(5)))

        # ── Logo ──────────────────────────────────────────────────────────────
        self._add_logo(row)

        # Divider
        tk.Frame(row, bg=C["border"], width=1).pack(
            side="left", fill="y", padx=self._sp(18))

        # ── Title ─────────────────────────────────────────────────────────────
        title_col = tk.Frame(row, bg=C["panel"])
        title_col.pack(side="left", fill="y")

        self._app_title_var = tk.StringVar(value="SISTEM PEMANTAUAN KUALITAS AIR")
        tk.Label(title_col,
                 textvariable=self._app_title_var,
                 bg=C["panel"], fg=C["text"],
                 font=(_FONT_UI, self._fs(13), "bold")).pack(anchor="w")

        sub_row = tk.Frame(title_col, bg=C["panel"])
        sub_row.pack(anchor="w", pady=(self._sp(4), 0))
        tk.Frame(sub_row, bg=C["accent"],
                 width=self._sp(22), height=2).pack(
            side="left", anchor="center", padx=(0, self._sp(8)))
        tk.Label(sub_row,
                 text="SPARING  ●  Online Monitoring System",
                 bg=C["panel"], fg=C["accent"],
                 font=(_FONT_UI, self._fs(9))).pack(side="left")

        # ── Connection status chips ───────────────────────────────────────────
        conn_row = tk.Frame(row, bg=C["panel"])
        conn_row.pack(side="left", padx=(self._sp(30), 0), fill="y")

        _dot_sz = self._sp(8)
        for key, label in [
            ("rs485",    "RS485"),
            ("internet", "Internet"),
            ("server1",  "Internal"),
            ("server2",  "KLHK"),
        ]:
            chip_frame = tk.Frame(conn_row, bg=C["panel"])
            chip_frame.pack(side="left", padx=self._sp(6))

            dot = tk.Canvas(chip_frame, width=_dot_sz, height=_dot_sz,
                            bg=C["panel"], highlightthickness=0)
            dot.pack(side="left", padx=(0, self._sp(4)), pady=2)
            dot.create_oval(0, 0, _dot_sz, _dot_sz,
                            fill=C["border"], outline="", tags="dot")

            tk.Label(chip_frame, text=label,
                     bg=C["panel"], fg=C["text_muted"],
                     font=(_FONT_UI, self._fs(8))).pack(
                side="left", pady=(0, 1))

            var = tk.StringVar(value="...")
            status_lbl = tk.Label(chip_frame, textvariable=var,
                                  bg=C["panel"], fg=C["text_muted"],
                                  font=(_FONT_UI, self._fs(8), "bold"))
            status_lbl.pack(side="left", padx=(self._sp(2), 0))

            self._conn_dots[key]   = dot
            self._conn_chips[key]  = (var, status_lbl)
            self._conn_labels[key] = (var, status_lbl)

    def _add_logo(self, parent) -> None:
        if HAS_PIL and Image is not None and LOGO_FILE.exists():
            try:
                img = Image.open(LOGO_FILE).convert("RGBA")

                # Pertahankan aspek rasio — tinggi max sesuai header
                max_h = self._sp(48)
                max_w = self._sp(120)
                orig_w, orig_h = img.size
                ratio = min(max_w / orig_w, max_h / orig_h)
                new_w = max(1, round(orig_w * ratio))
                new_h = max(1, round(orig_h * ratio))

                # Resize high-quality dengan antialiasing
                img = img.resize((new_w * 2, new_h * 2), Image.LANCZOS)
                img = img.resize((new_w, new_h), Image.LANCZOS)

                # Tempel ke background panel (hilangkan artefak transparan)
                bg_img = Image.new("RGBA", (new_w, new_h), C["panel"])
                bg_img.paste(img, mask=img.split()[3])
                img = bg_img.convert("RGB")

                self._logo_img = ImageTk.PhotoImage(img)
                tk.Label(parent, image=self._logo_img,
                         bg=C["panel"]).pack(side="left")
                return
            except Exception:
                pass
        tk.Label(parent, text="SUCOFINDO",
                 bg=C["panel"], fg=C["primary_dark"],
                 font=(_FONT_UI, self._fs(13), "bold")).pack(side="left")

    # ═══════════════════════════════════════════════════════════════════════════
    # FOOTER — sysmon + buttons (NO op-mode buttons; those live in sidebar)
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_footer(self) -> None:
        tk.Frame(self.root, bg=C["border"], height=1).pack(fill="x")
        bar = tk.Frame(self.root, bg=C["panel"], height=self._sp(30))
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        # Left indicator strip
        tk.Frame(bar, bg=C["primary"],
                 width=self._sp(3)).pack(side="left", fill="y")

        # Status echo
        self._statusbar_var = tk.StringVar(value="Siap")
        self._statusbar_lbl = tk.Label(bar, textvariable=self._statusbar_var,
                 bg=C["panel"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(9)))
        if not self._small:
            self._statusbar_lbl.pack(side="left", padx=self._sp(10))
            tk.Frame(bar, bg=C["border"],
                     width=1).pack(side="left", fill="y", pady=self._sp(4))

        # Sysmon indicator
        if self.cfg.get("sysmon_enabled", True):
            self._sys_var = tk.StringVar(
                value="— °C  ·  — %  ·  — %" if self._small
                      else "CPU —  ·  — °C  ·  RAM —  ·  Disk —")
            self._sys_lbl = tk.Label(
                bar, textvariable=self._sys_var,
                bg=C["panel"], fg=C["text_muted"],
                font=(_FONT_MONO, self._fs(8)))
            self._sys_lbl.pack(side="left", padx=self._sp(6 if self._small else 10))

        # Right-side buttons
        self._flat_btn(bar, "⛶  F11",
                       self._toggle_fullscreen,
                       C["bg"], C["text_muted"],
                       pady=0).pack(side="right", padx=self._sp(4), pady=3)

        self._flat_btn(bar, "⚙  Pengaturan",
                       self._open_settings,
                       C["bg"], C["text_muted"],
                       pady=0).pack(side="right", padx=(0, self._sp(2)), pady=3)

        self._flat_btn(bar, "⚙  Sensor",
                       self._open_sensor_select,
                       C["bg"], C["accent"],
                       pady=0).pack(side="right", padx=(0, self._sp(2)), pady=3)

    # ═══════════════════════════════════════════════════════════════════════════
    # SENSOR GRID — 6 water cards in 2 columns
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_sensor_grid(self, parent) -> None:
        self._grid = tk.Frame(parent, bg=C["bg"])
        self._grid.pack(fill="both", expand=True)
        for cfg_key, key, label, unit, color in self._WATER_DEFS:
            self._sensor_cards[cfg_key] = self._water_card(key, label, unit, C[color])

    def _water_card(self, key: str, label: str, unit: str, accent: str) -> tk.Canvas:
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

    def apply_sensor_visibility(self) -> None:
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

    # ═══════════════════════════════════════════════════════════════════════════
    # LOG PANEL
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_log_panel(self, parent) -> None:
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

    # ═══════════════════════════════════════════════════════════════════════════
    # SIDEBAR — clock, device info, mode regulasi, logger toggles, status
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_sidebar(self, parent) -> None:
        outer = tk.Frame(parent, bg=C["bg"], width=self._sp(280))
        outer.pack(side="right", fill="y")
        outer.pack_propagate(False)
        # autosize_height=False — kartu rounded mengikuti tinggi layar yang
        # tersedia (bukan tinggi konten), lalu isinya dibungkus scrollable
        # agar tidak pernah terpotong di layar 7-inch beresolusi rendah.
        _, card = self._rounded_canvas(outer, C["card"], radius=self._sp(14),
                                       autosize_height=False,
                                       fill="both", expand=True)
        _, scroll_inner = self._make_scrollable(card, C["card"],
                                                fill="both", expand=True)
        inner = tk.Frame(scroll_inner, bg=C["card"],
                         padx=self._sp(12), pady=self._sp(10))
        inner.pack(fill="both", expand=True)

        # Clock — date + time
        self._date_var  = tk.StringVar()
        self._clock_var = tk.StringVar()
        tk.Label(inner, textvariable=self._date_var, bg=C["card"],
                 fg=C["text_muted"], font=(_FONT_UI, self._fs(9))).pack(anchor="w")
        tk.Label(inner, textvariable=self._clock_var, bg=C["card"], fg=C["text"],
                 font=(_FONT_MONO, self._fs(22), "bold")).pack(anchor="w")

        # Device info rows
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

    def _meta_row(self, parent, label, value) -> None:
        row = tk.Frame(parent, bg=C["card"])
        row.pack(fill="x", pady=1)
        tk.Label(row, text=label + ":", bg=C["card"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(7))).pack(side="left")
        kw = {"textvariable": value} if isinstance(value, tk.StringVar) else {"text": value}
        tk.Label(row, bg=C["card"], fg=C["text"],
                 font=(_FONT_MONO, self._fs(7), "bold"), **kw).pack(side="right")

    _MODE_DEFS = [
        ("normal",      "Normal",                 "#0052CC"),
        ("stopped",     "−1 Stop Sementara",      "#C62828"),
        ("calibrating", "−2 Kalibrasi/Audit",     "#E65100"),
        ("malfunction", "−3 Tidak Optimal/Rusak", "#6A1B9A"),
    ]

    def _build_mode_section(self, parent) -> None:
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

    def _build_logger_section(self, parent) -> None:
        tk.Label(parent, text="LOGGER", bg=C["card"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(8), "bold")).pack(anchor="w", pady=(self._sp(8), 2))
        row = tk.Frame(parent, bg=C["card"])
        row.pack(fill="x")
        for cfg_key, label in [("logger_internal", "Internal"), ("logger_klhk", "KLHK")]:
            var = tk.BooleanVar(value=self.cfg.get(cfg_key, False))
            def _toggle(k=cfg_key, v=var):
                self.cfg[k] = v.get()
                save_config(self.cfg)
                self.log(f"Logger {k} = {v.get()}")
            tk.Checkbutton(row, text=label, variable=var, command=_toggle,
                           bg=C["card"], fg=C["text"], activebackground=C["card"],
                           font=(_FONT_UI, self._fs(8)), selectcolor=C["card_alt"]
                           ).pack(side="left", padx=(0, self._sp(10)))

    def _build_status_section(self, parent) -> None:
        tk.Label(parent, text="STATUS PENGIRIMAN", bg=C["card"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(8), "bold")).pack(anchor="w", pady=(self._sp(8), 2))
        self._s1_status_var = tk.StringVar(value="Internal (Live): menunggu")
        self._s2_status_var = tk.StringVar(value="KLHK (Hourly): menunggu")
        for var in (self._s1_status_var, self._s2_status_var):
            tk.Label(parent, textvariable=var, bg=C["card"], fg=C["text_muted"],
                     font=(_FONT_UI, self._fs(8))).pack(anchor="w")

    # ═══════════════════════════════════════════════════════════════════════════
    # WIDGET HELPERS (carried verbatim from old gui.py)
    # ═══════════════════════════════════════════════════════════════════════════
    def _make_dialog(self, w: int, h: int, title: str = "") -> tk.Toplevel:
        """
        Buat Toplevel yang selalu muncul di atas window utama,
        termasuk saat fullscreen di embedded display (Orange Pi / RPi).
        """
        win = tk.Toplevel(self.root)
        win.title(title)
        win.configure(bg=C["bg"])
        win.resizable(False, False)
        win.transient(self.root)

        sx = self.root.winfo_screenwidth()
        sy = self.root.winfo_screenheight()
        # Jangan melebihi layar (mis. 7-inch 800×480) — cegah dialog terpotong
        w  = min(w, sx - self._sp(20))
        h  = min(h, sy - self._sp(40))
        x  = (sx - w) // 2
        y  = max(0, (sy - h) // 2)
        win.geometry(f"{w}x{h}+{x}+{y}")

        win.attributes("-topmost", True)   # selalu di atas fullscreen
        win.update_idletasks()
        win.lift()
        win.focus_force()
        win.grab_set()
        return win

    def _rounded_canvas(self, parent, card_bg: str,
                        radius: int = None,
                        outer_bg: str = None,
                        autosize_height: bool = True,
                        **pack_kw) -> tuple:
        """
        Buat Canvas dengan latar sudut melengkung (smooth polygon).
        Kembalikan (canvas, inner_frame).
        canvas  — dipasang ke parent sesuai pack_kw
        inner   — Frame tempat konten diletakkan

        autosize_height:
          True  (default) — canvas mengikuti tinggi konten (cocok untuk
                 kartu kecil yang berdiri sendiri, mis. kartu sensor/log).
          False — canvas mengikuti tinggi yang dialokasikan parent (fill/
                 expand), TIDAK membesar mengikuti konten. Dipakai untuk
                 wadah setinggi layar (mis. sidebar) agar tidak mendorong
                 layout lain keluar dari batas layar — konten di dalamnya
                 harus dibungkus scrollable (lihat _make_scrollable) agar
                 tidak terpotong.
        """
        r        = radius   if radius   is not None else self._sp(16)
        outer_bg = outer_bg if outer_bg is not None else C["bg"]
        pad      = self._sp(2)

        canvas = tk.Canvas(parent, bg=outer_bg,
                           highlightthickness=0, bd=0)
        if pack_kw:
            canvas.pack(**pack_kw)

        inner  = tk.Frame(canvas, bg=card_bg)
        win_id = canvas.create_window(pad, pad, window=inner, anchor="nw")

        def _redraw():
            w = canvas.winfo_width()
            h = canvas.winfo_height()
            if w < 4 or h < 4:
                return
            canvas.delete("rr")
            pts = [
                r, 0,   w-r, 0,   w, 0,   w, r,
                w, h-r, w, h,     w-r, h, r, h,
                0, h,   0, h-r,   0, r,   0, 0,
            ]
            canvas.create_polygon(pts, smooth=True,
                                  fill=card_bg, outline="", tags="rr")
            canvas.tag_lower("rr")
            canvas.itemconfig(win_id,
                              width=w - pad * 2,
                              height=h - pad * 2)

        def _on_canvas_resize(event=None):
            canvas.itemconfig(win_id, width=canvas.winfo_width() - pad * 2)
            canvas.after_idle(_redraw)

        def _on_inner_resize(event=None):
            if autosize_height:
                req_h = inner.winfo_reqheight() + pad * 2
                if req_h > 4 and abs(canvas.winfo_height() - req_h) > 1:
                    canvas.configure(height=req_h)
            canvas.after_idle(_redraw)

        canvas.bind("<Configure>", _on_canvas_resize)
        inner.bind("<Configure>",  _on_inner_resize)
        return canvas, inner

    def _make_scrollable(self, parent, bg: str, **pack_kw) -> tuple:
        """
        Bungkus konten dalam Canvas + Scrollbar vertikal agar TIDAK PERNAH
        terpotong di layar kecil/beresolusi rendah (mis. layar 7-inch dengan
        resolusi berbeda-beda) — konten yang lebih tinggi dari ruang yang
        tersedia otomatis bisa di-scroll (mouse wheel saat kursor di
        atasnya, atau drag scrollbar) alih-alih hilang/terpotong.
        Kembalikan (canvas, inner_frame) — konten diletakkan di inner_frame.
        """
        outer = tk.Frame(parent, bg=bg)
        if pack_kw:
            outer.pack(**pack_kw)

        canvas = tk.Canvas(outer, bg=bg, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner  = tk.Frame(canvas, bg=bg)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win_id, width=e.width))
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        def _wheel(e):
            if canvas.winfo_exists():
                canvas.yview_scroll(int(-e.delta / 120), "units")
        # Bind mouse wheel hanya saat kursor di atas canvas ini (bukan
        # bind_all permanen) — supaya beberapa area scrollable yang aktif
        # bersamaan (mis. konten utama + sidebar) tidak saling rebutan.
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        return canvas, inner

    def _card(self, parent, title: str, accent: str,
              **pack_kw) -> tk.Frame:
        """
        Kartu putih sudut melengkung dengan accent bar atas dan judul.
        Kembalikan inner frame tempat konten diletakkan.
        """
        canvas, outer = self._rounded_canvas(
            parent, C["card"], radius=self._sp(12), **pack_kw)

        # Accent stripe tipis di atas
        tk.Frame(outer, bg=accent,
                 height=self._sp(3)).pack(fill="x")

        # Title row
        title_row = tk.Frame(outer, bg=C["card"])
        title_row.pack(fill="x")
        tk.Label(title_row, text=title,
                 bg=C["card"], fg=accent,
                 font=(_FONT_UI, self._fs(8), "bold"),
                 padx=self._sp(10), pady=self._sp(6)).pack(side="left")

        tk.Frame(outer, bg=C["border"], height=1).pack(fill="x")

        # Content frame
        content = tk.Frame(outer, bg=C["card"])
        content.pack(fill="both", expand=True,
                     padx=self._sp(10), pady=self._sp(8))
        return content

    def _info_row(self, parent, label: str, var: tk.StringVar,
                  fg: str, suffix: str = "") -> None:
        row = tk.Frame(parent, bg=C["card"])
        row.pack(fill="x", pady=self._sp(2))
        tk.Label(row, text=label,
                 bg=C["card"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(7)),
                 anchor="w", width=15).pack(side="left")
        tk.Label(row, textvariable=var,
                 bg=C["card"], fg=fg,
                 font=(_FONT_MONO, self._fs(8), "bold")).pack(side="left")
        if suffix:
            tk.Label(row, text=suffix,
                     bg=C["card"], fg=C["text_muted"],
                     font=(_FONT_UI, self._fs(7))).pack(side="left")

    def _flat_btn(self, parent, text: str, cmd,
                  bg: str, fg: str,
                  pady: int = 5,
                  border: bool = False) -> tk.Button:
        kw = dict(
            text=text, command=cmd,
            bg=bg, fg=fg,
            font=(_FONT_UI, self._fs(9), "bold"),
            relief="flat", cursor="hand2", pady=self._sp(pady),
            activebackground=C["accent"],
            activeforeground="white",
        )
        if border:
            kw.update(highlightthickness=1,
                      highlightbackground=C["border"],
                      highlightcolor=C["primary"])
        return tk.Button(parent, **kw)

    def _tick_clock(self) -> None:
        now = datetime.now()
        self._clock_var.set(now.strftime("%H:%M:%S"))
        self._date_var.set(now.strftime("%d %B %Y"))
        self.root.after(1000, self._tick_clock)

    # ═══════════════════════════════════════════════════════════════════════════
    # PUBLIC UPDATE METHODS (called from app.py via root.after)
    # ═══════════════════════════════════════════════════════════════════════════

    def update_connection(self, key: str, ok: bool) -> None:
        var, lbl = self._conn_chips[key]
        dot      = self._conn_dots[key]
        if ok:
            var.set("●")
            lbl.configure(fg=C["online"])
            dot.itemconfig("dot", fill=C["online"])
        else:
            var.set("●")
            lbl.configure(fg=C["offline"])
            dot.itemconfig("dot", fill=C["offline"])

    def update_sensors(self, r: SensorReading) -> None:
        fmt = {"ph": "{:.2f}", "tss": "{:.1f}", "debit": "{:.3f}",
               "cod": "{:.2f}", "nh3n": "{:.2f}", "temp": "{:.1f}"}
        for key, f in fmt.items():
            if key in self._sensor_vars:
                self._sensor_vars[key].set(f.format(getattr(r, key)))

    def update_count(self, n: int, total: int = 30) -> None:
        if hasattr(self, "_statusbar_var"):
            self._statusbar_var.set(f"Data terkumpul: {n}/{total}")

    def update_last_tx(self, ts: float) -> None:
        t = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        self._last_rx_var.set(t)
        self._s1_status_var.set("Internal (Live): OK " +
                                datetime.fromtimestamp(ts).strftime("%H:%M:%S"))

    def update_buffer(self, n: int) -> None:
        pass  # no buffer widget in this layout; could extend later

    def update_send_status(self, s1_ok: bool, s2_ok: bool, ts: float) -> None:
        t = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
        self._s2_status_var.set(f"KLHK (Hourly): {'OK' if s2_ok else 'gagal'} {t}")

    def update_send_offline(self, ts: float) -> None:
        t = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
        self._s2_status_var.set(f"KLHK (Hourly): offline {t}")

    def update_sysmon(self, cpu, temp, mem, disk,
                      severity: str = "ok") -> None:
        """Perbarui indikator resource di footer."""
        if not hasattr(self, "_sys_var"):
            return
        def f(v, suf=""):
            return f"{v}{suf}" if v is not None else "—"
        if self._small:
            self._sys_var.set(
                f"{f(temp, '°C')}  ·  {f(mem, '%')}  ·  {f(disk, '%')}")
        else:
            self._sys_var.set(
                f"CPU {f(cpu, '%')}  ·  {f(temp, '°C')}  ·  "
                f"RAM {f(mem, '%')}  ·  Disk {f(disk, '%')}")
        if hasattr(self, "_sys_lbl"):
            color = {"ok":   C["text_muted"],
                     "warn": C["warning"],
                     "crit": C["offline"]}.get(severity, C["text_muted"])
            self._sys_lbl.configure(fg=color)

    def update_op_mode_btn(self, mode: str) -> None:
        for m, (bg, btn) in self._op_btn_refs.items():
            active = (m == mode)
            btn.configure(bg=bg if active else C["bg"],
                          fg="white" if active else C["text_muted"])
        if hasattr(self, "_mode_now_var"):
            self._mode_now_var.set(f"Mode saat ini: {mode}")

    def gap_btn_busy(self) -> None:
        pass  # gap button added in a later task

    def gap_btn_reset(self) -> None:
        pass  # gap button added in a later task

    def log(self, msg: str) -> None:
        line = f"[{datetime.now():%H:%M:%S}] {msg}\n"
        if hasattr(self, "_log_txt"):
            self._log_txt.configure(state="normal")
            self._log_txt.insert("end", line)
            self._log_txt.see("end")
            self._log_txt.configure(state="disabled")
        if hasattr(self, "_statusbar_var"):
            self._statusbar_var.set(str(msg)[:80])

    # ═══════════════════════════════════════════════════════════════════════════
    # DIALOGS
    # ═══════════════════════════════════════════════════════════════════════════

    def _open_sensor_select(self) -> None:
        """Dialog pilih sensor aktif — 6 parameter air."""
        w, h = self._sp(440), self._sp(520)
        win = self._make_dialog(w, h, "Pilihan Sensor")
        win.configure(bg=C["panel"])

        sensors = [
            ("sensor_temp_enabled",  "Suhu Air (°C)",     C["s_suhu"], "#FFCC80"),
            ("sensor_ph_enabled",    "pH",                C["s_ph"],   "#A8CCFF"),
            ("sensor_cod_enabled",   "COD (mg/L)",        C["s_cod"],  "#CE93D8"),
            ("sensor_tss_enabled",   "TSS (mg/L)",        C["s_tss"],  "#A0D8F0"),
            ("sensor_nh3n_enabled",  "NH3-N (mg/L)",      C["s_nh3n"], "#80DEEA"),
            ("sensor_debit_enabled", "Debit (m³/menit)",  C["s_debit"],"#9AECD8"),
        ]

        check_vars = {}

        def _apply():
            for cfg_key, var in check_vars.items():
                self.cfg[cfg_key] = var.get()
            save_config(self.cfg)
            self.apply_sensor_visibility()
            active = [lbl for cfg_key, lbl, *_ in sensors
                      if self.cfg.get(cfg_key, True)]
            self.log(f"Sensor aktif: {', '.join(active) if active else '(tidak ada)'}")
            win.destroy()

        # Tombol bar — pack pertama ke bawah agar selalu terlihat
        tk.Frame(win, bg=C["border"], height=1).pack(side="bottom", fill="x")
        btn_bar = tk.Frame(win, bg=C["panel"],
                           padx=self._sp(16), pady=self._sp(10))
        btn_bar.pack(side="bottom", fill="x")
        self._flat_btn(btn_bar, "✓  Terapkan",
                       _apply, C["primary"], "white",
                       pady=7).pack(side="left", padx=(0, self._sp(8)),
                                    ipadx=self._sp(10))
        self._flat_btn(btn_bar, "✕  Batal",
                       win.destroy, C["bg"], C["text_muted"],
                       pady=7).pack(side="left", ipadx=self._sp(10))

        # Header
        tk.Frame(win, bg=C["primary"], height=self._sp(4)).pack(fill="x")
        tk.Label(win, text="PILIH SENSOR AKTIF",
                 bg=C["panel"], fg=C["text"],
                 font=(_FONT_UI, self._fs(12), "bold"),
                 padx=self._sp(16), pady=self._sp(12)).pack(anchor="w")
        tk.Frame(win, bg=C["border"], height=1).pack(fill="x")

        tk.Label(win,
                 text="Sensor yang dinonaktifkan tidak akan\nditampilkan dan tidak dikirim ke server.",
                 bg=C["panel"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(8)),
                 justify="left").pack(anchor="w",
                                      padx=self._sp(16), pady=(self._sp(10), self._sp(4)))

        # Daftar sensor — satu baris per sensor
        for cfg_key, label, swatch, _lc in sensors:
            var = tk.BooleanVar(value=self.cfg.get(cfg_key, True))
            check_vars[cfg_key] = var

            row = tk.Frame(win, bg=C["panel"],
                           pady=self._sp(6), padx=self._sp(16))
            row.pack(fill="x")

            tk.Frame(row, bg=swatch,
                     width=self._sp(10), height=self._sp(10)).pack(
                side="left", padx=(0, self._sp(10)))

            # Custom toggle label (on/off visual)
            _lbl = tk.Label(
                row,
                text="✓" if var.get() else "",
                bg=C["primary"] if var.get() else C["border"],
                fg="white",
                font=(_FONT_UI, self._fs(10), "bold"),
                width=2,
                padx=self._sp(3),
                pady=self._sp(3),
                cursor="hand2",
            )
            _lbl.pack(side="right", padx=(self._sp(6), 0))

            def _bind_toggle(_v=var, _l=_lbl):
                def _tog(e=None):
                    _v.set(not _v.get())
                    _l.config(text="✓" if _v.get() else "",
                              bg=C["primary"] if _v.get() else C["border"])
                _l.bind("<Button-1>", _tog)
            _bind_toggle()

            tk.Checkbutton(row, text=label, variable=var,
                           bg=C["panel"], fg=C["text"],
                           activebackground=C["panel"],
                           font=(_FONT_UI, self._fs(10)),
                           selectcolor=C["card_alt"],
                           command=lambda _v=var, _l=_lbl: _l.config(
                               text="✓" if _v.get() else "",
                               bg=C["primary"] if _v.get() else C["border"])
                           ).pack(side="left", expand=True, anchor="w")

            tk.Frame(win, bg=C["border"], height=1).pack(
                fill="x", padx=self._sp(16))

    def _reconnect_rs485(self) -> None:
        import threading
        self.log("Menghubungkan ulang RS485...")
        self.update_connection("rs485", False)

        def _do():
            ok = self.app.sensor_rdr.reconnect() if self.app.sensor_rdr else False
            port = self.cfg.get("serial_port", "—")
            self.root.after(0, self.update_connection, "rs485", ok)
            self.root.after(0, self.log, f"RS485 {'terhubung' if ok else 'GAGAL'} — {port}")

        threading.Thread(target=_do, daemon=True, name="reconnect").start()

    def _scan_ports_dialog(self) -> None:
        """Dialog pilih port serial USB RS485."""
        win = self._make_dialog(self._sp(460), self._sp(360), "Scan Port USB RS485")
        win.configure(bg=C["bg"])

        tk.Frame(win, bg=C["primary"], height=self._sp(4)).pack(fill="x")

        title_bar = tk.Frame(win, bg=C["panel"])
        title_bar.pack(fill="x")
        tk.Label(title_bar, text="PORT SERIAL TERSEDIA",
                 bg=C["panel"], fg=C["text"],
                 font=(_FONT_UI, self._fs(11), "bold"),
                 padx=self._sp(16), pady=self._sp(10)).pack(side="left")
        tk.Frame(win, bg=C["border"], height=1).pack(fill="x")

        body = tk.Frame(win, bg=C["bg"], padx=self._sp(16), pady=self._sp(12))
        body.pack(fill="both", expand=True)

        tk.Label(body, text="Pilih port USB RS485 Anda:",
                 bg=C["bg"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(9), "bold")).pack(
            anchor="w", pady=(0, self._sp(6)))

        list_frame = tk.Frame(body, bg=C["shadow"], padx=1, pady=1)
        list_frame.pack(fill="both", expand=True)

        listbox = tk.Listbox(
            list_frame,
            font=(_FONT_MONO, self._fs(11)),
            bg=C["card"], fg=C["text"],
            selectbackground=C["primary"],
            selectforeground="white",
            relief="flat", bd=0, height=7,
            activestyle="none",
        )
        listbox.pack(fill="both", expand=True)

        info_var = tk.StringVar(value="")
        tk.Label(body, textvariable=info_var,
                 bg=C["bg"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(8))).pack(
            anchor="w", pady=(self._sp(6), 0))

        def _refresh():
            listbox.delete(0, "end")
            ports = scan_serial_ports()
            detail = {}
            if HAS_SERIAL_TOOLS and list_ports is not None:
                detail = {p.device: p.description for p in list_ports.comports()}
            for p in ports:
                listbox.insert("end", f"  {p}   {detail.get(p, '')}")
            if not ports:
                listbox.insert("end", "  (tidak ada port terdeteksi)")
            info_var.set(f"{len(ports)} port ditemukan")

        def _apply():
            sel = listbox.curselection()
            if not sel:
                return
            port = listbox.get(sel[0]).strip().split()[0]
            self.cfg["serial_port"] = port
            save_config(self.cfg)
            self.log(f"Port diubah ke: {port}")
            win.destroy()
            self._reconnect_rs485()

        _refresh()

        tk.Frame(win, bg=C["border"], height=1).pack(fill="x")
        btn_bar = tk.Frame(win, bg=C["panel"],
                           padx=self._sp(12), pady=self._sp(8))
        btn_bar.pack(fill="x")

        for text, cmd, bg, fg in [
            ("↻  Refresh",          _refresh,    C["bg"],      C["primary"]),
            ("✓  Gunakan Port Ini", _apply,      C["primary"], "white"),
            ("✕  Tutup",            win.destroy, C["bg"],      C["text_muted"]),
        ]:
            self._flat_btn(btn_bar, text, cmd, bg, fg,
                           pady=6).pack(side="left", padx=(0, self._sp(6)))

    # Field konfigurasi sensor Modbus — (label, slave_id key, offset key)
    _SENSOR_CFG = [
        ("pH",    "slave_id_ph",    "offset_ph"),
        ("TSS",   "slave_id_tss",   "offset_tss"),
        ("Debit", "slave_id_debit", "offset_debit"),
        ("COD",   "slave_id_cod",   "offset_cod"),
        ("NH3-N", "slave_id_nh3n",  "offset_nh3n"),
        ("Suhu",  "slave_id_temp",  "offset_temp"),
    ]

    # Field endpoint pengiriman — (label, config key)
    _ENDPOINT_DEFS = [
        ("Server 1 — URL kirim",        "server_url1"),
        ("Server 1 — URL secret key",   "secret_key_url1"),
        ("Server 1 — UID (Internal)",   "uid1"),
        ("Server 1 — UID (KLHK)",       "uid1_klhk"),
        ("Server 2 — URL kirim",        "server_url2"),
        ("Server 2 — URL secret key",   "secret_key_url2"),
        ("Server 2 — UID",              "uid2"),
    ]

    def _open_settings(self) -> None:
        """Dialog pengaturan koneksi RS485, port, dan endpoint pengiriman.
        Body bisa di-scroll agar tidak terpotong di layar kecil; tombol
        Simpan/Tutup selalu terlihat di bar bawah."""
        w, h = self._sp(560), self._sp(560)
        win = self._make_dialog(w, h, "Pengaturan")
        win.configure(bg=C["bg"])

        # Header stripe
        tk.Frame(win, bg=C["primary"], height=self._sp(4)).pack(fill="x")
        title_bar = tk.Frame(win, bg=C["panel"])
        title_bar.pack(fill="x")
        tk.Label(title_bar, text="PENGATURAN",
                 bg=C["panel"], fg=C["text"],
                 font=(_FONT_UI, self._fs(12), "bold"),
                 padx=self._sp(16), pady=self._sp(10)).pack(side="left")
        tk.Frame(win, bg=C["border"], height=1).pack(fill="x")

        endpoint_entries: dict = {}

        def _close():
            try:
                win.unbind_all("<MouseWheel>")
            except Exception:
                pass
            win.destroy()

        def _save_endpoints():
            for cfg_key, entry in endpoint_entries.items():
                self.cfg[cfg_key] = entry.get().strip()
            save_config(self.cfg)
            self.app.net.reset_keys()
            self.log("Endpoint pengiriman diperbarui — secret key akan diambil ulang")
            _close()

        # ── Button bar bawah — selalu terlihat ────────────────────────────
        tk.Frame(win, bg=C["border"], height=1).pack(side="bottom", fill="x")
        btn_bar = tk.Frame(win, bg=C["panel"],
                           padx=self._sp(16), pady=self._sp(8))
        btn_bar.pack(side="bottom", fill="x")
        self._flat_btn(btn_bar, "💾  Simpan Endpoint",
                       _save_endpoints, C["primary"], "white",
                       pady=6).pack(side="left")
        self._flat_btn(btn_bar, "✕  Tutup", _close,
                       C["bg"], C["text_muted"], pady=6).pack(side="right")

        # ── Body scrollable ───────────────────────────────────────────────
        outer = tk.Frame(win, bg=C["bg"])
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=C["bg"], highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = tk.Frame(canvas, bg=C["bg"], padx=self._sp(20), pady=self._sp(16))
        body_win = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(body_win, width=e.width))
        body.bind("<Configure>",
                  lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        def _wheel(e):
            if canvas.winfo_exists():
                canvas.yview_scroll(int(-e.delta / 120), "units")
        win.bind_all("<MouseWheel>", _wheel)

        # ── KONEKSI RS485 ─────────────────────────────────────────────────
        tk.Label(body, text="KONEKSI RS485",
                 bg=C["bg"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(9), "bold")).pack(anchor="w",
                                                             pady=(0, self._sp(6)))

        port_row = tk.Frame(body, bg=C["bg"])
        port_row.pack(fill="x", pady=(0, self._sp(8)))
        tk.Label(port_row, text="Port aktif:",
                 bg=C["bg"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(9))).pack(side="left")
        tk.Label(port_row,
                 text=self.cfg.get("serial_port", "—"),
                 bg=C["bg"], fg=C["text"],
                 font=(_FONT_MONO, self._fs(9), "bold")).pack(side="left",
                                                                padx=(self._sp(8), 0))

        def _reconnect_and_close():
            _close()
            self._reconnect_rs485()

        for text, cmd, bg, fg in [
            ("↻  Hubungkan Ulang",       _reconnect_and_close,      C["primary"], "white"),
            ("⌕  Scan Port",             self._scan_ports_dialog,   C["bg"],      C["primary"]),
            ("⚙  Konfigurasi Sensor",    self._open_sensor_config,  C["bg"],      C["primary"]),
        ]:
            self._flat_btn(body, text, cmd, bg, fg,
                           pady=8, border=(bg == C["bg"])).pack(
                fill="x", pady=self._sp(4))

        tk.Frame(body, bg=C["border"], height=1).pack(fill="x", pady=self._sp(12))

        # ── ENDPOINT PENGIRIMAN ───────────────────────────────────────────
        tk.Label(body, text="ENDPOINT PENGIRIMAN",
                 bg=C["bg"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(9), "bold")).pack(anchor="w",
                                                             pady=(0, self._sp(6)))

        for label, cfg_key in self._ENDPOINT_DEFS:
            row = tk.Frame(body, bg=C["bg"])
            row.pack(fill="x", pady=self._sp(3))
            tk.Label(row, text=label,
                     bg=C["bg"], fg=C["text_muted"],
                     font=(_FONT_UI, self._fs(8))).pack(anchor="w")
            entry = tk.Entry(row, width=44,
                             font=(_FONT_MONO, self._fs(8)),
                             bg=C["card"], fg=C["text"],
                             insertbackground=C["text"],
                             relief="flat")
            entry.insert(0, str(self.cfg.get(cfg_key, "")))
            entry.pack(fill="x", ipady=self._sp(3))
            endpoint_entries[cfg_key] = entry

    _BAUD_RATES = ["4800", "9600", "19200", "38400", "57600"]

    def _open_sensor_config(self) -> None:
        """Dialog konfigurasi Modbus: baud rate bus + slave ID/offset per sensor."""
        w, h = self._sp(430), self._sp(430)
        win = self._make_dialog(w, h, "Konfigurasi Sensor")
        win.configure(bg=C["bg"])

        # Header stripe
        tk.Frame(win, bg=C["primary"], height=self._sp(4)).pack(fill="x")
        title_bar = tk.Frame(win, bg=C["panel"])
        title_bar.pack(fill="x")
        tk.Label(title_bar, text="KONFIGURASI SENSOR (MODBUS)",
                 bg=C["panel"], fg=C["primary"],
                 font=(_FONT_UI, self._fs(11), "bold"),
                 padx=self._sp(16), pady=self._sp(10)).pack(side="left")
        tk.Frame(win, bg=C["border"], height=1).pack(fill="x")

        # Button bar — pack dulu ke bawah agar selalu terlihat
        tk.Frame(win, bg=C["border"], height=1).pack(side="bottom", fill="x")
        btn_bar = tk.Frame(win, bg=C["panel"],
                           padx=self._sp(16), pady=self._sp(10))
        btn_bar.pack(side="bottom", fill="x")

        outer = tk.Frame(win, bg=C["bg"])
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=C["bg"], highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = tk.Frame(canvas, bg=C["bg"], padx=self._sp(16), pady=self._sp(10))
        _body_win = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(_body_win, width=e.width))
        body.bind("<Configure>",
                  lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        def _wheel(e):
            if canvas.winfo_exists():
                canvas.yview_scroll(int(-e.delta / 120), "units")
        win.bind_all("<MouseWheel>", _wheel)

        # ── Baud rate ─────────────────────────────────────────────────────
        tk.Label(body, text="Baud rate (bus)",
                 bg=C["bg"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(9), "bold")).pack(anchor="w")

        baud_var = tk.StringVar(value=str(self.cfg.get("baud_rate", 9600)))
        baud_combo = ttk.Combobox(body, textvariable=baud_var,
                                  values=self._BAUD_RATES,
                                  state="readonly", width=10,
                                  font=(_FONT_MONO, self._fs(9)))
        baud_combo.pack(anchor="w", pady=(self._sp(4), self._sp(2)))

        tk.Label(body,
                 text="Semua sensor di satu bus harus sama.\nCODS-3000-02 default 19200.",
                 bg=C["bg"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(7)),
                 justify="left").pack(anchor="w", pady=(0, self._sp(8)))

        tk.Frame(body, bg=C["border"], height=1).pack(fill="x", pady=self._sp(6))

        # ── Tipe Debit ────────────────────────────────────────────────────
        tk.Label(body, text="Tipe Debit",
                 bg=C["bg"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(9), "bold")).pack(anchor="w")

        _debit_channel_labels = {"open": "Open Channel", "closed": "Closed Channel"}
        debit_type_var = tk.StringVar(
            value=_debit_channel_labels.get(
                self.cfg.get("debit_channel", "open"), "Open Channel"))
        debit_type_combo = ttk.Combobox(body, textvariable=debit_type_var,
                                        values=["Open Channel", "Closed Channel"],
                                        state="readonly", width=16,
                                        font=(_FONT_UI, self._fs(9)))
        debit_type_combo.pack(anchor="w", pady=(self._sp(4), self._sp(8)))

        tk.Frame(body, bg=C["border"], height=1).pack(fill="x", pady=self._sp(6))

        # ── Per-sensor: Slave ID + Offset ────────────────────────────────
        header_row = tk.Frame(body, bg=C["bg"])
        header_row.pack(fill="x")
        tk.Label(header_row, text="Sensor",
                 bg=C["bg"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(8), "bold"),
                 width=8, anchor="w").pack(side="left")
        tk.Label(header_row, text="Slave ID",
                 bg=C["bg"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(8), "bold"),
                 width=8, anchor="w").pack(side="left")
        tk.Label(header_row, text="Offset",
                 bg=C["bg"], fg=C["text_muted"],
                 font=(_FONT_UI, self._fs(8), "bold"),
                 width=8, anchor="w").pack(side="left")

        slave_entries: dict = {}
        offset_entries: dict = {}

        for label, slave_key, offset_key in self._SENSOR_CFG:
            row = tk.Frame(body, bg=C["bg"])
            row.pack(fill="x", pady=self._sp(2))

            tk.Label(row, text=label,
                     bg=C["bg"], fg=C["text"],
                     font=(_FONT_UI, self._fs(9)),
                     width=8, anchor="w").pack(side="left")

            slave_entry = tk.Entry(row, width=5,
                                   font=(_FONT_MONO, self._fs(9)),
                                   bg=C["card"], fg=C["text"],
                                   insertbackground=C["text"],
                                   relief="flat")
            slave_entry.insert(0, str(self.cfg.get(slave_key, "")))
            slave_entry.pack(side="left", padx=(0, self._sp(10)), ipady=self._sp(2))
            slave_entries[slave_key] = slave_entry

            offset_entry = tk.Entry(row, width=8,
                                    font=(_FONT_MONO, self._fs(9)),
                                    bg=C["card"], fg=C["text"],
                                    insertbackground=C["text"],
                                    relief="flat")
            offset_entry.insert(0, str(self.cfg.get(offset_key, "")))
            offset_entry.pack(side="left", ipady=self._sp(2))
            offset_entries[offset_key] = offset_entry

        # ── Save handler ─────────────────────────────────────────────────
        def _save_and_reconnect():
            # Baud rate
            try:
                baud = int(baud_var.get())
                self.cfg["baud_rate"] = baud
            except (TypeError, ValueError):
                pass

            # Tipe Debit (open/closed channel)
            self.cfg["debit_channel"] = ("closed"
                                         if debit_type_var.get().startswith("Closed")
                                         else "open")

            # Per-sensor slave id / offset — skip silently on bad input
            for _label, slave_key, offset_key in self._SENSOR_CFG:
                try:
                    sid = int(slave_entries[slave_key].get().strip())
                    if 1 <= sid <= 255:
                        self.cfg[slave_key] = sid
                except (TypeError, ValueError):
                    pass

                try:
                    off = float(offset_entries[offset_key].get().strip())
                    self.cfg[offset_key] = off
                except (TypeError, ValueError):
                    pass

            save_config(self.cfg)
            self.log("Konfigurasi sensor disimpan — menghubungkan ulang RS485...")

            import threading

            def _do():
                ok = self.app.sensor_rdr.reconnect() if getattr(self.app, "sensor_rdr", None) else False
                self.root.after(0, self.update_connection, "rs485", ok)
                self.root.after(0, self.log, f"RS485 {'terhubung' if ok else 'GAGAL'} setelah ubah konfigurasi")

            threading.Thread(target=_do, daemon=True, name="reconnect_cfg").start()
            win.destroy()

        self._flat_btn(btn_bar, "💾  Simpan & Hubungkan Ulang",
                       _save_and_reconnect, C["primary"], "white",
                       pady=7).pack(side="left", padx=(0, self._sp(8)),
                                    ipadx=self._sp(6))
        self._flat_btn(btn_bar, "✕  Tutup",
                       win.destroy, C["bg"], C["text_muted"],
                       pady=7).pack(side="left", ipadx=self._sp(10))

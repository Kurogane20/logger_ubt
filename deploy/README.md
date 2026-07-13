# Auto-start SPARING Monitor (systemd)

Menjalankan dashboard otomatis saat perangkat menyala, fullscreen di layar HDMI.
Berkas:

- `sparing.service` — template unit systemd (placeholder `__USER__` / `__DIR__` / `__PY__`)
- `install-sparing-service.sh` — installer (mengisi placeholder & mengaktifkan service)

## Prasyarat (di perangkat: Raspberry Pi / Orange Pi)

1. **Desktop + AUTOLOGIN aktif.** App adalah GUI Tk fullscreen, jadi butuh sesi
   desktop yang login otomatis ke user Anda saat boot.
   - Raspberry Pi: `sudo raspi-config` → *System Options* → *Boot / Auto Login* →
     **Desktop Autologin**.
   - Orange Pi/Armbian: `sudo armbian-config` → *System* → atur autologin desktop.
2. **Dependency Python terpasang** (dari root repo):
   ```bash
   pip3 install -r requirements.txt
   # atau pakai virtualenv:
   python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
   ```
   (Installer otomatis memakai `.venv/` bila ada, kalau tidak pakai `python3` sistem.)

## Pasang

Dari **root repo di perangkat**:
```bash
sudo bash deploy/install-sparing-service.sh
```
Installer mendeteksi otomatis user, lokasi project, dan Python; menambahkan user
ke grup `dialout` (akses RS485); lalu enable + start service `sparing`.

> Grup `dialout` baru berlaku setelah **logout/login** (atau reboot).

## Kelola

```bash
systemctl status sparing          # status
journalctl -u sparing -f          # lihat log real-time
sudo systemctl restart sparing    # restart
sudo systemctl stop sparing       # hentikan sementara
sudo systemctl disable sparing    # matikan auto-start saat boot
```

## Catatan Display (PENTING)

Unit default memakai **X11** (`DISPLAY=:0`). Ini bekerja pada mayoritas setup
kiosk (Pi OS versi lama, Armbian desktop, LXDE/Openbox).

**Jika desktop Anda Wayland** (mis. Raspberry Pi OS *Bookworm* dengan labwc/wayfire),
`DISPLAY=:0` tidak akan menampilkan apa pun. Pilihan:

- **Paling mudah** — ganti ke X11: `sudo raspi-config` → *Advanced Options* →
  *Wayland* → **X11**, lalu reboot. Unit ini langsung jalan.
- **Tetap Wayland** — jangan pakai systemd untuk GUI-nya; taruh perintah start di
  autostart compositor (mis. `~/.config/labwc/autostart`):
  ```
  cd /path/ke/project && /path/ke/python main.py &
  ```

## Uninstall

```bash
sudo systemctl disable --now sparing
sudo rm /etc/systemd/system/sparing.service
sudo systemctl daemon-reload
```

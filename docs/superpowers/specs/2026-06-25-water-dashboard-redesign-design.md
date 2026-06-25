# Redesain Tampilan SPARING Monitor — Dashboard Kualitas Air

**Tanggal:** 2026-06-25
**Status:** Disetujui untuk perencanaan implementasi

## 1. Ringkasan & Tujuan

Mengganti tampilan GUI lama (`gui.py`) dengan dashboard kualitas air baru yang
meniru tata letak perangkat referензi pada foto (gaya "SCITECH Live Dashboard"),
namun dengan branding Sucofindo. Perangkat menjadi **murni monitoring air**:
sensor udara, kebisingan, dan cuaca dihapus total; ditambahkan dua parameter air
baru **COD** dan **NH3-N**.

## 2. Keputusan Desain (hasil brainstorming)

| Keputusan | Pilihan |
|---|---|
| Mekanisme kunci/PIN | **Dihapus** — semua tampil terbuka di satu layar |
| Sensor udara/noise/cuaca | **Hapus total** — tampilan + pengiriman server + kode pembacaan |
| Sumber COD & NH3-N | **Hardware** (Modbus RS485), pembacaan configurable |
| Tata letak | **Varian B** — header atas tipis + grid 6 parameter + sidebar kanan |
| Gaya kartu | Putih dengan garis aksen atas (gaya foto), menampilkan nilai terukur (raw) |
| Label logger | "Internal" / "KLHK" (bukan "SCITECH/KLH") |

## 3. Cakupan

**Termasuk:**
- Tulis ulang `gui.py` sebagai dashboard air (tanpa overlay kunci, tanpa tampilan raw/processed ganda).
- Tambah COD & NH3-N: model data, config, pembacaan sensor, pengiriman server, batas nilai, pilihan sensor.
- Hapus penuh: PM/debu, noise/kebisingan, cuaca (YGC-CSM) dari seluruh pipeline.
- Sidebar kanan: jam, info perangkat (Serial Number, MAC, Started At, Last Rx), Mode Regulasi, toggle logger, status pengiriman.

**Tidak termasuk:**
- Perubahan protokol/format JWT selain mengisi field `cod`/`nh3n` yang sudah ada.
- Perubahan pada `storage.py`, `gap_filler.py`, `sysmon.py` (selain dampak hapus env JWT pada gap fill).

## 4. Parameter & Model Data

Enam parameter air, urutan grid 2 kolom (reflow otomatis bila sebagian dimatikan):

| Baris | Kolom kiri | Kolom kanan |
|---|---|---|
| 1 | Suhu (°C) | pH |
| 2 | COD (mg/L) | TSS (mg/L) |
| 3 | NH3-N (mg/L) | Debit (m³/menit) |

**`models.py`** — `SensorReading`:
- Tambah: `cod: float = 0.0`, `nh3n: float = 0.0`.
- Pertahankan: `timestamp`, `ph`, `tss`, `debit`, `temp`.
- Hapus: `pm25`, `pm10`, `pm100`, `noise`, `wind_speed`, `wind_dir`, `air_temp`, `humidity`, `pressure`.

## 5. Konfigurasi (`config.py`)

**Tambah kunci** (nilai default; diset ulang oleh pengguna saat commissioning):
- `sensor_cod_enabled: True`, `sensor_nh3n_enabled: True`
- `slave_id_cod: 7`, `slave_id_nh3n: 8`
- Pembacaan configurable: `reg_addr_cod: 0`, `reg_count_cod: 2`, `reg_index_cod: 1`, `scale_cod: 100.0` (nilai = `reg[index] / scale`); idem untuk `*_nh3n`.
- `float_cod: False`, `float_nh3n: False`
- `offset_cod: 0.0`, `offset_nh3n: 0.0`
- `sim_cod_min: 10.0`, `sim_cod_max: 30.0`; `sim_nh3n_min: 0.5`, `sim_nh3n_max: 2.0`
- `limit_cod_*` (min/max + float_lo/hi zones), `limit_nh3n_*` (struktur sama dengan limit pH/TSS).

**Hapus kunci** dust/noise/weather: `slave_id_dust/noise/weather`, `sensor_dust/noise/weather_enabled`, `float_dust/noise/weather`, `offset_pm100/noise/wind_speed/air_temp/humidity/pressure`, `pm25/pm10_factor_*`, `sim_tsp/noise/wind_*/air_temp/humidity/pressure_*`, `limit_pm25/pm10/pm100/noise_*`.

**Pertahankan:** `sensor_temp_enabled`, `float_temp`, `offset_temp`, `sim_temp_*`, `limit_temp_*`.

Catatan: key lama yang tersisa di `config.json` pengguna bersifat tidak berbahaya (diabaikan); `load_config` hanya menambah key baru dari `DEFAULT_CONFIG`.

## 6. Pembacaan Sensor (`sensors.py`)

- Tambah `_read_cod()`, `_read_nh3n()`: pembacaan Modbus generik configurable
  (`slave_id` + `reg_addr` + `reg_count` + `reg_index` + `scale` + `offset`),
  default `nilai = reg[index] / 100` (pola seperti pH). Hormati `_is_float()`.
- Tambah `_sim_cod()`, `_sim_nh3n()` memakai `sim_*` config.
- Hapus: `_read_dust`, `_read_noise`, `_read_weather`, `_calc_pm_from_tsp`,
  `_sim_dust`, `_sim_noise`, `_sim_weather`, `read_dust_safe`, `read_noise_safe`,
  `read_weather_safe`, `_to_signed16`.
- `read_all()`: baca `ph, tss, debit, cod, nh3n, temp` sesuai flag enabled.

## 7. Pengiriman / Payload (`network.py`)

- `_build_row`: isi `cod`/`nh3n` dari reading (gantikan hardcoded `0`), gated oleh `sensor_*_enabled`. Hapus param `include_env` dan field PM/noise.
- `_apply_limits`: ubah jadi `(ph, tss, debit, cod, nh3n)` → 5 nilai terfilter. Hapus pm/noise.
- `create_jwt1_water`: tambah `cod`, `nh3n` (raw & processed). `temp` tetap.
- `create_jwt1_water_status`: sertakan `cod`/`nh3n` = status_code (sudah ada sebagian).
- `create_jwt2`: kini sertakan `cod`/`nh3n` (parameter air) — hapus pemfilteran env.
- Hapus: `create_jwt_s1_env`, `create_jwt_s1_weather`, `create_jwt_s1_env_status`.
- `get_processed`: disederhanakan/dihapus (GUI tidak lagi menampilkan processed; jalur KLHK memakai `create_jwt*(processed=True)`).

## 8. Orkestrasi (`app.py`)

- `_simulate()`: tambah `cod`, `nh3n`; hapus field PM/noise/weather.
- **Hapus** thread & metode: `_noise_loop`, `_send_s1_env`, `_send_s1_weather`,
  `_compute_leq`, buffer `_noise_buf`/lock terkait.
- `_sensor_loop`: hapus pemrosesan env & update GUI dust/noise/weather; tambah
  `cod`/`nh3n` ke log dan update GUI; hapus pemanggilan `get_processed` untuk display.
- `_fill_gaps`: hapus pembuatan env JWT (hanya JWT air).
- Tangkap `started_at` (waktu mulai app) untuk ditampilkan di sidebar.

## 9. Tata Letak GUI (`gui.py` — tulis ulang)

**Header atas (tipis):** logo Sucofindo + judul "SISTEM PEMANTAUAN KUALITAS AIR"
+ lampu koneksi (RS485 / Internet / Internal / KLHK) memakai `update_connection`
yang sudah ada.

**Badan — dua panel:**
- **Kiri (≈2/3):** grid 6 kartu parameter (putih + aksen atas, nilai monospace
  besar, satuan di bawah) + panel **Log Aktivitas** (terminal) + indikator "Data OK".
  Grid reflow via `apply_sensor_visibility` yang diperbarui untuk 6 parameter air.
- **Kanan (≈1/3) sidebar:**
  - Jam besar + tanggal.
  - Info perangkat: Started At, Last Rx (`last_tx`), Serial Number, MAC eth0/wlan0.
  - **Mode Regulasi**: tombol Normal / −1 Stop Sementara / −2 Kalibrasi/Audit /
    −3 Tidak Optimal/Rusak (memanggil `app.set_operation_mode`) + teks "Mode saat ini".
  - **Logger**: centang Internal (`logger_internal`) & KLHK (`logger_klhk`), simpan config.
  - **Status Pengiriman**: Internal (Live) = Server 1; KLHK (Hourly) = Server 2.

**Footer (tipis):** indikator resource sistem (sysmon, via `update_sysmon`) +
tombol Fullscreen (F11) / Pilih Sensor / Pengaturan.

**Dialog (tetap, kini tanpa PIN):** Pengaturan Koneksi, Scan Port, Pilih Sensor
(diperbarui: 6 parameter air, tambah COD/NH3-N, buang udara/noise/cuaca),
Floating per Sensor (idem).

**Dihapus dari `gui.py`:** seluruh kode locked overlay, lock/unlock/PIN, baris
dust/noise/weather, tampilan processed ganda & masking.

**Warna kartu** (`constants.py`, tambah ke dict `C`): Suhu `#E65100`, pH `#0052CC`,
COD `#6A1B9A`, TSS `#0091D5`, NH3-N `#00838F`, Debit `#00897B`.

## 10. Info Perangkat (helper baru)

Modul kecil (mis. `device_info.py`) atau fungsi di `sysmon.py`:
- `get_serial()`: Linux baca `/proc/cpuinfo` (field Serial) atau
  `/sys/firmware/devicetree/base/serial-number`; fallback ke config `device_serial`
  atau `"—"`.
- `get_macs()`: Linux baca `/sys/class/net/eth0/address` & `wlan0/address`;
  Windows fallback via `psutil.net_if_addrs()` atau `uuid.getnode()`.
- `started_at`: di-set saat `SparingApp.start()`.

## 11. Pengujian

- **Manual (Windows, floating mode):** layout render benar; reflow grid saat
  sensor dimatikan lewat dialog Pilih Sensor; tombol Mode Regulasi mengubah mode;
  centang logger tersimpan ke config; info perangkat tampil (serial/MAC fallback);
  jam berjalan; log mengalir.
- **Otomatis:** `config` memuat default COD/NH3-N; payload `create_jwt1_water` &
  `create_jwt2` memuat `cod`/`nh3n`; `_apply_limits` memfilter cod/nh3n sesuai batas;
  `read_all` mengisi cod/nh3n saat floating.

## 12. Risiko & Catatan

- **Register Modbus COD/NH3-N** belum pasti formatnya; pembacaan dibuat configurable
  dengan default `reg/100`. Pengguna wajib memverifikasi terhadap datasheet analyzer
  saat commissioning (bisa di-floating dulu bila perlu).
- **Kepatuhan:** penghapusan pengiriman udara/noise/cuaca diasumsikan sesuai izin
  lingkungan (perangkat khusus air). Dikonfirmasi pengguna.
- **Suhu air** tidak difilter batas (sama seperti perilaku lama); hanya 5 parameter
  (pH, TSS, Debit, COD, NH3-N) yang melalui `_apply_limits`.

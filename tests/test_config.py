from config import DEFAULT_CONFIG


def test_cod_nh3n_sensor_flags_present():
    assert DEFAULT_CONFIG["sensor_cod_enabled"] is True
    assert DEFAULT_CONFIG["sensor_nh3n_enabled"] is True


def test_cod_nh3n_modbus_keys_present():
    for k in ("slave_id_cod", "reg_addr_cod", "reg_index_cod", "scale_cod",
              "offset_cod",
              "slave_id_nh3n", "reg_addr_nh3n", "reg_index_nh3n", "scale_nh3n",
              "offset_nh3n"):
        assert k in DEFAULT_CONFIG, f"missing {k}"


def test_cod_nh3n_limit_keys_present():
    for p in ("cod", "nh3n"):
        for s in ("min", "max", "float_lo_min", "float_lo_max",
                  "float_hi_min", "float_hi_max"):
            assert f"limit_{p}_{s}" in DEFAULT_CONFIG, f"missing limit_{p}_{s}"


def test_env_keys_removed():
    for k in ("sensor_dust_enabled", "sensor_noise_enabled",
              "sensor_weather_enabled", "limit_noise_min", "sim_tsp_min"):
        assert k not in DEFAULT_CONFIG
    assert "sensor_temp_enabled" in DEFAULT_CONFIG


def test_simulation_keys_removed():
    for k in ("simulate_sensors", "float_ph", "float_cod", "float_nh3n",
              "sim_ph_min", "sim_cod_min", "sim_nh3n_max"):
        assert k not in DEFAULT_CONFIG

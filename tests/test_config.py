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

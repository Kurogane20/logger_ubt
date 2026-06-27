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
    assert reading.cod >= cfg["sim_cod_min"]
    assert reading.nh3n >= cfg["sim_nh3n_min"]

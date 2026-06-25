from models import SensorReading


def test_reading_has_cod_and_nh3n_defaults():
    r = SensorReading()
    assert r.cod == 0.0
    assert r.nh3n == 0.0


def test_reading_accepts_cod_and_nh3n():
    r = SensorReading(cod=12.5, nh3n=1.3)
    assert r.cod == 12.5
    assert r.nh3n == 1.3

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
    n, cfg = _net()
    cfg["sensor_cod_enabled"] = True
    cfg["sensor_nh3n_enabled"] = True
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


def test_jwt2_includes_cod_nh3n():
    n, cfg = _net()
    cfg["sensor_cod_enabled"] = True
    cfg["sensor_nh3n_enabled"] = True
    r = SensorReading(ph=7.0, tss=50.0, debit=1.2, cod=18.0, nh3n=1.1)
    token = n.create_jwt2([r])
    payload = jwt.decode(token, "testkey2", algorithms=["HS256"])
    assert payload["data"][0]["cod"] == 18.0
    assert payload["data"][0]["nh3n"] == 1.1

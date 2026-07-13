from config import DEFAULT_CONFIG
from sensors import SensorReader


def _reader_no_hw():
    # pymodbus/hardware absent on this machine → _mb stays None
    return SensorReader({**DEFAULT_CONFIG})


def test_read_all_returns_zeros_without_hardware():
    rdr = _reader_no_hw()
    r = rdr.read_all()
    assert r.ph == 0.0
    assert r.cod == 0.0
    assert r.nh3n == 0.0


def test_read_scaled_applies_register_scale_and_offset(monkeypatch):
    rdr = _reader_no_hw()

    class _FakeResult:
        registers = [0, 1850]      # reg[1] = 1850
        def isError(self):
            return False

    rdr._mb = object()             # pretend hardware present
    monkeypatch.setattr(rdr, "_rhr", lambda addr, count, slave: _FakeResult())
    rdr.cfg["reg_index_cod"] = 1
    rdr.cfg["scale_cod"] = 100.0
    rdr.cfg["offset_cod"] = 0.0
    # value = reg[1] / scale + offset = 1850 / 100 = 18.5
    assert rdr._read_cod() == 18.5

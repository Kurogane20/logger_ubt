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
    rdr.cfg["reg_index_nh3n"] = 1
    rdr.cfg["scale_nh3n"] = 100.0
    rdr.cfg["offset_nh3n"] = 0.0
    # value = reg[1] / scale + offset = 1850 / 100 = 18.5
    assert rdr._read_nh3n() == 18.5


def test_read_cod_decodes_ieee754_cdab_float(monkeypatch):
    rdr = SensorReader({**DEFAULT_CONFIG})

    class _R:
        registers = [0x0000, 0x40E0]   # CODS-3000-02 manual example -> 7.00 mg/L
        def isError(self):
            return False

    rdr._mb = object()
    monkeypatch.setattr(rdr, "_rhr", lambda addr, count, slave: _R())
    assert rdr._read_cod() == 7.0


def test_read_debit_closed_decodes_float_cdab(monkeypatch):
    rdr = SensorReader({**DEFAULT_CONFIG})

    class _R:
        registers = [0x0000, 0x3F80]   # CDAB float -> 1.0
        def isError(self):
            return False

    rdr._mb = object()
    rdr.cfg["offset_debit"] = 0.0
    monkeypatch.setattr(rdr, "_rhr", lambda addr, count, slave: _R())
    assert rdr._read_debit_closed() == 1.0


def test_read_debit_dispatches_by_channel(monkeypatch):
    rdr = SensorReader({**DEFAULT_CONFIG})
    monkeypatch.setattr(rdr, "_read_debit_open",   lambda: 11.0)
    monkeypatch.setattr(rdr, "_read_debit_closed", lambda: 22.0)
    rdr.cfg["debit_channel"] = "open"
    assert rdr._read_debit() == 11.0
    rdr.cfg["debit_channel"] = "closed"
    assert rdr._read_debit() == 22.0

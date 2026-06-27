import gap_filler
from models import SensorReading


def test_save_state_roundtrip_water_only(tmp_path, monkeypatch):
    monkeypatch.setattr(gap_filler, "_STATE_FILE", tmp_path / "gap_state.json")
    r = SensorReading(timestamp=1000.0, ph=7.0, tss=50.0, debit=1.2,
                      cod=18.0, nh3n=1.1, temp=27.0)
    gap_filler.save_state(r)
    state = gap_filler._load_state()
    assert state["cod"] == 18.0
    assert state["nh3n"] == 1.1
    assert "pm25" not in state

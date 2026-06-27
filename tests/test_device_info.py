import device_info


def test_get_serial_returns_nonempty_string():
    s = device_info.get_serial()
    assert isinstance(s, str)
    assert s != ""


def test_get_macs_returns_eth_and_wlan_keys():
    macs = device_info.get_macs()
    assert "eth0" in macs
    assert "wlan0" in macs

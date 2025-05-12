from watchmen.client import ClientMode


def test_in_mode_method():
    assert ClientMode.has_value("queue") is True

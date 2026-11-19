import pytest

from factoriobench.desktop import ActionError, parse_keys, seconds


@pytest.mark.parametrize("combo, keys", [
    ("w", ["w"]),
    ("W", ["w"]),
    ("Return", ["Return"]),
    ("enter", ["Return"]),
    ("ctrl+s", ["ctrl", "s"]),
    ("Ctrl+Shift+Z", ["ctrl", "shift", "z"]),
    ("alt+Tab", ["alt", "Tab"]),
    ("`", ["grave"]),
    ("F4", ["F4"]),
    ("+", ["plus"]),
    ("ctrl++", ["ctrl", "plus"]),
    ("shift + space", ["shift", "space"]),
    ("Page_Down", ["Next"]),
])
def test_key_combinations_become_xdotool_names(combo, keys):
    assert parse_keys(combo) == keys


@pytest.mark.parametrize("combo", ["", "  ", "ctrl+"])
def test_unreadable_combinations_are_reported(combo):
    with pytest.raises(ActionError):
        parse_keys(combo)


def test_durations_are_bounded_not_clamped():
    assert seconds(2, "wait") == 2.0
    assert seconds("0.5", "wait") == 0.5
    for bad in (-1, 301, "long", None):
        with pytest.raises(ActionError):
            seconds(bad, "wait")

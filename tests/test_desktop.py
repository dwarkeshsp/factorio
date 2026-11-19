import pytest

from factoriobench.desktop import ActionError, Desktop, parse_keys, seconds


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


class Recorder(Desktop):
    """A Desktop that records the xdotool calls instead of making them."""

    def __init__(self):
        self.size = (1280, 720)
        self.move_settle = 0.0
        self.calls = []
        from factoriobench.clock import WallClock
        self.clock = WallClock()

    def _x(self, *args):
        self.calls.append(args)
        return ""


def test_a_newline_in_typed_text_presses_enter():
    desktop = Recorder()
    desktop.act("type", {"text": "need coal at the boiler\n"})
    assert desktop.calls == [
        ("type", "--delay", "25", "--", "need coa"), ("type", "--delay", "25", "--", "l at the"),
        ("type", "--delay", "25", "--", " boiler"), ("key", "Return"),
    ]


def test_a_drag_can_follow_a_path_and_out_of_bounds_points_are_refused():
    desktop = Recorder()
    desktop.act("left_click_drag", {"path": [[10, 10], [50, 10], [50, 40]]})
    moves = [call for call in desktop.calls if call[0] == "mousemove"]
    assert moves[0] == ("mousemove", "10", "10") and moves[-1] == ("mousemove", "50", "40")
    assert ("mousedown", "1") in desktop.calls and desktop.calls[-1] == ("mouseup", "1")
    with pytest.raises(ActionError):
        desktop.act("left_click", {"coordinate": [5000, 10]})
    with pytest.raises(ActionError):
        desktop.act("unsupported", {"what": "mouse button 'back'"})

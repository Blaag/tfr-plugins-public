from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from prompt_toolkit.formatted_text import fragment_list_to_text
from tfr.plugin_api import PluginRegistrationError, ScreenClearContext, terminal_cell_width

from tfr_plugins_public.vortex import (
    _vortex_position,
    _vortex_progress,
    plugin,
    render_vortex,
)


@dataclass
class RegisteredEffect:
    handler: Any
    duration_seconds: float
    frames_per_second: float


class RecordingRegistrar:
    def __init__(self) -> None:
        self.effects: list[RegisteredEffect] = []

    def register_screen_clear_effect(
        self,
        handler: Any,
        *,
        duration_seconds: float,
        frames_per_second: float,
    ) -> None:
        self.effects.append(RegisteredEffect(handler, duration_seconds, frames_per_second))


def context(lines: tuple[str, ...], width: int, progress: float) -> ScreenClearContext:
    return ScreenClearContext(lines=lines, width=width, progress=progress, seed=7)


def test_vortex_starts_with_source_text_and_finishes_empty() -> None:
    lines = ("FIRST", "SECOND")

    initial = fragment_list_to_text(render_vortex(context(lines, 8, 0)))
    finished = fragment_list_to_text(render_vortex(context(lines, 8, 1)))

    assert initial == "FIRST\nSECOND"
    assert finished.strip() == ""


def test_activation_front_expands_from_center() -> None:
    lines = ("abcdefghi", "jklmnopqr", "stuvwxyz0")

    early = render_vortex(context(lines, 9, 0.2))
    later = render_vortex(context(lines, 9, 0.5))

    assert fragment_list_to_text(early) != "\n".join(lines)
    assert fragment_list_to_text(later) != fragment_list_to_text(early)


def test_activation_edge_accelerates_gradually_from_rest() -> None:
    activation = 0.58

    assert _vortex_progress(0, activation) == 0
    assert 0 < _vortex_progress(0.1, activation) < _vortex_progress(0.44, activation)
    assert _vortex_progress(0.44, activation) < _vortex_progress(0.58, activation) < 0.2


@pytest.mark.parametrize("progress", [0, 0.2, 0.4])
def test_vortex_preserves_source_styles(progress: float) -> None:
    source = ScreenClearContext(
        lines=("ABCD",),
        width=4,
        progress=progress,
        seed=7,
        styled_lines=((("fg:#d70000", "AB"), ("fg:#5f87af bold", "CD")),),
    )

    rendered = render_vortex(source)
    visible_styles = {style for style, text in rendered if text.strip()}

    assert visible_styles
    assert visible_styles <= {"fg:#d70000", "fg:#5f87af bold"}


def test_orbit_can_leave_and_reenter_a_rectangular_viewport() -> None:
    turns = 2.25
    source_x = 4.75

    outside_x, outside_y = _vortex_position(
        source_x,
        0,
        1 / (4 * turns),
        turns=turns,
        direction=1,
    )
    returned_x, returned_y = _vortex_position(
        source_x,
        0,
        1 / (2 * turns),
        turns=turns,
        direction=1,
    )

    assert abs(outside_x) < 1
    assert abs(outside_y) > 1.5
    assert returned_x < -3.5
    assert abs(returned_y) < 1


@pytest.mark.parametrize("progress", [0, 0.2, 0.5, 0.8, 1])
def test_vortex_respects_terminal_width_for_wide_and_combining_text(progress: float) -> None:
    rendered = render_vortex(context(("界A", "e\u0301x"), 3, progress))

    lines = fragment_list_to_text(rendered).split("\n")
    assert len(lines) == 2
    assert all(terminal_cell_width(line) <= 3 for line in lines)


def test_plugin_registers_default_timing() -> None:
    registrar = RecordingRegistrar()

    plugin.register(registrar, {})

    assert len(registrar.effects) == 1
    assert registrar.effects[0].duration_seconds == 2.8
    assert registrar.effects[0].frames_per_second == 24


def test_plugin_accepts_slow_clear_duration() -> None:
    registrar = RecordingRegistrar()

    plugin.register(registrar, {"duration_seconds": 24})

    assert registrar.effects[0].duration_seconds == 24


def test_plugin_applies_configured_direction_and_turns() -> None:
    registrar = RecordingRegistrar()
    source = context(("abcdef",), 6, 0.4)

    plugin.register(
        registrar,
        {
            "direction": "counterclockwise",
            "duration_seconds": 3,
            "edge_softness": 0.25,
            "frames_per_second": 20,
            "turns": 1.5,
        },
    )

    effect = registrar.effects[0]
    assert effect.duration_seconds == 3
    assert effect.frames_per_second == 20
    assert effect.handler(source) == render_vortex(
        source,
        turns=1.5,
        direction=-1,
        edge_softness=0.25,
    )


@pytest.mark.parametrize(
    "config",
    [
        {"duration_seconds": 0},
        {"duration_seconds": True},
        {"duration_seconds": 61},
        {"frames_per_second": 0},
        {"frames_per_second": "24"},
        {"frames_per_second": 31},
        {"edge_softness": 0},
        {"edge_softness": True},
        {"edge_softness": 0.6},
        {"turns": 0},
        {"turns": float("inf")},
        {"turns": 7},
        {"direction": "down"},
        {"direction": True},
        {"direction": []},
        {"unknown": True},
    ],
)
def test_invalid_configuration_is_rejected(config: dict[str, object]) -> None:
    registrar = RecordingRegistrar()

    with pytest.raises(PluginRegistrationError):
        plugin.register(registrar, config)

    assert registrar.effects == []

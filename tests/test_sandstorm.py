from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from prompt_toolkit.formatted_text import fragment_list_to_text
from tfr.plugin_api import PluginRegistrationError, ScreenClearContext, terminal_cell_width

from tfr_plugins_public.sandstorm import plugin, render_sandstorm


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


def context(
    lines: tuple[str, ...], width: int, progress: float, *, seed: int = 7
) -> ScreenClearContext:
    return ScreenClearContext(lines=lines, width=width, progress=progress, seed=seed)


def test_sandstorm_starts_with_source_text_and_finishes_empty() -> None:
    lines = ("DUST IN THE WIND", "SECOND LINE")

    initial = fragment_list_to_text(render_sandstorm(context(lines, 24, 0)))
    finished = fragment_list_to_text(render_sandstorm(context(lines, 24, 1)))

    assert initial == "\n".join(lines)
    assert finished.strip() == ""


def test_sandstorm_breaks_text_into_wind_driven_earth_tone_particles() -> None:
    source = context(("ABCDEFGHIJKLMNOPQRSTUVWXYZ",) * 3, 30, 0.48)

    rendered = render_sandstorm(source)
    text = fragment_list_to_text(rendered)
    visible_styles = {style for style, fragment in rendered if fragment.strip()}

    assert text != "\n".join(source.lines)
    assert any(glyph in text for glyph in ".:·*")
    assert visible_styles
    assert all(
        any(color in style for color in ("#e5c07b", "#c89b5a", "#8b6f47"))
        for style in visible_styles
    )


def test_direction_and_seed_change_the_particle_field() -> None:
    source = context(("0123456789" * 3,) * 3, 30, 0.42)

    left_to_right = render_sandstorm(source, direction=1)
    right_to_left = render_sandstorm(source, direction=-1)
    another_seed = render_sandstorm(
        context(source.lines, source.width, source.progress, seed=8), direction=1
    )

    assert left_to_right != right_to_left
    assert left_to_right != another_seed


def test_sandstorm_preserves_source_styles_before_the_front_arrives() -> None:
    source = ScreenClearContext(
        lines=("ABCD",),
        width=4,
        progress=0,
        seed=7,
        styled_lines=((('fg:#d70000', "AB"), ("fg:#5f87af bold", "CD")),),
    )

    rendered = render_sandstorm(source)
    visible_styles = {style for style, text in rendered if text.strip()}

    assert visible_styles == {"fg:#d70000", "fg:#5f87af bold"}


@pytest.mark.parametrize("progress", [0, 0.25, 0.5, 0.75, 1])
def test_sandstorm_respects_terminal_width_for_wide_and_combining_text(progress: float) -> None:
    rendered = render_sandstorm(context(("界A", "e\u0301x"), 3, progress))

    lines = fragment_list_to_text(rendered).split("\n")
    assert len(lines) == 2
    assert all(terminal_cell_width(line) <= 3 for line in lines)


def test_plugin_registers_defaults_and_configured_values() -> None:
    defaults = RecordingRegistrar()
    configured = RecordingRegistrar()

    plugin.register(defaults, {})
    plugin.register(
        configured,
        {
            "direction": "right-to-left",
            "duration_seconds": 4,
            "frames_per_second": 20,
            "gust_strength": 2,
        },
    )

    assert len(defaults.effects) == 1
    assert defaults.effects[0].duration_seconds == 2.8
    assert defaults.effects[0].frames_per_second == 24
    assert configured.effects[0].duration_seconds == 4
    assert configured.effects[0].frames_per_second == 20
    source = context(("SANDSTORM",), 20, 0.4)
    assert configured.effects[0].handler(source) == render_sandstorm(
        source,
        direction=-1,
        gust_strength=2,
    )


@pytest.mark.parametrize(
    "config",
    [
        {"duration_seconds": 0},
        {"duration_seconds": True},
        {"duration_seconds": 61},
        {"frames_per_second": 0.5},
        {"frames_per_second": "24"},
        {"frames_per_second": 31},
        {"gust_strength": -0.1},
        {"gust_strength": True},
        {"gust_strength": 4.1},
        {"direction": "up"},
        {"direction": []},
        {"unknown": True},
    ],
)
def test_invalid_configuration_is_rejected(config: dict[str, object]) -> None:
    registrar = RecordingRegistrar()

    with pytest.raises(PluginRegistrationError):
        plugin.register(registrar, config)

    assert registrar.effects == []

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from prompt_toolkit.formatted_text import fragment_list_to_text
from tfr.plugin_api import PluginRegistrationError, ScreenClearContext, terminal_cell_width

from tfr_plugins_public.acid_rain import _corroded_cell, plugin, render_acid_rain


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


def test_acid_rain_starts_with_source_text_and_finishes_empty() -> None:
    lines = ("FIRST LINE", "SECOND LINE")

    initial = fragment_list_to_text(render_acid_rain(context(lines, 16, 0)))
    finished = fragment_list_to_text(render_acid_rain(context(lines, 16, 1)))

    assert initial == "\n".join(lines)
    assert finished.strip() == ""


def test_acid_corrosion_advances_from_top_to_bottom() -> None:
    lines = ("AAAAAAAAAAAA",) * 6

    rendered = fragment_list_to_text(
        render_acid_rain(context(lines, 12, 0.22), density=0)
    ).split("\n")

    assert rendered[0] != lines[0]
    assert rendered[-1] == lines[-1]


def test_corrosion_moves_through_green_rust_and_residue_stages() -> None:
    stages = [
        _corroded_cell("A", progress, 0.2)
        for progress in (0.05, 0.2, 0.38, 0.55, 0.72, 0.86)
    ]

    assert [stage[1] for stage in stages if stage is not None] == ["A", "a", "#", "*", ":", "."]
    assert [stage[0] for stage in stages if stage is not None] == [
        "bold fg:#afff00",
        "fg:#87d700",
        "fg:#5f8700",
        "fg:#5f5f00",
        "fg:#5f3f00",
        "fg:#3f2f00",
    ]


def test_seeded_rain_streaks_are_visible_in_empty_space() -> None:
    source = context((" " * 12,) * 6, 12, 0.35)

    rendered = fragment_list_to_text(
        render_acid_rain(source, density=1, streak_length=4)
    )

    assert any(glyph in rendered for glyph in "│:.")
    assert any(
        color in style
        for style, text in render_acid_rain(source, density=1, streak_length=4)
        if text.strip()
        for color in ("#afff00", "#87d700", "#5f8700")
    )


def test_acid_rain_is_deterministic_for_a_seed() -> None:
    source = context(("CORROSIVE RAIN",) * 4, 20, 0.45)

    first = render_acid_rain(source)
    second = render_acid_rain(source)
    another_seed = render_acid_rain(context(source.lines, 20, 0.45, seed=8))

    assert first == second
    assert first != another_seed


def test_acid_rain_preserves_source_styles_before_contact() -> None:
    source = ScreenClearContext(
        lines=("ABCD",),
        width=4,
        progress=0,
        seed=7,
        styled_lines=((('fg:#d70000', "AB"), ("fg:#5f87af bold", "CD")),),
    )

    rendered = render_acid_rain(source)
    visible_styles = {style for style, text in rendered if text.strip()}

    assert visible_styles == {"fg:#d70000", "fg:#5f87af bold"}


@pytest.mark.parametrize("progress", [0, 0.2, 0.5, 0.8, 1])
def test_acid_rain_respects_terminal_width_for_wide_and_combining_text(progress: float) -> None:
    rendered = render_acid_rain(context(("界A", "e\u0301x"), 3, progress))

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
            "density": 0.8,
            "duration_seconds": 4,
            "frames_per_second": 20,
            "streak_length": 7,
        },
    )

    assert len(defaults.effects) == 1
    assert defaults.effects[0].duration_seconds == 3
    assert defaults.effects[0].frames_per_second == 24
    assert configured.effects[0].duration_seconds == 4
    assert configured.effects[0].frames_per_second == 20
    source = context(("ACID",), 8, 0.4)
    assert configured.effects[0].handler(source) == render_acid_rain(
        source,
        density=0.8,
        streak_length=7,
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
        {"density": -0.1},
        {"density": True},
        {"density": 1.1},
        {"streak_length": 0},
        {"streak_length": True},
        {"streak_length": 13},
        {"unknown": True},
    ],
)
def test_invalid_configuration_is_rejected(config: dict[str, object]) -> None:
    registrar = RecordingRegistrar()

    with pytest.raises(PluginRegistrationError):
        plugin.register(registrar, config)

    assert registrar.effects == []

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from prompt_toolkit.formatted_text import fragment_list_to_text
from tfr.plugin_api import PluginRegistrationError, ScreenClearContext, terminal_cell_width

from tfr_plugins_public.flame import _flame_cell, plugin, render_flame


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
    return ScreenClearContext(lines=lines, width=width, progress=progress)


def test_flame_color_stages_follow_cooling_order() -> None:
    stages = [
        _flame_cell("A", progress, 1) for progress in (0.05, 0.15, 0.35, 0.5, 0.65, 0.75, 0.87)
    ]

    assert [stage[0] for stage in stages if stage is not None] == [
        "",
        "bold fg:#ffd700",
        "bold fg:#ff8700",
        "bold fg:#d70000",
        "fg:#5f0000",
        "fg:#bcbcbc",
        "fg:#626262",
    ]


def test_flame_moves_through_fire_and_smoke_stages() -> None:
    lines = ("BURN BRIGHTLY",)

    dark_red = render_flame(context(lines, 16, 0))
    burning = render_flame(context(lines, 16, 0.4))
    smoke = render_flame(context(lines, 16, 0.72))
    ash = render_flame(context(lines, 16, 0.84))

    assert fragment_list_to_text(dark_red) == "BURN BRIGHTLY"
    burning_styles = {style for style, text, *_ in burning if text.strip()}
    assert len(burning_styles) >= 2
    assert all(
        any(color in style for color in ("#ffd700", "#ff8700", "#d70000", "#5f0000"))
        for style in burning_styles
    )
    assert any("#5f0000" in style or "#bcbcbc" in style for style, _text, *_ in smoke)
    assert any(character in fragment_list_to_text(ash) for character in "*+.")


def test_flame_embers_finish_independently_and_end_empty() -> None:
    lines = ("TOP", "BOTTOM")

    middle = render_flame(context(lines, 8, 0.7))
    finished = render_flame(context(lines, 8, 1))

    middle_text = fragment_list_to_text(middle)
    assert 0 < len(middle_text.replace("\n", "").strip()) < len("TOPBOTTOM")
    assert fragment_list_to_text(finished).strip() == ""


@pytest.mark.parametrize("progress", [0, 0.4, 0.72, 0.84, 1])
def test_flame_preserves_terminal_width_for_wide_and_combining_text(progress: float) -> None:
    rendered = render_flame(context(("界A", "e\u0301x"), 3, progress))

    lines = fragment_list_to_text(rendered).split("\n")
    assert all(terminal_cell_width(line) <= 3 for line in lines)


def test_plugin_registers_one_effect_with_default_timing() -> None:
    registrar = RecordingRegistrar()

    plugin.register(registrar, {})

    assert registrar.effects == [RegisteredEffect(render_flame, 2.1, 24.0)]


def test_plugin_registers_configured_timing() -> None:
    registrar = RecordingRegistrar()

    plugin.register(
        registrar,
        {"duration_seconds": 3, "frames_per_second": 20},
    )

    assert registrar.effects == [RegisteredEffect(render_flame, 3.0, 20.0)]


@pytest.mark.parametrize(
    "config",
    [
        {"duration_seconds": 0},
        {"duration_seconds": -1},
        {"duration_seconds": True},
        {"duration_seconds": "2.1"},
        {"duration_seconds": None},
        {"duration_seconds": float("inf")},
        {"duration_seconds": 11},
        {"frames_per_second": 0},
        {"frames_per_second": True},
        {"frames_per_second": "24"},
        {"frames_per_second": float("nan")},
        {"frames_per_second": 31},
        {"unknown": True},
    ],
)
def test_invalid_configuration_is_rejected(config: dict[str, object]) -> None:
    registrar = RecordingRegistrar()

    with pytest.raises(PluginRegistrationError):
        plugin.register(registrar, config)

    assert registrar.effects == []

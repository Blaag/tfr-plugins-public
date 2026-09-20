from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from prompt_toolkit.formatted_text import fragment_list_to_text
from tfr.plugin_api import PluginRegistrationError, ScreenClearContext, terminal_cell_width

from tfr_plugins_public.water_ripple import _ripple_cell, plugin, render_water_ripple


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


def test_water_ripple_starts_with_source_text_and_finishes_empty() -> None:
    lines = ("FIRST LINE", "SECOND LINE")

    initial = fragment_list_to_text(render_water_ripple(context(lines, 16, 0)))
    finished = fragment_list_to_text(render_water_ripple(context(lines, 16, 1)))

    assert initial == "\n".join(lines)
    assert finished.strip() == ""


def test_ripple_dissolves_from_the_center_outward() -> None:
    lines = ("AAAAAAAAA",) * 5

    rendered = fragment_list_to_text(render_water_ripple(context(lines, 9, 0.2))).split("\n")

    assert rendered[0][0] == "A"
    assert rendered[2][4] != "A"
    assert rendered[2][4] in "█▓▒░."


def test_ripple_uses_decreasing_density_glyphs() -> None:
    stages = [_ripple_cell("A", progress) for progress in (0.05, 0.2, 0.36, 0.53, 0.7, 0.85)]

    assert [stage[1] for stage in stages if stage is not None] == ["A", "█", "▓", "▒", "░", "."]
    assert all("fg:#" in stage[0] for stage in stages if stage is not None)


def test_water_ripple_preserves_source_styles_before_the_wave_arrives() -> None:
    source = ScreenClearContext(
        lines=("ABCD",),
        width=4,
        progress=0,
        seed=7,
        styled_lines=((('fg:#d70000', "AB"), ("fg:#5f87af bold", "CD")),),
    )

    rendered = render_water_ripple(source)
    visible_styles = {style for style, text in rendered if text.strip()}

    assert visible_styles == {"fg:#d70000", "fg:#5f87af bold"}


@pytest.mark.parametrize("progress", [0, 0.2, 0.5, 0.8, 1])
def test_water_ripple_respects_terminal_width_for_wide_and_combining_text(
    progress: float,
) -> None:
    rendered = render_water_ripple(context(("界A", "e\u0301x"), 3, progress))

    lines = fragment_list_to_text(rendered).split("\n")
    assert len(lines) == 2
    assert all(terminal_cell_width(line) <= 3 for line in lines)


def test_plugin_registers_default_and_configured_timing() -> None:
    defaults = RecordingRegistrar()
    configured = RecordingRegistrar()

    plugin.register(defaults, {})
    plugin.register(configured, {"duration_seconds": 4, "frames_per_second": 20})

    assert defaults.effects == [RegisteredEffect(render_water_ripple, 2.6, 24.0)]
    assert configured.effects == [RegisteredEffect(render_water_ripple, 4.0, 20.0)]


@pytest.mark.parametrize(
    "config",
    [
        {"duration_seconds": 0},
        {"duration_seconds": True},
        {"duration_seconds": 61},
        {"frames_per_second": 0.5},
        {"frames_per_second": "24"},
        {"frames_per_second": 31},
        {"unknown": True},
    ],
)
def test_invalid_configuration_is_rejected(config: dict[str, object]) -> None:
    registrar = RecordingRegistrar()

    with pytest.raises(PluginRegistrationError):
        plugin.register(registrar, config)

    assert registrar.effects == []

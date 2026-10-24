from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from prompt_toolkit.formatted_text import fragment_list_to_text
from tfr.plugin_api import PluginRegistrationError, ScreenClearContext, terminal_cell_width

from tfr_plugins_public.spotlight import _spotlights, plugin, render_spotlight


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


def test_spotlight_starts_with_source_text_and_finishes_empty() -> None:
    lines = ("FIRST LINE", "SECOND LINE")

    initial = fragment_list_to_text(render_spotlight(context(lines, 16, 0)))
    finished = fragment_list_to_text(render_spotlight(context(lines, 16, 1)))

    assert initial == "\n".join(lines)
    assert finished.strip() == ""


def test_seeded_spotlights_vary_size_and_follow_diagonal_paths() -> None:
    source = context(("X" * 40,) * 12, 40, 0, seed=11)

    lights = _spotlights(source, 3)

    def outside(center: tuple[float, float]) -> bool:
        return center[0] < 0 or center[0] > 40 or center[1] < 0 or center[1] > 24

    assert len(lights) == 3
    assert len({light.radius for light in lights}) == 3
    assert all(abs(light.direction_x) >= 0.1 for light in lights)
    assert all(abs(light.direction_y) >= 0.1 for light in lights)
    assert all(outside(light.center(0)) for light in lights)
    assert all(outside(light.center(1)) for light in lights)


def test_spotlights_reveal_source_styles_and_dim_their_feathered_edges() -> None:
    source = ScreenClearContext(
        lines=("X" * 50,) * 14,
        width=50,
        progress=0.5,
        seed=19,
        styled_lines=tuple((("fg:#d70000 bold", "X" * 50),) for _ in range(14)),
    )

    frames = [
        render_spotlight(
            ScreenClearContext(
                lines=source.lines,
                width=source.width,
                progress=progress,
                seed=source.seed,
                styled_lines=source.styled_lines,
            )
        )
        for progress in (0.35, 0.45, 0.55, 0.65, 0.75)
    ]

    assert any(style == "fg:#d70000 bold" and text for frame in frames for style, text in frame)
    assert any("dim" in style and text for frame in frames for style, text in frame)


def test_spotlight_is_deterministic_for_a_seed() -> None:
    source = context(("FOLLOW THE LIGHT",) * 8, 30, 0.52)

    assert render_spotlight(source) == render_spotlight(source)
    assert render_spotlight(source) != render_spotlight(
        context(source.lines, source.width, source.progress, seed=8)
    )


def test_spotlight_respects_terminal_width_for_wide_and_combining_text() -> None:
    for progress in (0, 0.1, 0.4, 0.7, 1):
        rendered = render_spotlight(context(("界A", "e\u0301x"), 3, progress))
        lines = fragment_list_to_text(rendered).split("\n")

        assert len(lines) == 2
        assert all(terminal_cell_width(line) <= 3 for line in lines)


def test_plugin_registers_defaults_and_configured_values() -> None:
    defaults = RecordingRegistrar()
    configured = RecordingRegistrar()

    plugin.register(defaults, {})
    plugin.register(
        configured,
        {"duration_seconds": 4.5, "frames_per_second": 20, "spotlight_count": 5},
    )

    assert defaults.effects[0].duration_seconds == 3.6
    assert defaults.effects[0].frames_per_second == 24
    assert configured.effects[0].duration_seconds == 4.5
    assert configured.effects[0].frames_per_second == 20
    source = context(("LIGHT",) * 5, 12, 0.5)
    assert configured.effects[0].handler(source) == render_spotlight(source, spotlight_count=5)


@pytest.mark.parametrize(
    "config",
    [
        {"duration_seconds": 0},
        {"duration_seconds": True},
        {"duration_seconds": 61},
        {"frames_per_second": 0.5},
        {"frames_per_second": "24"},
        {"frames_per_second": 31},
        {"spotlight_count": 1},
        {"spotlight_count": True},
        {"spotlight_count": 6},
        {"unknown": True},
    ],
)
def test_invalid_configuration_is_rejected(config: dict[str, object]) -> None:
    registrar = RecordingRegistrar()

    with pytest.raises(PluginRegistrationError):
        plugin.register(registrar, config)

    assert registrar.effects == []

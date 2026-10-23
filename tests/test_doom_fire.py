from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from prompt_toolkit.formatted_text import fragment_list_to_text
from tfr.plugin_api import PluginRegistrationError, ScreenClearContext, terminal_cell_width

from tfr_plugins_public.doom_fire import (
    _DoomFireRenderer,
    _fire_cell,
    plugin,
    render_doom_fire,
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


def context(
    lines: tuple[str, ...], width: int, progress: float, *, seed: int = 7
) -> ScreenClearContext:
    return ScreenClearContext(lines=lines, width=width, progress=progress, seed=seed)


def test_doom_fire_starts_with_source_text_and_finishes_empty() -> None:
    lines = ("TOP LINE", "BOTTOM LINE")

    initial = fragment_list_to_text(render_doom_fire(context(lines, 16, 0)))
    finished = fragment_list_to_text(render_doom_fire(context(lines, 16, 1)))

    assert initial == "\n".join(lines)
    assert finished.strip() == ""


def test_cellular_fire_ignites_from_source_text_and_propagates_upward() -> None:
    lines = ("", "", "", "        X", "")

    rendered = fragment_list_to_text(render_doom_fire(context(lines, 17, 0.18))).split("\n")

    assert rendered[-1].strip() == ""
    assert any(glyph in rendered[3] for glyph in ".:*oO#@")
    assert any(glyph in rendered[2] for glyph in ".:*oO#@")


def test_sparse_source_does_not_create_a_full_width_bottom_fire() -> None:
    lines = ("", "", "        .", "")

    rendered = fragment_list_to_text(render_doom_fire(context(lines, 17, 0.12))).split("\n")

    assert rendered[-1].strip() == ""
    assert sum(character in ".:*oO#@" for line in rendered for character in line) < 8


def test_empty_source_does_not_create_artificial_fire() -> None:
    lines = ("", "", "", "")

    rendered = fragment_list_to_text(render_doom_fire(context(lines, 17, 0.4)))

    assert rendered.strip() == ""


def test_dense_row_ignites_irregularly_instead_of_as_a_solid_front() -> None:
    line = "X" * 40

    rendered = fragment_list_to_text(render_doom_fire(context((line,), 40, 0.04)))

    assert "X" in rendered
    assert any(glyph in rendered for glyph in ".:*oO#@")


def test_fire_footprint_depends_on_source_density() -> None:
    sparse = fragment_list_to_text(render_doom_fire(context(("X",) * 5, 20, 0.25)))
    dense = fragment_list_to_text(render_doom_fire(context(("X" * 20,) * 5, 20, 0.25)))

    fire_glyphs = set(".:*oO#@")
    assert sum(character in fire_glyphs for character in sparse) < sum(
        character in fire_glyphs for character in dense
    )


def test_doom_fire_uses_classic_intensity_colors_and_glyphs() -> None:
    stages = [_fire_cell(value) for value in (1, 5, 10, 16, 23, 29, 36)]

    assert stages == [
        ("fg:#5f0000", "."),
        ("fg:#870000", ":"),
        ("fg:#d70000", "*"),
        ("fg:#ff5f00", "o"),
        ("fg:#ffaf00", "O"),
        ("bold fg:#ffd700", "#"),
        ("bold fg:#ffffd7", "@"),
    ]


def test_consumed_text_does_not_reappear_as_the_fire_cools() -> None:
    renderer = _DoomFireRenderer(duration_seconds=3.2, frames_per_second=24)
    source = ("X" * 18,) * 6

    middle = fragment_list_to_text(renderer(context(source, 18, 0.55)))
    cooling = fragment_list_to_text(renderer(context(source, 18, 0.9)))

    assert middle.count("X") < 18 * 6
    assert cooling.count("X") <= middle.count("X")


def test_doom_fire_is_deterministic_for_a_seed() -> None:
    source = context(("CELLULAR FIRE",) * 4, 20, 0.5)

    first = render_doom_fire(source)
    second = render_doom_fire(source)
    another_seed = render_doom_fire(context(source.lines, 20, 0.5, seed=8))

    assert first == second
    assert first != another_seed


def test_doom_fire_preserves_source_styles_before_ignition() -> None:
    source = ScreenClearContext(
        lines=("ABCD",),
        width=4,
        progress=0,
        seed=7,
        styled_lines=((('fg:#d70000', "AB"), ("fg:#5f87af bold", "CD")),),
    )

    rendered = render_doom_fire(source)
    visible_styles = {style for style, text in rendered if text.strip()}

    assert visible_styles == {"fg:#d70000", "fg:#5f87af bold"}


@pytest.mark.parametrize("progress", [0, 0.2, 0.5, 0.8, 1])
def test_doom_fire_respects_terminal_width_for_wide_and_combining_text(progress: float) -> None:
    rendered = render_doom_fire(context(("界A", "e\u0301x"), 3, progress))

    lines = fragment_list_to_text(rendered).split("\n")
    assert len(lines) == 2
    assert all(terminal_cell_width(line) <= 3 for line in lines)


def test_plugin_registers_defaults_and_configured_timing() -> None:
    defaults = RecordingRegistrar()
    configured = RecordingRegistrar()

    plugin.register(defaults, {})
    plugin.register(configured, {"duration_seconds": 5, "frames_per_second": 20})

    assert len(defaults.effects) == 1
    assert defaults.effects[0].duration_seconds == 3.2
    assert defaults.effects[0].frames_per_second == 24
    assert isinstance(defaults.effects[0].handler, _DoomFireRenderer)
    assert configured.effects[0].duration_seconds == 5
    assert configured.effects[0].frames_per_second == 20


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

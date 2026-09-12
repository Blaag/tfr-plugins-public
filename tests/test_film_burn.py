from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from prompt_toolkit.formatted_text import fragment_list_to_text
from tfr.plugin_api import PluginRegistrationError, ScreenClearContext, terminal_cell_width

from tfr_plugins_public.film_burn import (
    _assign_ignition_times,
    _burned_cell,
    _Cell,
    _FilmBurnRenderer,
    _Hole,
    _ignition_time,
    _source_cells,
    plugin,
    render_film_burn,
)


@dataclass
class RegisteredEffect:
    handler: Any
    duration_seconds: float
    frames_per_second: float
    is_complete: Any = None


class RecordingRegistrar:
    def __init__(self) -> None:
        self.effects: list[RegisteredEffect] = []

    def register_screen_clear_effect(
        self,
        handler: Any,
        *,
        duration_seconds: float,
        frames_per_second: float,
        is_complete: Any = None,
    ) -> None:
        self.effects.append(
            RegisteredEffect(handler, duration_seconds, frames_per_second, is_complete)
        )


def context(
    lines: tuple[str, ...],
    width: int,
    progress: float,
    *,
    elapsed_seconds: float | None = None,
    seed: int = 7,
    styled_lines: tuple[tuple[tuple[str, str], ...], ...] = (),
) -> ScreenClearContext:
    return ScreenClearContext(
        lines=lines,
        width=width,
        progress=progress,
        seed=seed,
        elapsed_seconds=elapsed_seconds,
        styled_lines=styled_lines,
    )


def renderer(**overrides: object) -> _FilmBurnRenderer:
    values: dict[str, object] = {
        "minimum_holes": 3,
        "maximum_holes": 7,
        "maximum_appearance_delay_seconds": 3.0,
        "minimum_growth_duration_seconds": 3.5,
        "maximum_growth_duration_seconds": 6.0,
        "burn_duration_seconds": 0.7,
        "frames_per_second": 24.0,
    }
    values.update(overrides)
    return _FilmBurnRenderer(**values)  # type: ignore[arg-type]


def test_first_hole_ignites_immediately_without_deleting_text() -> None:
    source = context(("FILM BURN",), 9, 0)

    frame = render_film_burn(source)

    assert fragment_list_to_text(frame) == "FILM BURN"
    assert sum("#ff8700" in style for style, text in frame if text.strip()) == 1


def test_holes_use_seeded_count_appearance_and_growth_ranges() -> None:
    first = renderer(
        minimum_holes=5,
        maximum_holes=5,
        maximum_appearance_delay_seconds=2,
        minimum_growth_duration_seconds=2,
        maximum_growth_duration_seconds=4,
    )
    second = renderer(
        minimum_holes=5,
        maximum_holes=5,
        maximum_appearance_delay_seconds=2,
        minimum_growth_duration_seconds=2,
        maximum_growth_duration_seconds=4,
    )
    source = context(("X" * 20,) * 8, 20, 0)

    first(source)
    second(source)

    assert first._state is not None
    assert second._state is not None
    assert first._state.holes == second._state.holes
    assert len(first._state.holes) == 5
    assert first._state.holes[0].appearance_time == 0
    assert all(0 <= hole.appearance_time <= 2 for hole in first._state.holes)
    assert all(2 <= hole.growth_duration <= 4 for hole in first._state.holes)


def test_front_keeps_expanding_while_earlier_cells_finish_burning() -> None:
    hole = _Hole(
        x=0,
        y=0,
        appearance_time=0,
        growth_duration=4,
        maximum_radius=10,
        primary_phase=0,
        secondary_phase=0,
    )
    center = _Cell(0, 0, 1, "A", "", ignition_time=0)
    outer = _Cell(0, 10, 1, "B", "")
    outer.ignition_time = _ignition_time(outer, hole)
    elapsed_seconds = outer.ignition_time + 0.01

    assert _burned_cell(center, elapsed_seconds, 0.5) is None
    assert _burned_cell(outer, elapsed_seconds, 0.5) == (
        "bold fg:#ff8700",
        "B",
    )


@pytest.mark.parametrize(
    ("elapsed_seconds", "expected_style"),
    [
        (0.1, "italic bold fg:#ff8700"),
        (0.3, "italic fg:#af0000"),
        (0.5, "italic fg:#5f2f17"),
        (0.7, "italic fg:#000000"),
    ],
)
def test_character_cools_through_burn_stages(
    elapsed_seconds: float,
    expected_style: str,
) -> None:
    cell = _Cell(0, 0, 1, "A", "fg:#ffffff italic", ignition_time=0)

    assert _burned_cell(cell, elapsed_seconds, 0.8) == (expected_style, "A")


def test_overlapping_holes_use_earliest_front_and_age_independently() -> None:
    first_cell = _Cell(0, 0, 1, "A", "")
    second_cell = _Cell(2, 4, 1, "B", "")
    holes = (
        _Hole(0, 0, 0, 10, 10, 0, 0),
        _Hole(2, 2, 1, 3, 5, 0, 0),
    )

    assert _ignition_time(second_cell, holes[1]) < _ignition_time(second_cell, holes[0])

    _assign_ignition_times([first_cell, second_cell], holes)

    assert first_cell.ignition_time == 0
    assert second_cell.ignition_time == _ignition_time(second_cell, holes[1])
    assert _burned_cell(first_cell, 1.1, 0.5) is None
    assert _burned_cell(second_cell, 1.1, 0.5) == (
        "bold fg:#ff8700",
        "B",
    )


def test_renderer_completes_after_slowest_possible_burn() -> None:
    effect = renderer(
        minimum_holes=3,
        maximum_holes=3,
        maximum_appearance_delay_seconds=1,
        minimum_growth_duration_seconds=2,
        maximum_growth_duration_seconds=2,
        burn_duration_seconds=0.4,
    )
    source = ("X" * 20,) * 8

    finished = effect(context(source, 20, 1, elapsed_seconds=3.5))

    assert finished == []
    assert effect.is_complete() is True


def test_renderer_continues_past_registered_nominal_duration() -> None:
    effect = renderer(
        minimum_holes=1,
        maximum_holes=1,
        maximum_appearance_delay_seconds=0,
        minimum_growth_duration_seconds=2,
        maximum_growth_duration_seconds=6,
        burn_duration_seconds=0.4,
    )
    source = ("X" * 20,) * 8
    effect(context(source, 20, 0, elapsed_seconds=0, seed=19))
    assert effect._state is not None
    actual_completion = max(cell.ignition_time for cell in effect._state.cells) + 0.4

    assert actual_completion > effect.duration_seconds
    assert effect(context(source, 20, 1, elapsed_seconds=effect.duration_seconds, seed=19))
    assert effect.is_complete() is False
    assert effect(context(source, 20, 1, elapsed_seconds=actual_completion + 0.01, seed=19)) == []
    assert effect.is_complete() is True


def test_renderer_continues_after_progress_one_without_elapsed_time() -> None:
    effect = renderer(
        minimum_holes=2,
        maximum_holes=2,
        maximum_appearance_delay_seconds=1,
        minimum_growth_duration_seconds=1,
        maximum_growth_duration_seconds=2,
        burn_duration_seconds=0.2,
        frames_per_second=10,
    )
    source = context(("X" * 10,) * 4, 10, 1)

    for _ in range(30):
        effect(source)
        if effect.is_complete():
            break

    assert effect.is_complete() is True


@pytest.mark.parametrize("elapsed_seconds", [0, 1, 2, 4, 8])
def test_frames_preserve_unicode_width_and_height(elapsed_seconds: float) -> None:
    lines = ("界A", "e\u0301x")
    source = context(
        lines,
        3,
        min(1, elapsed_seconds / 4.2),
        elapsed_seconds=elapsed_seconds,
        styled_lines=((("fg:#d70000", "界A"),), (("underline", "e\u0301x"),)),
    )

    frame = render_film_burn(source)
    rendered_lines = fragment_list_to_text(frame).split("\n") if frame else []

    assert len(rendered_lines) in {0, 2}
    assert all(terminal_cell_width(line) <= 3 for line in rendered_lines)


def test_styled_whitespace_and_trailing_background_are_preserved() -> None:
    source = context(
        ("A B ",),
        4,
        0,
        styled_lines=((("fg:ansired bg:#440000 reverse class:burn", "A B "),),),
    )

    frame = render_film_burn(source)

    assert fragment_list_to_text(frame) == "A B "
    assert all(
        "bg:#440000" in style and "reverse" in style and "class:burn" in style
        for style, text in frame
        if text
    )


def test_foreground_only_whitespace_does_not_control_ignition_or_completion() -> None:
    source = context(
        ("A B ",),
        4,
        0,
        styled_lines=((("fg:#d70000", "A B "),),),
    )
    effect = renderer(minimum_holes=1, maximum_holes=1)

    frame = effect(source)

    assert effect._state is not None
    assert [cell.character for cell in effect._state.cells if cell.controls_completion] == [
        "A",
        "B",
    ]
    assert all(
        not cell.controls_completion for cell in effect._state.cells if cell.character.isspace()
    )
    assert fragment_list_to_text(frame) == "A B "
    assert any("#ff8700" in style for style, text in frame if text.strip())


@pytest.mark.parametrize("character", [" \ufe0f", " \u200d", " \u0301"])
def test_styled_whitespace_with_zero_width_marks_does_not_control_completion(
    character: str,
) -> None:
    source = context(
        (character, "A"),
        2,
        0,
        styled_lines=((("fg:#d70000", character),), (("fg:#d70000", "A"),)),
    )

    cells = _source_cells(source)

    assert [cell.controls_completion for cell in cells] == [False, True]


@pytest.mark.parametrize("suffix", ["\u200b" * 10_000, "\u0301" * 10_000])
def test_zero_width_sequences_are_bounded(suffix: str) -> None:
    source = context(("A" + suffix,), 1, 0)

    cells = _source_cells(source)
    frame = render_film_burn(source)

    assert len(cells) == 1
    assert len(cells[0].character) <= 8
    assert len(fragment_list_to_text(frame)) <= 8


@pytest.mark.parametrize(
    "text",
    [
        "\u200b" * 10_000 + "A",
        "\u0301" * 10_000 + "A",
        "\u200b" * 129 + "A" + "\u200b" * 129,
        "👩\u200d" * 10_000 + "💻",
    ],
)
def test_bounded_input_retains_a_visible_grapheme(text: str) -> None:
    source = context((text,), 8, 0)

    cells = _source_cells(source)
    frame = render_film_burn(source)

    assert cells
    assert any(terminal_cell_width(cell.character) > 0 for cell in cells)
    assert terminal_cell_width(fragment_list_to_text(frame)) <= 8


def test_plugin_registers_configured_effect() -> None:
    registrar = RecordingRegistrar()

    plugin.register(
        registrar,
        {
            "minimum_holes": 2,
            "maximum_holes": 6,
            "maximum_appearance_delay_seconds": 2,
            "minimum_growth_duration_seconds": 3,
            "maximum_growth_duration_seconds": 5,
            "burn_duration_seconds": 0.8,
            "frames_per_second": 20,
        },
    )

    assert len(registrar.effects) == 1
    effect = registrar.effects[0]
    assert effect.duration_seconds == 3.8
    assert effect.frames_per_second == 20
    assert callable(effect.is_complete)
    assert effect.handler.minimum_holes == 2
    assert effect.handler.maximum_holes == 6


@pytest.mark.parametrize(
    "config",
    [
        {"minimum_holes": 0},
        {"minimum_holes": True},
        {"minimum_holes": 1.5},
        {"maximum_holes": 1, "minimum_holes": 2},
        {"maximum_holes": 33},
        {"maximum_appearance_delay_seconds": -0.1},
        {"maximum_appearance_delay_seconds": 31},
        {"minimum_growth_duration_seconds": 0},
        {"maximum_growth_duration_seconds": 0},
        {
            "minimum_growth_duration_seconds": 4,
            "maximum_growth_duration_seconds": 3,
        },
        {
            "maximum_appearance_delay_seconds": 4,
            "minimum_growth_duration_seconds": 3,
        },
        {"maximum_growth_duration_seconds": 61},
        {"burn_duration_seconds": 0},
        {"burn_duration_seconds": 11},
        {
            "minimum_growth_duration_seconds": 55,
            "maximum_growth_duration_seconds": 55,
            "burn_duration_seconds": 6,
        },
        {"frames_per_second": 0.9},
        {"frames_per_second": 31},
        {"frames_per_second": True},
        {"frames_per_second": float("inf")},
        {"unknown": True},
    ],
)
def test_invalid_configuration_is_rejected(config: dict[str, object]) -> None:
    registrar = RecordingRegistrar()

    with pytest.raises(PluginRegistrationError):
        plugin.register(registrar, config)

    assert registrar.effects == []

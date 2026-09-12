from __future__ import annotations

import math
import random
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tfr.plugin_api import (
    MAX_SCREEN_CLEAR_DURATION_SECONDS,
    PLUGIN_API_VERSION,
    PluginRegistrar,
    PluginRegistrationError,
    ScreenClearContext,
    terminal_cell_width,
)

_FIELDS = frozenset(
    {
        "burn_duration_seconds",
        "frames_per_second",
        "maximum_appearance_delay_seconds",
        "maximum_growth_duration_seconds",
        "maximum_holes",
        "minimum_growth_duration_seconds",
        "minimum_holes",
    }
)
_CELL_ASPECT = 0.5
_EDGE_IRREGULARITY = 0.12
_MAX_GRAPHEME_CODEPOINTS = 8
_BURN_COLORS = ("#ff8700", "#af0000", "#5f2f17", "#000000")
_BARE_FOREGROUND_COLORS = frozenset(
    {
        "black",
        "blue",
        "brightblack",
        "brightblue",
        "brightcyan",
        "brightgreen",
        "brightmagenta",
        "brightred",
        "brightwhite",
        "brightyellow",
        "cyan",
        "default",
        "green",
        "magenta",
        "red",
        "white",
        "yellow",
    }
)


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PluginRegistrationError(f"film_burn {field} must be a number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as error:
        raise PluginRegistrationError(f"film_burn {field} must be finite") from error
    if not math.isfinite(result):
        raise PluginRegistrationError(f"film_burn {field} must be finite")
    return result


def _positive_number(value: object, field: str) -> float:
    result = _number(value, field)
    if result <= 0:
        raise PluginRegistrationError(f"film_burn {field} must be positive")
    return result


def _non_negative_number(value: object, field: str) -> float:
    result = _number(value, field)
    if result < 0:
        raise PluginRegistrationError(f"film_burn {field} cannot be negative")
    return result


def _positive_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PluginRegistrationError(f"film_burn {field} must be a positive integer")
    return value


@dataclass(slots=True)
class _Cell:
    row: int
    column: int
    width: int
    character: str
    style: str
    controls_completion: bool = True
    ignition_time: float = math.inf


@dataclass(frozen=True, slots=True)
class _Hole:
    x: float
    y: float
    appearance_time: float
    growth_duration: float
    maximum_radius: float
    primary_phase: float
    secondary_phase: float


@dataclass(slots=True)
class _FilmBurnState:
    cells: list[_Cell]
    holes: tuple[_Hole, ...]
    elapsed_seconds: float = 0.0
    complete: bool = False


def _graphemes(text: str) -> list[str]:
    graphemes: list[str] = []
    cluster = ""
    cluster_has_width = False
    for character in text:
        character_has_width = terminal_cell_width(character) > 0
        joins_cluster = bool(cluster) and (
            unicodedata.combining(character) != 0
            or character == "\u200d"
            or cluster.endswith("\u200d")
            or "\ufe00" <= character <= "\ufe0f"
            or "\U0001f3fb" <= character <= "\U0001f3ff"
            or "\U000e0020" <= character <= "\U000e007f"
            or not cluster_has_width
            or (
                "\U0001f1e6" <= character <= "\U0001f1ff"
                and all("\U0001f1e6" <= item <= "\U0001f1ff" for item in cluster)
                and len(cluster) % 2 == 1
            )
        )
        if cluster and not joins_cluster:
            graphemes.append(cluster)
            cluster = ""
            cluster_has_width = False
        cluster += character
        cluster_has_width = cluster_has_width or character_has_width
    if cluster:
        graphemes.append(cluster)
    return graphemes


def _styled_graphemes(fragments: tuple[tuple[str, str], ...]) -> list[tuple[str, str]]:
    codepoints = [(style, character) for style, text in fragments for character in text]
    result: list[tuple[str, str]] = []
    offset = 0
    for grapheme in _graphemes("".join(character for _style, character in codepoints)):
        cluster = codepoints[offset : offset + len(grapheme)]
        style = next(
            (
                candidate_style
                for candidate_style, character in cluster
                if terminal_cell_width(character) > 0
            ),
            cluster[0][0],
        )
        result.append((style, grapheme))
        offset += len(grapheme)
    return result


def _bounded_fragments(
    fragments: tuple[tuple[str, str], ...],
    maximum_characters: int,
) -> tuple[tuple[str, str], ...]:
    total_characters = sum(len(text) for _style, text in fragments)
    if total_characters <= maximum_characters:
        return fragments
    prefix_target = maximum_characters // 3
    suffix_target = maximum_characters // 3
    middle_target = maximum_characters - prefix_target - suffix_target
    prefix_length = prefix_target
    prefix: list[tuple[str, str]] = []
    for style, text in fragments:
        if prefix_length <= 0:
            break
        selected = text[:prefix_length]
        if selected:
            prefix.append((style, selected))
            prefix_length -= len(selected)
    middle: list[tuple[str, str]] = []
    offset = 0
    middle_end = total_characters - suffix_target
    for style, text in fragments:
        start = max(0, prefix_target - offset)
        end = min(len(text), middle_end - offset)
        if start < end and middle_target > 0:
            selected = "".join(
                character for character in text[start:end] if terminal_cell_width(character) > 0
            )[:middle_target]
            if selected:
                middle.append((style, selected))
                middle_target -= len(selected)
        offset += len(text)
        if middle_target <= 0 or offset >= middle_end:
            break
    suffix_length = suffix_target
    suffix: list[tuple[str, str]] = []
    for style, text in reversed(fragments):
        if suffix_length <= 0:
            break
        selected = text[-suffix_length:]
        if selected:
            suffix.append((style, selected))
            suffix_length -= len(selected)
    suffix.reverse()
    return tuple(prefix + middle + suffix)


def _truncate_grapheme(grapheme: str, maximum_characters: int) -> str:
    if len(grapheme) <= maximum_characters:
        return grapheme
    result = grapheme[:maximum_characters]
    if terminal_cell_width(result) <= 0 and terminal_cell_width(grapheme) > 0:
        visible = next(character for character in grapheme if terminal_cell_width(character) > 0)
        result = result[: maximum_characters - 1] + visible
    return result.rstrip("\u200d")


def _controls_completion(grapheme: str) -> bool:
    return any(
        terminal_cell_width(character) > 0 and not character.isspace() for character in grapheme
    )


def _source_cells(context: ScreenClearContext) -> list[_Cell]:
    cells: list[_Cell] = []
    styled_lines = context.styled_lines or tuple((("", line),) for line in context.lines)
    maximum_text_characters = max(1, len(context.lines) * (context.width + 1) * 4)
    grid_characters = len(context.lines) * context.width + max(0, len(context.lines) - 1)
    remaining_extra_characters = max(0, maximum_text_characters - grid_characters)
    for row, fragments in enumerate(styled_lines):
        bounded_fragments = _bounded_fragments(
            fragments,
            max(256, context.width * 32),
        )
        column = 0
        for style, character in _styled_graphemes(bounded_fragments):
            character = _truncate_grapheme(
                character,
                min(_MAX_GRAPHEME_CODEPOINTS, 1 + remaining_extra_characters),
            )
            width = terminal_cell_width(character)
            if width <= 0:
                if cells and cells[-1].row == row and remaining_extra_characters:
                    attachment = character[:remaining_extra_characters]
                    cells[-1].character += attachment
                    remaining_extra_characters -= len(attachment)
                continue
            if column + width > context.width:
                break
            controls_completion = _controls_completion(character)
            if controls_completion or style.strip():
                cells.append(
                    _Cell(
                        row,
                        column,
                        width,
                        character,
                        style,
                        controls_completion=controls_completion,
                    )
                )
                remaining_extra_characters -= max(0, len(character) - 1)
            column += width
            if column >= context.width:
                break
    return cells


def _maximum_radius(x: float, y: float, width: int, height: int) -> float:
    maximum_x = max(x, max(0.0, (width - 1) * _CELL_ASPECT - x))
    maximum_y = max(y, max(0.0, height - 1 - y))
    return math.hypot(maximum_x, maximum_y) * (1 + _EDGE_IRREGULARITY) + 0.5


def _spread_position(
    rng: random.Random,
    existing: list[tuple[float, float]],
    width: int,
    height: int,
) -> tuple[float, float]:
    pane_width = max(0.0, (width - 1) * _CELL_ASPECT)
    pane_height = max(0.0, height - 1)
    candidates = [(rng.uniform(0, pane_width), rng.uniform(0, pane_height)) for _ in range(12)]
    if not existing:
        return candidates[0]
    return max(
        candidates,
        key=lambda candidate: min(
            math.hypot(candidate[0] - x, candidate[1] - y) for x, y in existing
        ),
    )


def _generate_holes(
    context: ScreenClearContext,
    cells: list[_Cell],
    *,
    minimum_holes: int,
    maximum_holes: int,
    maximum_appearance_delay_seconds: float,
    minimum_growth_duration_seconds: float,
    maximum_growth_duration_seconds: float,
) -> tuple[_Hole, ...]:
    rng = random.Random(context.seed)
    count = rng.randint(minimum_holes, maximum_holes)
    positions: list[tuple[float, float]] = []
    ignition_anchors = [cell for cell in cells if cell.controls_completion]
    if ignition_anchors:
        first = ignition_anchors[rng.randrange(len(ignition_anchors))]
        positions.append(
            (
                (first.column + (first.width - 1) / 2) * _CELL_ASPECT,
                float(first.row),
            )
        )
    else:
        positions.append(_spread_position(rng, [], context.width, len(context.lines)))
    while len(positions) < count:
        positions.append(_spread_position(rng, positions, context.width, len(context.lines)))

    holes: list[_Hole] = []
    for index, (x, y) in enumerate(positions):
        appearance_time = 0.0 if index == 0 else rng.uniform(0, maximum_appearance_delay_seconds)
        holes.append(
            _Hole(
                x=x,
                y=y,
                appearance_time=appearance_time,
                growth_duration=rng.uniform(
                    minimum_growth_duration_seconds,
                    maximum_growth_duration_seconds,
                ),
                maximum_radius=_maximum_radius(
                    x,
                    y,
                    context.width,
                    len(context.lines),
                ),
                primary_phase=rng.uniform(0, math.tau),
                secondary_phase=rng.uniform(0, math.tau),
            )
        )
    return tuple(holes)


def _ignition_time(cell: _Cell, hole: _Hole) -> float:
    x = (cell.column + (cell.width - 1) / 2) * _CELL_ASPECT
    dx = x - hole.x
    dy = cell.row - hole.y
    distance = math.hypot(dx, dy)
    if distance <= 1e-9:
        return hole.appearance_time
    angle = math.atan2(dy, dx)
    distortion = 0.08 * math.sin(angle * 3 + hole.primary_phase) + 0.04 * math.sin(
        angle * 7 + hole.secondary_phase
    )
    effective_distance = distance * (1 + distortion)
    return hole.appearance_time + hole.growth_duration * min(
        1.0,
        effective_distance / hole.maximum_radius,
    )


def _assign_ignition_times(cells: list[_Cell], holes: tuple[_Hole, ...]) -> None:
    for cell in cells:
        cell.ignition_time = min(_ignition_time(cell, hole) for hole in holes)


def _without_foreground(style: str) -> str:
    return " ".join(
        token
        for token in style.split()
        if not token.startswith(("fg:", "#", "ansi"))
        and token.casefold() not in _BARE_FOREGROUND_COLORS
    )


def _burned_cell(
    cell: _Cell,
    elapsed_seconds: float,
    burn_duration_seconds: float,
) -> tuple[str, str] | None:
    age = elapsed_seconds - cell.ignition_time
    if age < 0:
        return cell.style, cell.character
    progress = age / burn_duration_seconds
    if progress >= 1:
        return None
    stage = min(len(_BURN_COLORS) - 1, int(progress * len(_BURN_COLORS)))
    attributes = _without_foreground(cell.style)
    bold = "bold " if stage == 0 and "bold" not in attributes.split() else ""
    return f"{attributes} {bold}fg:{_BURN_COLORS[stage]}".strip(), cell.character


def _render_cells(
    cells: list[_Cell],
    *,
    elapsed_seconds: float,
    burn_duration_seconds: float,
    height: int,
    width: int,
) -> tuple[list[tuple[str, str]], int]:
    grid: list[list[tuple[str, str] | None]] = [[None for _ in range(width)] for _ in range(height)]
    remaining = 0
    for cell in cells:
        rendered = _burned_cell(cell, elapsed_seconds, burn_duration_seconds)
        if rendered is None:
            continue
        style, character = rendered
        if cell.controls_completion:
            remaining += 1
        grid[cell.row][cell.column] = (style, character)
        padding = max(0, cell.width - terminal_cell_width(character))
        for offset in range(1, cell.width):
            grid[cell.row][cell.column + offset] = (
                "",
                " " if offset <= padding else "",
            )
    if remaining == 0:
        return [], 0

    fragments: list[tuple[str, str]] = []
    for row_number, row in enumerate(grid):
        active_style = ""
        active_text = ""
        occupied_columns = [index for index, entry in enumerate(row) if entry is not None]
        visible_row = row[: occupied_columns[-1] + 1] if occupied_columns else []
        for entry in visible_row:
            style, character = ("", " ") if entry is None else entry
            if style != active_style and active_text:
                fragments.append((active_style, active_text))
                active_text = ""
            active_style = style
            active_text += character
        if active_text:
            fragments.append((active_style, active_text))
        if row_number + 1 < height:
            fragments.append(("", "\n"))
    return fragments, remaining


class _FilmBurnRenderer:
    def __init__(
        self,
        *,
        minimum_holes: int,
        maximum_holes: int,
        maximum_appearance_delay_seconds: float,
        minimum_growth_duration_seconds: float,
        maximum_growth_duration_seconds: float,
        burn_duration_seconds: float,
        frames_per_second: float,
    ) -> None:
        self.minimum_holes = minimum_holes
        self.maximum_holes = maximum_holes
        self.maximum_appearance_delay_seconds = maximum_appearance_delay_seconds
        self.minimum_growth_duration_seconds = minimum_growth_duration_seconds
        self.maximum_growth_duration_seconds = maximum_growth_duration_seconds
        self.burn_duration_seconds = burn_duration_seconds
        self.frames_per_second = frames_per_second
        self.duration_seconds = minimum_growth_duration_seconds + burn_duration_seconds
        self._key: tuple[object, ...] | None = None
        self._state: _FilmBurnState | None = None

    def __call__(self, context: ScreenClearContext) -> list[tuple[str, str]]:
        key = (context.lines, context.styled_lines, context.width, context.seed)
        if self._key != key or self._state is None:
            cells = _source_cells(context)
            holes = _generate_holes(
                context,
                cells,
                minimum_holes=self.minimum_holes,
                maximum_holes=self.maximum_holes,
                maximum_appearance_delay_seconds=self.maximum_appearance_delay_seconds,
                minimum_growth_duration_seconds=self.minimum_growth_duration_seconds,
                maximum_growth_duration_seconds=self.maximum_growth_duration_seconds,
            )
            _assign_ignition_times(cells, holes)
            self._key = key
            self._state = _FilmBurnState(
                cells,
                holes,
                complete=not any(cell.controls_completion for cell in cells),
            )

        elapsed_seconds = (
            context.elapsed_seconds
            if context.elapsed_seconds is not None
            else context.progress * self.duration_seconds
        )
        if (
            context.elapsed_seconds is None
            and context.progress >= 1
            and elapsed_seconds <= self._state.elapsed_seconds
            and not self._state.complete
        ):
            elapsed_seconds = self._state.elapsed_seconds + 1 / self.frames_per_second
        self._state.elapsed_seconds = elapsed_seconds
        fragments, remaining = _render_cells(
            self._state.cells,
            elapsed_seconds=elapsed_seconds,
            burn_duration_seconds=self.burn_duration_seconds,
            height=len(context.lines),
            width=context.width,
        )
        self._state.complete = remaining == 0
        return fragments

    def is_complete(self) -> bool:
        return self._state is not None and self._state.complete


def render_film_burn(
    context: ScreenClearContext,
    *,
    minimum_holes: int = 3,
    maximum_holes: int = 7,
    maximum_appearance_delay_seconds: float = 3.0,
    minimum_growth_duration_seconds: float = 3.5,
    maximum_growth_duration_seconds: float = 6.0,
    burn_duration_seconds: float = 0.7,
    frames_per_second: float = 24.0,
) -> list[tuple[str, str]]:
    return _FilmBurnRenderer(
        minimum_holes=minimum_holes,
        maximum_holes=maximum_holes,
        maximum_appearance_delay_seconds=maximum_appearance_delay_seconds,
        minimum_growth_duration_seconds=minimum_growth_duration_seconds,
        maximum_growth_duration_seconds=maximum_growth_duration_seconds,
        burn_duration_seconds=burn_duration_seconds,
        frames_per_second=frames_per_second,
    )(context)


class FilmBurnPlugin:
    api_version = PLUGIN_API_VERSION

    def register(self, registrar: PluginRegistrar, config: Mapping[str, Any]) -> None:
        unknown = set(config) - _FIELDS
        if unknown:
            raise PluginRegistrationError("unknown film_burn fields: " + ", ".join(sorted(unknown)))
        minimum_holes = _positive_integer(config.get("minimum_holes", 3), "minimum_holes")
        maximum_holes = _positive_integer(config.get("maximum_holes", 7), "maximum_holes")
        if maximum_holes < minimum_holes:
            raise PluginRegistrationError(
                "film_burn maximum_holes cannot be less than minimum_holes"
            )
        if maximum_holes > 32:
            raise PluginRegistrationError("film_burn maximum_holes cannot exceed 32")
        maximum_appearance_delay_seconds = _non_negative_number(
            config.get("maximum_appearance_delay_seconds", 3.0),
            "maximum_appearance_delay_seconds",
        )
        if maximum_appearance_delay_seconds > 30:
            raise PluginRegistrationError(
                "film_burn maximum_appearance_delay_seconds cannot exceed 30"
            )
        minimum_growth_duration_seconds = _positive_number(
            config.get("minimum_growth_duration_seconds", 3.5),
            "minimum_growth_duration_seconds",
        )
        maximum_growth_duration_seconds = _positive_number(
            config.get("maximum_growth_duration_seconds", 6.0),
            "maximum_growth_duration_seconds",
        )
        if maximum_growth_duration_seconds < minimum_growth_duration_seconds:
            raise PluginRegistrationError(
                "film_burn maximum_growth_duration_seconds cannot be less than "
                "minimum_growth_duration_seconds"
            )
        if maximum_growth_duration_seconds > 60:
            raise PluginRegistrationError(
                "film_burn maximum_growth_duration_seconds cannot exceed 60"
            )
        if minimum_growth_duration_seconds < maximum_appearance_delay_seconds:
            raise PluginRegistrationError(
                "film_burn minimum_growth_duration_seconds cannot be less than "
                "maximum_appearance_delay_seconds"
            )
        burn_duration_seconds = _positive_number(
            config.get("burn_duration_seconds", 0.7),
            "burn_duration_seconds",
        )
        if burn_duration_seconds > 10:
            raise PluginRegistrationError("film_burn burn_duration_seconds cannot exceed 10")
        duration_seconds = minimum_growth_duration_seconds + burn_duration_seconds
        if duration_seconds > MAX_SCREEN_CLEAR_DURATION_SECONDS:
            raise PluginRegistrationError(
                f"film_burn minimum growth plus burn duration cannot exceed "
                f"{MAX_SCREEN_CLEAR_DURATION_SECONDS:g}"
            )
        frames_per_second = _positive_number(
            config.get("frames_per_second", 24.0),
            "frames_per_second",
        )
        if not 1 <= frames_per_second <= 30:
            raise PluginRegistrationError("film_burn frames_per_second must be between 1 and 30")

        renderer = _FilmBurnRenderer(
            minimum_holes=minimum_holes,
            maximum_holes=maximum_holes,
            maximum_appearance_delay_seconds=maximum_appearance_delay_seconds,
            minimum_growth_duration_seconds=minimum_growth_duration_seconds,
            maximum_growth_duration_seconds=maximum_growth_duration_seconds,
            burn_duration_seconds=burn_duration_seconds,
            frames_per_second=frames_per_second,
        )
        registrar.register_screen_clear_effect(
            renderer,
            duration_seconds=duration_seconds,
            frames_per_second=frames_per_second,
            is_complete=renderer.is_complete,
        )


plugin = FilmBurnPlugin()

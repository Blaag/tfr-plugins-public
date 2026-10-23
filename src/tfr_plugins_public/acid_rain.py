from __future__ import annotations

import math
from collections.abc import Mapping
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
    {"density", "duration_seconds", "frames_per_second", "streak_length"}
)


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PluginRegistrationError(f"acid_rain {field} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise PluginRegistrationError(f"acid_rain {field} must be finite")
    return result


def _positive_number(value: object, field: str) -> float:
    result = _number(value, field)
    if result <= 0:
        raise PluginRegistrationError(f"acid_rain {field} must be positive")
    return result


def _variation(seed: int, salt: int) -> float:
    value = (seed ^ (salt * 0x9E3779B9)) & 0xFFFFFFFF
    value ^= value >> 16
    value = (value * 0x7FEB352D) & 0xFFFFFFFF
    value ^= value >> 15
    value = (value * 0x846CA68B) & 0xFFFFFFFF
    value ^= value >> 16
    return value / 0xFFFFFFFF


def _source_cells(context: ScreenClearContext) -> list[tuple[int, int, int, str, str]]:
    cells: list[tuple[int, int, int, str, str]] = []
    styled_lines = context.styled_lines or tuple((("", line),) for line in context.lines)
    for row, fragments in enumerate(styled_lines):
        column = 0
        line_cells: list[tuple[int, int, int, str, str]] = []
        for style, text in fragments:
            for character in text:
                width = terminal_cell_width(character)
                if width <= 0:
                    if line_cells:
                        previous = line_cells[-1]
                        line_cells[-1] = (*previous[:3], previous[3] + character, previous[4])
                    continue
                if column + width > context.width:
                    break
                line_cells.append((row, column, width, character, style))
                column += width
            if column >= context.width:
                break
        cells.extend(line_cells)
    return cells


def _corroded_cell(
    character: str,
    local_progress: float,
    variation: float,
) -> tuple[str, str] | None:
    if local_progress <= 0:
        return "", character
    if local_progress < 0.13:
        return "bold fg:#afff00", character
    if local_progress < 0.3:
        return "fg:#87d700", character.lower()
    if local_progress < 0.47:
        return "fg:#5f8700", "#" if variation < 0.5 else "%"
    if local_progress < 0.64:
        return "fg:#5f5f00", "*"
    if local_progress < 0.8:
        return "fg:#5f3f00", ":"
    if local_progress < 0.91:
        return "fg:#3f2f00", "."
    return None


def _render_grid(grid: list[list[tuple[str, str] | None]]) -> list[tuple[str, str]]:
    fragments: list[tuple[str, str]] = []
    for row_number, row in enumerate(grid):
        active_style = ""
        active_text = ""
        for cell in row:
            style, character = ("", " ") if cell is None else cell
            if style != active_style and active_text:
                fragments.append((active_style, active_text))
                active_text = ""
            active_style = style
            active_text += character
        if active_text:
            fragments.append((active_style, active_text.rstrip()))
        if row_number + 1 < len(grid):
            fragments.append(("", "\n"))
    return fragments


def _collision_schedule(
    context: ScreenClearContext,
    cells: list[tuple[int, int, int, str, str]],
) -> tuple[dict[tuple[int, int], float], dict[int, list[tuple[int, float]]]]:
    targets_by_column: dict[int, list[tuple[int, int]]] = {}
    for index, (row, column, character_width, character, _style) in enumerate(cells):
        if character.isspace():
            continue
        for occupied_column in range(column, column + character_width):
            targets_by_column.setdefault(occupied_column, []).append((row, index))

    impacts_by_index: dict[int, float] = {}
    column_impacts: dict[int, list[tuple[int, float]]] = {}
    height_scale = max(1, len(context.lines) - 1)
    for column, targets in targets_by_column.items():
        ordered_targets = sorted(set(targets))
        first_row = ordered_targets[0][0]
        first_impact = (
            0.045
            + first_row / height_scale * 0.35
            + _variation(context.seed, column * 23 + 1) * 0.025
        )
        slot = max(0.01, (0.86 - first_impact) / len(ordered_targets))
        impacts: list[tuple[int, float]] = []
        for order, (row, index) in enumerate(ordered_targets):
            jitter = _variation(context.seed, column * 1_009 + row * 37 + order) * slot * 0.12
            impact = first_impact + order * slot + jitter
            impacts.append((row, impact))
            impacts_by_index[index] = min(impacts_by_index.get(index, 1.0), impact)
        column_impacts[column] = impacts

    return (
        {
            (cells[index][0], cells[index][1]): impact
            for index, impact in impacts_by_index.items()
        },
        column_impacts,
    )


def _burn_duration(
    seed: int,
    row: int,
    column: int,
    impact: float,
    next_impact: float | None = None,
) -> float:
    duration = 0.22 + _variation(seed, row * 131 + column * 17 + 3) * 0.08
    if next_impact is not None:
        duration = min(duration, max(0.01, (next_impact - impact) * 0.88))
    return min(duration, max(0.01, (1 - impact) / 0.91))


def _draw_rain(
    grid: list[list[tuple[str, str] | None]],
    *,
    progress: float,
    seed: int,
    density: float,
    streak_length: int,
    collision_impacts: dict[int, list[tuple[int, float]]],
) -> None:
    if progress <= 0 or progress >= 1 or not grid:
        return
    height = len(grid)
    width = len(grid[0])
    span = height + streak_length
    for column in range(width):
        impacts = collision_impacts.get(column, ())
        head: int | None = None
        if impacts:
            for row, impact in impacts:
                travel_duration = 0.1 + row / max(1, height - 1) * 0.1
                if progress < impact - travel_duration:
                    continue
                if progress < impact:
                    travel = (progress - (impact - travel_duration)) / travel_duration
                    head = math.floor(-streak_length + travel * (row + streak_length))
                    break
                hold = 0.045 + _variation(seed, column * 59 + row) * 0.035
                if progress < impact + hold:
                    head = row
                    break
            if head is None:
                continue
        else:
            if _variation(seed, column * 11 + 1) > density:
                continue
            phase = _variation(seed, column * 11 + 2)
            cycles = 1.1 + _variation(seed, column * 11 + 3) * 1.4
            head = math.floor(((progress * cycles + phase) % 1.0) * span) - streak_length
        for offset in range(streak_length):
            row = head - offset
            if not 0 <= row < height or grid[row][column] is not None:
                continue
            if offset == 0:
                grid[row][column] = ("bold fg:#afff00", "│")
            elif offset < streak_length / 2:
                grid[row][column] = ("fg:#87d700", ":")
            else:
                grid[row][column] = ("fg:#5f8700", ".")


def render_acid_rain(
    context: ScreenClearContext,
    *,
    density: float = 0.32,
    streak_length: int = 4,
) -> list[tuple[str, str]]:
    height = len(context.lines)
    if height == 0 or context.width < 1:
        return []
    progress = min(1.0, max(0.0, context.progress))
    grid: list[list[tuple[str, str] | None]] = [
        [None for _ in range(context.width)] for _ in range(height)
    ]
    source_cells = _source_cells(context)
    collision_times, collision_impacts = _collision_schedule(context, source_cells)

    for row, column, character_width, character, source_style in source_cells:
        if character.isspace():
            continue
        seed = context.seed * 1_009 + row * 131 + column * 17 + sum(map(ord, character))
        impact = collision_times[(row, column)]
        next_impacts = [
            next_impact
            for occupied_column in range(column, column + character_width)
            for next_row, next_impact in collision_impacts[occupied_column]
            if next_row > row
        ]
        duration = _burn_duration(
            context.seed,
            row,
            column,
            impact,
            min(next_impacts, default=None),
        )
        local_progress = min(1.0, max(0.0, (progress - impact) / duration))
        rendered = _corroded_cell(character, local_progress, _variation(seed, 2))
        if rendered is None:
            continue
        style, output_character = rendered
        if local_progress <= 0:
            style = source_style
        grid[row][column] = (style, output_character)
        padding = max(0, character_width - terminal_cell_width(output_character))
        for offset in range(1, character_width):
            grid[row][column + offset] = ("", " " if offset <= padding else "")

    _draw_rain(
        grid,
        progress=progress,
        seed=context.seed,
        density=density,
        streak_length=streak_length,
        collision_impacts=collision_impacts,
    )
    return _render_grid(grid)


class AcidRainPlugin:
    api_version = PLUGIN_API_VERSION

    def register(self, registrar: PluginRegistrar, config: Mapping[str, Any]) -> None:
        unknown = set(config) - _FIELDS
        if unknown:
            raise PluginRegistrationError(
                "unknown acid_rain fields: " + ", ".join(sorted(unknown))
            )
        duration_seconds = _positive_number(
            config.get("duration_seconds", 3.0), "duration_seconds"
        )
        if duration_seconds > MAX_SCREEN_CLEAR_DURATION_SECONDS:
            raise PluginRegistrationError(
                f"acid_rain duration_seconds cannot exceed {MAX_SCREEN_CLEAR_DURATION_SECONDS:g}"
            )
        frames_per_second = _positive_number(
            config.get("frames_per_second", 24.0), "frames_per_second"
        )
        if not 1 <= frames_per_second <= 30:
            raise PluginRegistrationError("acid_rain frames_per_second must be between 1 and 30")
        density = _number(config.get("density", 0.32), "density")
        if not 0 <= density <= 1:
            raise PluginRegistrationError("acid_rain density must be between 0 and 1")
        streak_length = config.get("streak_length", 4)
        if (
            isinstance(streak_length, bool)
            or not isinstance(streak_length, int)
            or not 1 <= streak_length <= 12
        ):
            raise PluginRegistrationError(
                "acid_rain streak_length must be an integer between 1 and 12"
            )

        def render(context: ScreenClearContext) -> list[tuple[str, str]]:
            return render_acid_rain(
                context,
                density=density,
                streak_length=streak_length,
            )

        registrar.register_screen_clear_effect(
            render,
            duration_seconds=duration_seconds,
            frames_per_second=frames_per_second,
        )


plugin = AcidRainPlugin()

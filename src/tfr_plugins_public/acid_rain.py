from __future__ import annotations

import math
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


@dataclass(frozen=True, slots=True)
class _Drop:
    column: int
    spawn_row: int
    start: float
    rows_per_progress: float
    collision_row: int | None
    impact: float | None


def _drop_schedule(
    context: ScreenClearContext,
    cells: list[tuple[int, int, int, str, str]],
    density: float,
) -> tuple[_Drop, ...]:
    if density <= 0 or not context.lines or context.width < 1:
        return ()

    targets_by_column: dict[int, list[int]] = {}
    for row, column, character_width, character, _style in cells:
        if character.isspace():
            continue
        for occupied_column in range(column, column + character_width):
            targets_by_column.setdefault(occupied_column, []).append(row)

    height = len(context.lines)
    drop_count = max(1, math.ceil(context.width * density * 0.35))
    drops: list[_Drop] = []
    for index in range(drop_count):
        salt = index * 97
        column = min(
            context.width - 1,
            math.floor(_variation(context.seed, salt + 1) * context.width),
        )
        spawn_row = min(
            height - 1,
            math.floor(_variation(context.seed, salt + 2) * height),
        )
        start = 0.025 + _variation(context.seed, salt + 3) * 0.52
        fall_duration = min(
            0.18 + _variation(context.seed, salt + 4) * 0.12,
            0.68 - start,
        )
        rows_per_progress = max(1, height - 1) / fall_duration
        collision_row = next(
            (
                row
                for row in sorted(set(targets_by_column.get(column, ())))
                if row >= spawn_row
            ),
            None,
        )
        impact = (
            start + (collision_row - spawn_row) / rows_per_progress
            if collision_row is not None
            else None
        )
        drops.append(
            _Drop(
                column=column,
                spawn_row=spawn_row,
                start=start,
                rows_per_progress=rows_per_progress,
                collision_row=collision_row,
                impact=impact,
            )
        )
    return tuple(drops)


def _corrosion_schedule(
    context: ScreenClearContext,
    cells: list[tuple[int, int, int, str, str]],
    drops: tuple[_Drop, ...],
) -> dict[tuple[int, int], float]:
    impacts = tuple(
        (drop.collision_row, drop.column, drop.impact)
        for drop in drops
        if drop.collision_row is not None and drop.impact is not None
    )
    height_scale = max(1, len(context.lines) - 1)
    schedule: dict[tuple[int, int], float] = {}
    for row, column, _character_width, character, _style in cells:
        if character.isspace():
            continue
        if impacts:
            arrival = min(
                impact
                + (abs(row - impact_row) * 1.5 + abs(column - impact_column)) * 0.035
                + (
                    0
                    if (row, column) == (impact_row, impact_column)
                    else _variation(context.seed, row * 1_009 + column * 37 + 5) * 0.025
                )
                for impact_row, impact_column, impact in impacts
            )
        else:
            # A zero-density effect still has to fulfill the screen-clear contract.
            # Keep the old quiet top-to-bottom diffusion when no rain can strike.
            arrival = 0.045 + row / height_scale * 0.5
            arrival += _variation(context.seed, row * 1_009 + column * 37 + 5) * 0.025
        schedule[(row, column)] = min(0.7, arrival)
    return schedule


def _burn_duration(
    seed: int,
    row: int,
    column: int,
    impact: float,
) -> float:
    duration = 0.22 + _variation(seed, row * 131 + column * 17 + 3) * 0.08
    return min(duration, max(0.01, (1 - impact) / 0.91))


def _draw_rain(
    grid: list[list[tuple[str, str] | None]],
    *,
    progress: float,
    seed: int,
    streak_length: int,
    drops: tuple[_Drop, ...],
) -> None:
    if progress <= 0 or progress >= 1 or not grid:
        return
    height = len(grid)
    for index, drop in enumerate(drops):
        if progress < drop.start:
            continue
        head = drop.spawn_row + math.floor((progress - drop.start) * drop.rows_per_progress)
        if drop.collision_row is not None and drop.impact is not None:
            hold = 0.035 + _variation(seed, index * 59 + drop.collision_row) * 0.025
            if progress >= drop.impact + hold:
                continue
            head = min(head, drop.collision_row)
        elif head >= height + streak_length:
            continue
        # Preserve the option for compatibility while keeping each visible drop compact.
        visible_length = min(streak_length, 2)
        for offset in range(visible_length):
            row = head - offset
            if not 0 <= row < height or grid[row][drop.column] is not None:
                continue
            if offset == 0:
                grid[row][drop.column] = ("bold fg:#afff00", "•")
            else:
                grid[row][drop.column] = ("fg:#5f8700", ".")


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
    drops = _drop_schedule(context, source_cells, density)
    collision_times = _corrosion_schedule(context, source_cells, drops)

    for row, column, character_width, character, source_style in source_cells:
        if character.isspace():
            continue
        seed = context.seed * 1_009 + row * 131 + column * 17 + sum(map(ord, character))
        impact = collision_times[(row, column)]
        duration = _burn_duration(context.seed, row, column, impact)
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
        streak_length=streak_length,
        drops=drops,
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

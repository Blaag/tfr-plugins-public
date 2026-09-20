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

_FIELDS = frozenset({"direction", "duration_seconds", "frames_per_second", "gust_strength"})
_SAND_COLORS = ("#e5c07b", "#c89b5a", "#8b6f47")
_SAND_GLYPHS = (".", ":", "·", "*")


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PluginRegistrationError(f"sandstorm {field} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise PluginRegistrationError(f"sandstorm {field} must be finite")
    return result


def _positive_number(value: object, field: str) -> float:
    result = _number(value, field)
    if result <= 0:
        raise PluginRegistrationError(f"sandstorm {field} must be positive")
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


def _render_grid(
    grid: list[list[tuple[float, str, str] | None]],
) -> list[tuple[str, str]]:
    fragments: list[tuple[str, str]] = []
    for row_number, row in enumerate(grid):
        active_style = ""
        active_text = ""
        for cell in row:
            style, character = ("", " ") if cell is None else (cell[1], cell[2])
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


def render_sandstorm(
    context: ScreenClearContext,
    *,
    direction: float = 1.0,
    gust_strength: float = 1.4,
) -> list[tuple[str, str]]:
    height = len(context.lines)
    if height == 0 or context.width < 1:
        return []
    progress = min(1.0, max(0.0, context.progress))
    grid: list[list[tuple[float, str, str] | None]] = [
        [None for _ in range(context.width)] for _ in range(height)
    ]
    width_scale = max(1, context.width - 1)

    for row, column, character_width, character, source_style in _source_cells(context):
        if character.isspace():
            continue
        seed = context.seed * 1_009 + row * 131 + column * 17 + sum(map(ord, character))
        windward_position = column / width_scale
        if direction < 0:
            windward_position = 1 - windward_position
        activation = 0.03 + windward_position * 0.18 + _variation(seed, 1) * 0.11
        local_progress = min(1.0, max(0.0, (progress - activation) / (1 - activation)))

        if local_progress <= 0:
            destination_row = row
            destination_column = column
            output_character = character
            style = source_style
            priority = 1.0
        else:
            fade_at = 0.8 + _variation(seed, 2) * 0.14
            if local_progress >= fade_at:
                continue
            travel = (local_progress**1.6) * (
                context.width + 6 + _variation(seed, 3) * 8
            )
            destination_column = round(column + direction * travel)
            turbulence = math.sin(local_progress * 15 + _variation(seed, 4) * math.tau)
            vertical_drift = (
                turbulence * gust_strength * local_progress
                + (_variation(seed, 5) - 0.5) * gust_strength * local_progress * 2
            )
            destination_row = round(row + vertical_drift)
            breakup = min(1.0, local_progress / 0.65)
            color_index = min(len(_SAND_COLORS) - 1, int(breakup * len(_SAND_COLORS)))
            style = f"fg:{_SAND_COLORS[color_index]}"
            output_character = _SAND_GLYPHS[
                int(_variation(seed, 6) * len(_SAND_GLYPHS)) % len(_SAND_GLYPHS)
            ]
            priority = 2.0 + local_progress

        if not (
            0 <= destination_row < height
            and destination_column >= 0
            and destination_column + character_width <= context.width
        ):
            continue
        occupied = range(destination_column, destination_column + character_width)
        if any(grid[destination_row][occupied_column] is not None for occupied_column in occupied):
            continue
        grid[destination_row][destination_column] = (priority, style, output_character)
        padding = max(0, character_width - terminal_cell_width(output_character))
        for offset in range(1, character_width):
            grid[destination_row][destination_column + offset] = (
                priority,
                "",
                " " if offset <= padding else "",
            )

    return _render_grid(grid)


class SandstormPlugin:
    api_version = PLUGIN_API_VERSION

    def register(self, registrar: PluginRegistrar, config: Mapping[str, Any]) -> None:
        unknown = set(config) - _FIELDS
        if unknown:
            raise PluginRegistrationError(
                "unknown sandstorm fields: " + ", ".join(sorted(unknown))
            )
        duration_seconds = _positive_number(
            config.get("duration_seconds", 2.8), "duration_seconds"
        )
        if duration_seconds > MAX_SCREEN_CLEAR_DURATION_SECONDS:
            raise PluginRegistrationError(
                f"sandstorm duration_seconds cannot exceed {MAX_SCREEN_CLEAR_DURATION_SECONDS:g}"
            )
        frames_per_second = _positive_number(
            config.get("frames_per_second", 24.0), "frames_per_second"
        )
        if not 1 <= frames_per_second <= 30:
            raise PluginRegistrationError("sandstorm frames_per_second must be between 1 and 30")
        gust_strength = _number(config.get("gust_strength", 1.4), "gust_strength")
        if not 0 <= gust_strength <= 4:
            raise PluginRegistrationError("sandstorm gust_strength must be between 0 and 4")
        direction_name = config.get("direction", "left-to-right")
        if not isinstance(direction_name, str) or direction_name not in {
            "left-to-right",
            "right-to-left",
        }:
            raise PluginRegistrationError(
                "sandstorm direction must be left-to-right or right-to-left"
            )
        direction = 1.0 if direction_name == "left-to-right" else -1.0

        def render(context: ScreenClearContext) -> list[tuple[str, str]]:
            return render_sandstorm(
                context,
                direction=direction,
                gust_strength=gust_strength,
            )

        registrar.register_screen_clear_effect(
            render,
            duration_seconds=duration_seconds,
            frames_per_second=frames_per_second,
        )


plugin = SandstormPlugin()

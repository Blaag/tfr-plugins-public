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

_FIELDS = frozenset({"duration_seconds", "frames_per_second"})
_CELL_ASPECT = 0.5


def _positive_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PluginRegistrationError(f"water_ripple {field} must be a number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise PluginRegistrationError(f"water_ripple {field} must be positive")
    return result


def _variation(seed: int, row: int, column: int) -> float:
    value = (seed * 0x9E3779B1 + row * 0x85EBCA77 + column * 0xC2B2AE3D) & 0xFFFFFFFF
    value ^= value >> 16
    value = (value * 0x7FEB352D) & 0xFFFFFFFF
    value ^= value >> 15
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


def _ripple_cell(character: str, local_progress: float) -> tuple[str, str] | None:
    if local_progress <= 0:
        return "", character
    if local_progress < 0.12:
        return "bold fg:#d7ffff", character
    if local_progress < 0.28:
        return "fg:#87d7ff", "█"
    if local_progress < 0.45:
        return "fg:#5fafff", "▓"
    if local_progress < 0.62:
        return "fg:#5f87d7", "▒"
    if local_progress < 0.79:
        return "fg:#5f5faf", "░"
    if local_progress < 0.9:
        return "fg:#30305f", "."
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


def render_water_ripple(context: ScreenClearContext) -> list[tuple[str, str]]:
    height = len(context.lines)
    if height == 0 or context.width < 1:
        return []
    progress = min(1.0, max(0.0, context.progress))
    center_column = (context.width - 1) / 2
    center_row = (height - 1) / 2
    maximum_radius = max(
        math.hypot((column - center_column) * _CELL_ASPECT, row - center_row)
        for column in (0, context.width - 1)
        for row in (0, height - 1)
    )
    grid: list[list[tuple[str, str] | None]] = [
        [None for _ in range(context.width)] for _ in range(height)
    ]

    for row, column, character_width, character, source_style in _source_cells(context):
        if character.isspace():
            continue
        cell_center = column + (character_width - 1) / 2
        radius = math.hypot(
            (cell_center - center_column) * _CELL_ASPECT,
            row - center_row,
        )
        jitter = _variation(context.seed, row, column) * 0.025
        activation = min(0.64, (radius / maximum_radius if maximum_radius else 0.0) * 0.6 + jitter)
        local_progress = min(1.0, max(0.0, (progress - activation) / (1 - activation)))
        rendered = _ripple_cell(character, local_progress)
        if rendered is None:
            continue
        style, output_character = rendered
        if local_progress <= 0:
            style = source_style
        grid[row][column] = (style, output_character)
        padding = max(0, character_width - terminal_cell_width(output_character))
        for offset in range(1, character_width):
            grid[row][column + offset] = ("", " " if offset <= padding else "")

    return _render_grid(grid)


class WaterRipplePlugin:
    api_version = PLUGIN_API_VERSION

    def register(self, registrar: PluginRegistrar, config: Mapping[str, Any]) -> None:
        unknown = set(config) - _FIELDS
        if unknown:
            raise PluginRegistrationError(
                "unknown water_ripple fields: " + ", ".join(sorted(unknown))
            )
        duration_seconds = _positive_number(
            config.get("duration_seconds", 2.6), "duration_seconds"
        )
        if duration_seconds > MAX_SCREEN_CLEAR_DURATION_SECONDS:
            raise PluginRegistrationError(
                f"water_ripple duration_seconds cannot exceed "
                f"{MAX_SCREEN_CLEAR_DURATION_SECONDS:g}"
            )
        frames_per_second = _positive_number(
            config.get("frames_per_second", 24.0), "frames_per_second"
        )
        if not 1 <= frames_per_second <= 30:
            raise PluginRegistrationError(
                "water_ripple frames_per_second must be between 1 and 30"
            )
        registrar.register_screen_clear_effect(
            render_water_ripple,
            duration_seconds=duration_seconds,
            frames_per_second=frames_per_second,
        )


plugin = WaterRipplePlugin()

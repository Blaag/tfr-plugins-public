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
    {"direction", "duration_seconds", "edge_softness", "frames_per_second", "turns"}
)
_CELL_ASPECT = 0.5


def _positive_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PluginRegistrationError(f"vortex {field} must be a number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise PluginRegistrationError(f"vortex {field} must be positive")
    return result


def _softplus(value: float, softness: float) -> float:
    scaled = value / softness
    if scaled > 40:
        return value
    if scaled < -40:
        return softness * math.exp(scaled)
    return softness * math.log1p(math.exp(scaled))


def _vortex_position(
    x: float,
    y: float,
    progress: float,
    *,
    turns: float,
    direction: float,
) -> tuple[float, float]:
    progress = min(1.0, max(0.0, progress))
    radius = math.hypot(x, y)
    angle = math.atan2(y, x) + direction * math.tau * turns * progress
    collapse = progress * progress * (3 - 2 * progress)
    radius_scale = 1 - collapse
    return radius * radius_scale * math.cos(angle), radius * radius_scale * math.sin(angle)


def _vortex_progress(progress: float, activation: float, edge_softness: float = 0.18) -> float:
    baseline = _softplus(-activation, edge_softness)
    total = _softplus(1 - activation, edge_softness) - baseline
    value = (_softplus(progress - activation, edge_softness) - baseline) / total
    value = min(1.0, max(0.0, value))
    return value * value * (3 - 2 * value)


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
                        previous_row, start, previous_width, previous, previous_style = line_cells[
                            -1
                        ]
                        line_cells[-1] = (
                            previous_row,
                            start,
                            previous_width,
                            previous + character,
                            previous_style,
                        )
                    continue
                if column + width > context.width:
                    break
                line_cells.append((row, column, width, character, style))
                column += width
        cells.extend(line_cells)
    return cells


def render_vortex(
    context: ScreenClearContext,
    *,
    turns: float = 2.25,
    direction: float = 1.0,
    edge_softness: float = 0.18,
) -> list[tuple[str, str]]:
    height = len(context.lines)
    if height == 0:
        return []
    progress = min(1.0, max(0.0, context.progress))
    center_column = (context.width - 1) / 2
    center_row = (height - 1) / 2
    maximum_radius = max(
        math.hypot((column - center_column) * _CELL_ASPECT, row - center_row)
        for column in (0, context.width - 1)
        for row in (0, height - 1)
    )
    grid: list[list[tuple[float, str, str] | None]] = [
        [None for _ in range(context.width)] for _ in range(height)
    ]

    for row, column, character_width, character, source_style in _source_cells(context):
        if character.isspace():
            continue
        source_x = (column + (character_width - 1) / 2 - center_column) * _CELL_ASPECT
        source_y = row - center_row
        radius = math.hypot(source_x, source_y)
        activation = 0.58 * radius / maximum_radius if maximum_radius else 0.0
        local_progress = _vortex_progress(progress, activation, edge_softness)
        if local_progress <= 0:
            destination_row = row
            destination_column = column
            style = source_style
            priority = 1.0
        else:
            if local_progress >= 0.98:
                continue
            destination_x, destination_y = _vortex_position(
                source_x,
                source_y,
                local_progress,
                turns=turns,
                direction=direction,
            )
            destination_column = round(
                center_column + destination_x / _CELL_ASPECT - (character_width - 1) / 2
            )
            destination_row = round(center_row + destination_y)
            style = source_style
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
        grid[destination_row][destination_column] = (priority, style, character)
        padding = max(0, character_width - terminal_cell_width(character))
        for offset in range(1, character_width):
            grid[destination_row][destination_column + offset] = (
                priority,
                "",
                " " if offset <= padding else "",
            )

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
        if row_number + 1 < height:
            fragments.append(("", "\n"))
    return fragments


class VortexPlugin:
    api_version = PLUGIN_API_VERSION

    def register(self, registrar: PluginRegistrar, config: Mapping[str, Any]) -> None:
        unknown = set(config) - _FIELDS
        if unknown:
            raise PluginRegistrationError("unknown vortex fields: " + ", ".join(sorted(unknown)))
        duration_seconds = _positive_number(config.get("duration_seconds", 2.8), "duration_seconds")
        if duration_seconds > MAX_SCREEN_CLEAR_DURATION_SECONDS:
            raise PluginRegistrationError(
                f"vortex duration_seconds cannot exceed {MAX_SCREEN_CLEAR_DURATION_SECONDS:g}"
            )
        frames_per_second = _positive_number(
            config.get("frames_per_second", 24.0), "frames_per_second"
        )
        if frames_per_second > 30:
            raise PluginRegistrationError("vortex frames_per_second cannot exceed 30")
        turns = _positive_number(config.get("turns", 2.25), "turns")
        if turns > 6:
            raise PluginRegistrationError("vortex turns cannot exceed 6")
        edge_softness = _positive_number(config.get("edge_softness", 0.18), "edge_softness")
        if edge_softness > 0.5:
            raise PluginRegistrationError("vortex edge_softness cannot exceed 0.5")
        direction_name = config.get("direction", "clockwise")
        if not isinstance(direction_name, str) or direction_name not in {
            "clockwise",
            "counterclockwise",
        }:
            raise PluginRegistrationError("vortex direction must be clockwise or counterclockwise")
        direction = 1.0 if direction_name == "clockwise" else -1.0

        def render(context: ScreenClearContext) -> list[tuple[str, str]]:
            return render_vortex(
                context,
                turns=turns,
                direction=direction,
                edge_softness=edge_softness,
            )

        registrar.register_screen_clear_effect(
            render,
            duration_seconds=duration_seconds,
            frames_per_second=frames_per_second,
        )


plugin = VortexPlugin()

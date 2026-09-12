from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from tfr.plugin_api import (
    PLUGIN_API_VERSION,
    PluginRegistrar,
    PluginRegistrationError,
    ScreenClearContext,
    terminal_cell_width,
)

_FIELDS = frozenset({"duration_seconds", "frames_per_second"})


def _positive_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PluginRegistrationError(f"flame {field} must be a number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise PluginRegistrationError(f"flame {field} must be positive")
    return result


def _flame_cell(character: str, progress: float, seed: int) -> tuple[str, str] | None:
    if progress < 0:
        return "", character
    if progress < 0.1:
        return "", character
    if progress < 0.27:
        return "bold fg:#ffd700", character
    if progress < 0.43:
        return "bold fg:#ff8700", character
    if progress < 0.59:
        return "bold fg:#d70000", character
    if progress < 0.7:
        return "fg:#5f0000", character
    if progress < 0.82:
        return "fg:#bcbcbc", character.lower()
    if progress < 0.92:
        return "fg:#626262", "*" if seed % 2 else "+"
    if progress < 0.98:
        return "fg:#626262", ":" if seed % 3 else "."
    return None


def _variation(seed: int, salt: int) -> float:
    value = (seed * 1_103_515_245 + salt * 12_345) & 0xFFFF
    return value / 0xFFFF


def render_flame(context: ScreenClearContext) -> list[tuple[str, str]]:
    progress = min(1.0, max(0.0, context.progress))
    height = len(context.lines)
    if height == 0 or context.width < 1:
        return []
    grid: list[list[tuple[float, str, str] | None]] = [
        [None for _ in range(context.width)] for _ in range(height)
    ]
    for row, line in enumerate(context.lines):
        column = 0
        cells: list[tuple[int, int, str]] = []
        for character in line:
            character_width = terminal_cell_width(character)
            if character_width <= 0:
                if cells:
                    start, width, previous = cells[-1]
                    cells[-1] = (start, width, previous + character)
                continue
            if column + character_width > context.width:
                break
            cells.append((column, character_width, character))
            column += character_width
        for column, character_width, character in cells:
            if character.isspace():
                continue
            seed = row * 131 + column * 17 + sum(map(ord, character))
            ignition = _variation(seed, 1) * 0.16
            burnout = 0.62 + _variation(seed, 2) * 0.38
            local_progress = (progress - ignition) / (burnout - ignition)
            rendered = _flame_cell(character, local_progress, seed)
            if rendered is None:
                continue
            smoke_progress = min(1.0, max(0.0, (local_progress - 0.7) / 0.3))
            lift = round(smoke_progress * (1 + seed % 4))
            sway = math.sin(progress * 28 + seed * 0.37)
            shift = round(sway * smoke_progress * (1 + seed % 2))
            destination_row = max(0, row - lift)
            destination_column = column + shift
            if not (
                0 <= destination_row < height
                and destination_column >= 0
                and destination_column + character_width <= context.width
            ):
                continue
            style, output_character = rendered
            priority = 2.0 if local_progress < 0.7 else 2.0 - local_progress
            occupied = range(destination_column, destination_column + character_width)
            if any(
                grid[destination_row][occupied_column] is not None for occupied_column in occupied
            ):
                continue
            grid[destination_row][destination_column] = (priority, style, output_character)
            padding = max(0, character_width - terminal_cell_width(output_character))
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


class FlamePlugin:
    api_version = PLUGIN_API_VERSION

    def register(self, registrar: PluginRegistrar, config: Mapping[str, Any]) -> None:
        unknown = set(config) - _FIELDS
        if unknown:
            raise PluginRegistrationError("unknown flame fields: " + ", ".join(sorted(unknown)))
        duration_seconds = _positive_number(config.get("duration_seconds", 2.1), "duration_seconds")
        if duration_seconds > 10:
            raise PluginRegistrationError("flame duration_seconds cannot exceed 10")
        frames_per_second = _positive_number(
            config.get("frames_per_second", 24.0), "frames_per_second"
        )
        if frames_per_second > 30:
            raise PluginRegistrationError("flame frames_per_second cannot exceed 30")
        registrar.register_screen_clear_effect(
            render_flame,
            duration_seconds=duration_seconds,
            frames_per_second=frames_per_second,
        )


plugin = FlamePlugin()

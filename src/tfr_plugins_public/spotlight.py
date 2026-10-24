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

_FIELDS = frozenset({"duration_seconds", "frames_per_second", "spotlight_count"})
_FADE_END = 0.14
_CELL_ASPECT = 2.0


@dataclass(frozen=True, slots=True)
class _Spotlight:
    waypoint_x: float
    waypoint_y: float
    direction_x: float
    direction_y: float
    start_distance: float
    end_distance: float
    radius: float
    phase: float

    def center(self, progress: float) -> tuple[float, float]:
        sweep = min(1.0, max(0.0, (progress - _FADE_END) / (1 - _FADE_END)))
        staggered = min(1.0, max(0.0, (sweep - self.phase) / (1 - self.phase)))
        offset = -self.start_distance + staggered * (
            self.start_distance + self.end_distance
        )
        return (
            self.waypoint_x + self.direction_x * offset,
            self.waypoint_y + self.direction_y * offset,
        )


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PluginRegistrationError(f"spotlight {field} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise PluginRegistrationError(f"spotlight {field} must be finite")
    return result


def _positive_number(value: object, field: str) -> float:
    result = _number(value, field)
    if result <= 0:
        raise PluginRegistrationError(f"spotlight {field} must be positive")
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


def _ray_exit_distance(
    x: float,
    y: float,
    direction_x: float,
    direction_y: float,
    width: float,
    height: float,
    radius: float,
) -> float:
    candidates: list[tuple[float, float]] = []
    if direction_x > 0:
        candidates.append(((width - x) / direction_x, abs(direction_x)))
    elif direction_x < 0:
        candidates.append((-x / direction_x, abs(direction_x)))
    if direction_y > 0:
        candidates.append(((height - y) / direction_y, abs(direction_y)))
    elif direction_y < 0:
        candidates.append((-y / direction_y, abs(direction_y)))
    distance, boundary_component = min(candidates)
    return distance + radius / boundary_component


def _spotlights(context: ScreenClearContext, count: int) -> tuple[_Spotlight, ...]:
    physical_height = max(_CELL_ASPECT, len(context.lines) * _CELL_ASPECT)
    minimum_dimension = max(1.0, min(context.width, physical_height))
    result: list[_Spotlight] = []
    for index in range(count):
        salt = index * 101
        angle = _variation(context.seed, salt + 1) * math.tau
        direction_x = math.cos(angle)
        direction_y = math.sin(angle)
        # Avoid paths that look constrained to terminal rows or columns.
        if min(abs(direction_x), abs(direction_y)) < 0.16:
            angle += 0.21
            direction_x = math.cos(angle)
            direction_y = math.sin(angle)
        radius = minimum_dimension * (0.14 + _variation(context.seed, salt + 2) * 0.18)
        radius = max(2.5, radius)
        waypoint_x = context.width * (0.2 + _variation(context.seed, salt + 3) * 0.6)
        waypoint_y = physical_height * (0.2 + _variation(context.seed, salt + 4) * 0.6)
        start_distance = _ray_exit_distance(
            waypoint_x,
            waypoint_y,
            -direction_x,
            -direction_y,
            context.width,
            physical_height,
            radius,
        )
        end_distance = _ray_exit_distance(
            waypoint_x,
            waypoint_y,
            direction_x,
            direction_y,
            context.width,
            physical_height,
            radius,
        )
        phase = _variation(context.seed, salt + 5) * 0.08
        result.append(
            _Spotlight(
                waypoint_x,
                waypoint_y,
                direction_x,
                direction_y,
                start_distance,
                end_distance,
                radius,
                phase,
            )
        )
    return tuple(result)


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


def _dimmed(style: str) -> str:
    return f"{style} dim".strip()


def render_spotlight(
    context: ScreenClearContext,
    *,
    spotlight_count: int = 3,
) -> list[tuple[str, str]]:
    height = len(context.lines)
    if height == 0 or context.width < 1:
        return []
    progress = min(1.0, max(0.0, context.progress))
    grid: list[list[tuple[str, str] | None]] = [
        [None for _ in range(context.width)] for _ in range(height)
    ]
    lights = _spotlights(context, spotlight_count)

    for row, column, character_width, character, source_style in _source_cells(context):
        if character.isspace():
            continue
        salt = row * 1_009 + column * 37 + sum(map(ord, character))
        style: str | None = None
        if progress <= 0:
            style = source_style
        elif progress < _FADE_END:
            visibility = 1 - progress / _FADE_END
            if _variation(context.seed, salt) <= visibility:
                style = source_style if visibility > 0.72 else _dimmed(source_style)
        elif progress < 1:
            cell_x = column + character_width / 2
            cell_y = row * _CELL_ASPECT + _CELL_ASPECT / 2
            best_visibility = 0.0
            fully_lit = False
            for light in lights:
                center_x, center_y = light.center(progress)
                distance = math.hypot(cell_x - center_x, cell_y - center_y)
                feather = max(1.25, light.radius * 0.24)
                if distance <= light.radius - feather:
                    fully_lit = True
                    break
                if distance < light.radius:
                    best_visibility = max(
                        best_visibility,
                        (light.radius - distance) / feather,
                    )
            if fully_lit:
                style = source_style
            elif best_visibility > 0 and _variation(context.seed, salt + 17) <= best_visibility:
                style = _dimmed(source_style)
        if style is None:
            continue
        grid[row][column] = (style, character)
        for offset in range(1, character_width):
            grid[row][column + offset] = ("", "")

    return _render_grid(grid)


class SpotlightPlugin:
    api_version = PLUGIN_API_VERSION

    def register(self, registrar: PluginRegistrar, config: Mapping[str, Any]) -> None:
        unknown = set(config) - _FIELDS
        if unknown:
            raise PluginRegistrationError(
                "unknown spotlight fields: " + ", ".join(sorted(unknown))
            )
        duration_seconds = _positive_number(
            config.get("duration_seconds", 3.6), "duration_seconds"
        )
        if duration_seconds > MAX_SCREEN_CLEAR_DURATION_SECONDS:
            raise PluginRegistrationError(
                f"spotlight duration_seconds cannot exceed {MAX_SCREEN_CLEAR_DURATION_SECONDS:g}"
            )
        frames_per_second = _positive_number(
            config.get("frames_per_second", 24.0), "frames_per_second"
        )
        if not 1 <= frames_per_second <= 30:
            raise PluginRegistrationError("spotlight frames_per_second must be between 1 and 30")
        spotlight_count = config.get("spotlight_count", 3)
        if (
            isinstance(spotlight_count, bool)
            or not isinstance(spotlight_count, int)
            or not 2 <= spotlight_count <= 5
        ):
            raise PluginRegistrationError(
                "spotlight spotlight_count must be an integer between 2 and 5"
            )

        def render(context: ScreenClearContext) -> list[tuple[str, str]]:
            return render_spotlight(context, spotlight_count=spotlight_count)

        registrar.register_screen_clear_effect(
            render,
            duration_seconds=duration_seconds,
            frames_per_second=frames_per_second,
        )


plugin = SpotlightPlugin()

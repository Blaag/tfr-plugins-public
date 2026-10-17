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

_FIELDS = frozenset({"duration_seconds", "frames_per_second"})
_MAX_INTENSITY = 36
_FIRE_STAGES = (
    (4, "fg:#5f0000", "."),
    (9, "fg:#870000", ":"),
    (15, "fg:#d70000", "*"),
    (22, "fg:#ff5f00", "o"),
    (28, "fg:#ffaf00", "O"),
    (33, "bold fg:#ffd700", "#"),
    (_MAX_INTENSITY, "bold fg:#ffffd7", "@"),
)


def _positive_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PluginRegistrationError(f"doom_fire {field} must be a number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise PluginRegistrationError(f"doom_fire {field} must be positive")
    return result


def _noise(seed: int, frame: int, generation: int, row: int, column: int) -> int:
    value = (
        seed * 0x9E3779B1
        + frame * 0x85EBCA77
        + generation * 0xC2B2AE3D
        + row * 0x27D4EB2F
        + column * 0x165667B1
    ) & 0xFFFFFFFF
    value ^= value >> 16
    value = (value * 0x7FEB352D) & 0xFFFFFFFF
    value ^= value >> 15
    value = (value * 0x846CA68B) & 0xFFFFFFFF
    return value ^ (value >> 16)


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
    grid: list[list[tuple[str, str] | None]],
) -> list[tuple[str, str]]:
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


def _fire_cell(intensity: int) -> tuple[str, str] | None:
    if intensity <= 0:
        return None
    for maximum, style, glyph in _FIRE_STAGES:
        if intensity <= maximum:
            return style, glyph
    return _FIRE_STAGES[-1][1:]


@dataclass(slots=True)
class _FireState:
    intensities: list[int]
    burned: list[bool]
    frame: int = 0


def _new_state(width: int, height: int) -> _FireState:
    intensities = [0] * (width * (height + 1))
    for column in range(width):
        intensities[height * width + column] = _MAX_INTENSITY
    return _FireState(intensities, [False] * (width * height))


def _source_intensity(frame: int, total_frames: int) -> int:
    progress = frame / max(1, total_frames)
    if progress <= 0.56:
        return _MAX_INTENSITY
    if progress >= 0.72:
        return 0
    return round(_MAX_INTENSITY * (0.72 - progress) / 0.16)


def _advance_generation(
    state: _FireState,
    *,
    width: int,
    height: int,
    seed: int,
    frame: int,
    generation: int,
    source_intensity: int,
) -> None:
    previous = state.intensities
    values = [0] * len(previous)
    source_row = height * width
    for column in range(width):
        flicker = _noise(seed, frame, generation, height, column) % 5
        values[source_row + column] = max(0, source_intensity - flicker)

    for row in range(height):
        below_row = (row + 1) * width
        target_row = row * width
        for column in range(width):
            noise = _noise(seed, frame, generation, row, column)
            source_column = min(width - 1, max(0, column + (noise % 3) - 1))
            decay = (noise >> 3) & 1
            if source_intensity == 0:
                decay += 1
            intensity = max(0, previous[below_row + source_column] - decay)
            values[target_row + column] = intensity
            if intensity >= 4:
                state.burned[target_row + column] = True
    state.intensities = values


def _render_fire(context: ScreenClearContext, state: _FireState) -> list[tuple[str, str]]:
    height = len(context.lines)
    width = context.width
    grid: list[list[tuple[str, str] | None]] = [
        [None for _ in range(width)] for _ in range(height)
    ]

    for row, column, character_width, character, style in _source_cells(context):
        if character.isspace():
            continue
        occupied = range(column, column + character_width)
        if any(
            state.burned[row * width + occupied_column]
            or state.intensities[row * width + occupied_column] > 0
            for occupied_column in occupied
        ):
            continue
        grid[row][column] = (style, character)
        padding = max(0, character_width - terminal_cell_width(character))
        for offset in range(1, character_width):
            grid[row][column + offset] = ("", " " if offset <= padding else "")

    for row in range(height):
        for column in range(width):
            if grid[row][column] is not None:
                continue
            rendered = _fire_cell(state.intensities[row * width + column])
            if rendered is not None:
                grid[row][column] = rendered
    return _render_grid(grid)


class _DoomFireRenderer:
    def __init__(self, *, duration_seconds: float, frames_per_second: float) -> None:
        self.duration_seconds = duration_seconds
        self.frames_per_second = frames_per_second
        self._key: tuple[object, ...] | None = None
        self._state: _FireState | None = None

    def __call__(self, context: ScreenClearContext) -> list[tuple[str, str]]:
        height = len(context.lines)
        if height == 0 or context.width < 1:
            self._key = (context.lines, context.styled_lines, context.width, context.seed)
            self._state = _new_state(max(1, context.width), 0)
            return []
        key = (context.lines, context.styled_lines, context.width, context.seed)
        elapsed_seconds = (
            context.elapsed_seconds
            if context.elapsed_seconds is not None
            else min(1.0, max(0.0, context.progress)) * self.duration_seconds
        )
        total_frames = max(1, round(self.duration_seconds * self.frames_per_second))
        target_frame = min(total_frames, max(0, int(elapsed_seconds * self.frames_per_second)))
        if self._key != key or self._state is None or target_frame < self._state.frame:
            self._key = key
            self._state = _new_state(context.width, height)

        generations_per_frame = max(1, math.ceil(height / max(1, total_frames * 0.5)))
        while self._state.frame < target_frame:
            next_frame = self._state.frame + 1
            source_intensity = _source_intensity(next_frame, total_frames)
            for generation in range(generations_per_frame):
                _advance_generation(
                    self._state,
                    width=context.width,
                    height=height,
                    seed=context.seed,
                    frame=next_frame,
                    generation=generation,
                    source_intensity=source_intensity,
                )
            self._state.frame = next_frame

        if context.progress >= 1:
            return _render_grid([[None for _ in range(context.width)] for _ in range(height)])
        return _render_fire(context, self._state)


def render_doom_fire(
    context: ScreenClearContext,
    *,
    duration_seconds: float = 3.2,
    frames_per_second: float = 24.0,
) -> list[tuple[str, str]]:
    return _DoomFireRenderer(
        duration_seconds=duration_seconds,
        frames_per_second=frames_per_second,
    )(context)


class DoomFirePlugin:
    api_version = PLUGIN_API_VERSION

    def register(self, registrar: PluginRegistrar, config: Mapping[str, Any]) -> None:
        unknown = set(config) - _FIELDS
        if unknown:
            raise PluginRegistrationError(
                "unknown doom_fire fields: " + ", ".join(sorted(unknown))
            )
        duration_seconds = _positive_number(
            config.get("duration_seconds", 3.2), "duration_seconds"
        )
        if duration_seconds > MAX_SCREEN_CLEAR_DURATION_SECONDS:
            raise PluginRegistrationError(
                f"doom_fire duration_seconds cannot exceed {MAX_SCREEN_CLEAR_DURATION_SECONDS:g}"
            )
        frames_per_second = _positive_number(
            config.get("frames_per_second", 24.0), "frames_per_second"
        )
        if not 1 <= frames_per_second <= 30:
            raise PluginRegistrationError("doom_fire frames_per_second must be between 1 and 30")
        renderer = _DoomFireRenderer(
            duration_seconds=duration_seconds,
            frames_per_second=frames_per_second,
        )
        registrar.register_screen_clear_effect(
            renderer,
            duration_seconds=duration_seconds,
            frames_per_second=frames_per_second,
        )


plugin = DoomFirePlugin()

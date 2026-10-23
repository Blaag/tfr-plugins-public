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
    fuel_starts: list[int]
    fuel_ends: list[int]
    fuel_intensities: list[int]
    frame: int = 0


def _new_state(context: ScreenClearContext, total_frames: int) -> _FireState:
    width = context.width
    height = len(context.lines)
    cell_count = width * height
    fuel = [False] * cell_count
    for row, column, character_width, character, _style in _source_cells(context):
        if character.isspace():
            continue
        for occupied_column in range(column, column + character_width):
            fuel[row * width + occupied_column] = True

    occupied_rows = [index // width for index, occupied in enumerate(fuel) if occupied]
    fuel_count = len(occupied_rows)
    bottom_row = max(occupied_rows, default=0)
    row_span = max(1, bottom_row - min(occupied_rows, default=bottom_row))
    fuel_starts = [0] * cell_count
    fuel_ends = [0] * cell_count
    fuel_intensities = [0] * cell_count
    for index, occupied in enumerate(fuel):
        if not occupied:
            continue
        row, column = divmod(index, width)
        height_delay = (bottom_row - row) / row_span
        ignition_jitter = (_noise(context.seed, 0, 0, row, column) & 0xFFFF) / 0xFFFF
        burn_jitter = (_noise(context.seed, 0, 1, row, column) & 0xFFFF) / 0xFFFF
        start = round(total_frames * (0.01 + height_delay * 0.58 + ignition_jitter * 0.08))
        sparse_fuel_extension = 0.3 / math.sqrt(max(1, fuel_count))
        lifetime = max(
            2,
            round(total_frames * (0.025 + burn_jitter * 0.025 + sparse_fuel_extension)),
        )
        fuel_starts[index] = max(1, start)
        fuel_ends[index] = fuel_starts[index] + lifetime
        fuel_intensities[index] = 24 + round(burn_jitter * (_MAX_INTENSITY - 24))

    return _FireState(
        [0] * (width * (height + 1)),
        [False] * cell_count,
        fuel_starts,
        fuel_ends,
        fuel_intensities,
    )


def _advance_generation(
    state: _FireState,
    *,
    width: int,
    height: int,
    seed: int,
    frame: int,
    generation: int,
    total_frames: int,
) -> None:
    previous = state.intensities
    values = [0] * len(previous)

    for row in range(height):
        below_row = (row + 1) * width
        target_row = row * width
        for column in range(width):
            noise = _noise(seed, frame, generation, row, column)
            source_column = min(width - 1, max(0, column + (noise % 3) - 1))
            decay = (noise >> 3) & 1
            if frame / max(1, total_frames) >= 0.68:
                decay += 1
            intensity = max(0, previous[below_row + source_column] - decay)
            values[target_row + column] = intensity
            if intensity >= 4:
                state.burned[target_row + column] = True

    for index, maximum_intensity in enumerate(state.fuel_intensities):
        if not maximum_intensity or not state.fuel_starts[index] <= frame < state.fuel_ends[index]:
            continue
        lifetime = state.fuel_ends[index] - state.fuel_starts[index]
        remaining = state.fuel_ends[index] - frame
        intensity = max(4, round(maximum_intensity * remaining / lifetime))
        flicker = _noise(seed, frame, generation, index // width, index % width) % 4
        values[index] = max(values[index], intensity - flicker)
        state.burned[index] = True
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
            self._state = _new_state(context, 1)
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
            self._state = _new_state(context, total_frames)

        generations_per_frame = max(1, math.ceil(height / max(1, total_frames * 0.5)))
        while self._state.frame < target_frame:
            next_frame = self._state.frame + 1
            for generation in range(generations_per_frame):
                _advance_generation(
                    self._state,
                    width=context.width,
                    height=height,
                    seed=context.seed,
                    frame=next_frame,
                    generation=generation,
                    total_frames=total_frames,
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

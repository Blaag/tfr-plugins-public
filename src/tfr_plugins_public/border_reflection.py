from __future__ import annotations

import random
from collections.abc import Mapping
from typing import Any

from tfr.plugin_api import BorderCellContext, BorderFragment, PluginRegistrar

_BORDER_COLORS = {
    "output": (95, 135, 175),
    "input": (135, 175, 255),
}


def _circular_distance(first: float, second: float, perimeter: int) -> float:
    distance = abs(first - second)
    return min(distance, perimeter - distance)


def reflection_intensity(
    context: BorderCellContext,
    *,
    progress: float,
    gradient_cells: float,
) -> float:
    progress = min(1.0, max(0.0, progress))
    if progress < 0.08:
        travel = 0.0
        strength = progress / 0.08
    elif progress < 0.82:
        travel = (progress - 0.08) / 0.74
        strength = 1.0
    else:
        travel = 1.0
        strength = 1.0 - (progress - 0.82) / 0.18

    meeting_index = context.perimeter_length / 2
    clockwise = travel * meeting_index
    counterclockwise = (-travel * meeting_index) % context.perimeter_length
    distance = min(
        _circular_distance(context.perimeter_index, clockwise, context.perimeter_length),
        _circular_distance(context.perimeter_index, counterclockwise, context.perimeter_length),
    )
    return strength * max(0.0, 1.0 - distance / gradient_cells)


class ReflectionSchedule:
    def __init__(
        self,
        *,
        minimum_interval_seconds: float,
        maximum_interval_seconds: float,
        rng: random.Random | None = None,
    ) -> None:
        self.minimum_interval_seconds = minimum_interval_seconds
        self.maximum_interval_seconds = maximum_interval_seconds
        self.rng = rng or random.Random()
        self.active_start: float | None = None
        self.next_start = self.rng.uniform(
            minimum_interval_seconds,
            maximum_interval_seconds,
        )

    def progress(self, elapsed_seconds: float, duration_seconds: float) -> float | None:
        if self.active_start is not None:
            progress = (elapsed_seconds - self.active_start) / duration_seconds
            if progress < 1:
                return max(0.0, progress)
            self.active_start = None
        if elapsed_seconds < self.next_start:
            return None
        self.active_start = elapsed_seconds
        self.next_start = elapsed_seconds + self.rng.uniform(
            self.minimum_interval_seconds,
            self.maximum_interval_seconds,
        )
        return 0.0

    def frame_delay(
        self,
        elapsed_seconds: float,
        *,
        duration_seconds: float,
        frames_per_second: float,
    ) -> float:
        if self.progress(elapsed_seconds, duration_seconds) is not None:
            return 1 / frames_per_second
        return max(0.0, self.next_start - elapsed_seconds)


def reflect_border(
    context: BorderCellContext,
    fragment: BorderFragment,
    *,
    progress: float,
    gradient_cells: float,
) -> BorderFragment:
    intensity = reflection_intensity(
        context,
        progress=progress,
        gradient_cells=gradient_cells,
    )
    if intensity <= 0:
        return fragment
    red, green, blue = _BORDER_COLORS.get(context.panel, (128, 128, 128))
    reflected = tuple(
        round(channel + (255 - channel) * intensity) for channel in (red, green, blue)
    )
    color = "#" + "".join(f"{channel:02x}" for channel in reflected)
    return BorderFragment(fragment.character, f"{fragment.style} fg:{color}")


class BorderReflectionPlugin:
    api_version = 1

    def register(self, registrar: PluginRegistrar, config: Mapping[str, Any]) -> None:
        frames_per_second = float(config.get("frames_per_second", 24))
        duration_seconds = float(config.get("duration_seconds", 1.2))
        gradient_cells = float(config.get("gradient_cells", 8))
        minimum_interval_seconds = float(config.get("minimum_interval_seconds", 30))
        maximum_interval_seconds = float(config.get("maximum_interval_seconds", 120))
        if not 0.5 <= duration_seconds <= 10:
            raise ValueError("duration_seconds must be between 0.5 and 10")
        if not 1 <= gradient_cells <= 40:
            raise ValueError("gradient_cells must be between 1 and 40")
        if not duration_seconds <= minimum_interval_seconds <= maximum_interval_seconds <= 3600:
            raise ValueError("reflection intervals must be ordered and no longer than 3600 seconds")
        schedule = ReflectionSchedule(
            minimum_interval_seconds=minimum_interval_seconds,
            maximum_interval_seconds=maximum_interval_seconds,
        )

        def transform(context: BorderCellContext, fragment: BorderFragment) -> BorderFragment:
            progress = schedule.progress(context.elapsed_seconds, duration_seconds)
            if progress is None:
                return fragment
            return reflect_border(
                context,
                fragment,
                progress=progress,
                gradient_cells=gradient_cells,
            )

        registrar.register_border_effect(
            "border_reflection",
            transform,
            frames_per_second=frames_per_second,
            frame_delay=lambda elapsed_seconds: schedule.frame_delay(
                elapsed_seconds,
                duration_seconds=duration_seconds,
                frames_per_second=frames_per_second,
            ),
        )


plugin = BorderReflectionPlugin()

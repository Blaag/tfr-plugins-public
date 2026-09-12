from __future__ import annotations

import random

import pytest
from tfr.borders import BorderCellContext, BorderEdge, BorderFragment
from tfr.core import CommandBus, EventBus
from tfr.plugins import PluginManager

from tfr_plugins_public.border_reflection import (
    ReflectionSchedule,
    reflect_border,
    reflection_intensity,
)


def context(index: int, elapsed_seconds: float, *, panel: str = "output") -> BorderCellContext:
    return BorderCellContext(
        panel=panel,
        world="alpha",
        edge=BorderEdge.TOP,
        edge_index=0,
        perimeter_index=index,
        perimeter_length=40,
        width=16,
        height=10,
        focused=True,
        elapsed_seconds=elapsed_seconds,
    )


def intensity(index: int, progress: float) -> float:
    return reflection_intensity(
        context(index, progress * 1.2),
        progress=progress,
        gradient_cells=8,
    )


def test_reflection_splits_from_top_left_and_meets_at_bottom_right() -> None:
    assert intensity(0, 0) == 0
    assert intensity(0, 0.04) == pytest.approx(0.5)
    assert intensity(0, 0.08) == 1

    assert intensity(10, 0.45) == pytest.approx(1)
    assert intensity(30, 0.45) == pytest.approx(1)
    assert intensity(20, 0.45) == 0

    assert intensity(20, 0.82) == pytest.approx(1)
    assert intensity(20, 0.91) == pytest.approx(0.5)


def test_reflection_schedule_waits_randomly_between_thirty_and_120_seconds() -> None:
    schedule = ReflectionSchedule(
        minimum_interval_seconds=30,
        maximum_interval_seconds=120,
        rng=random.Random(42),
    )
    first_start = schedule.next_start

    assert 30 <= first_start <= 120
    assert schedule.progress(first_start - 0.01, 1.2) is None
    assert schedule.progress(first_start, 1.2) == 0
    assert schedule.progress(first_start + 0.6, 1.2) == pytest.approx(0.5)
    assert schedule.frame_delay(
        first_start + 0.6,
        duration_seconds=1.2,
        frames_per_second=24,
    ) == pytest.approx(1 / 24)
    assert 30 <= schedule.next_start - first_start <= 120


async def test_bundled_reflection_uses_each_panels_native_color() -> None:
    manager = await PluginManager.load(
        enabled=("border_reflection",),
        config={"border_reflection": {}},
        event_bus=EventBus(),
        command_bus=CommandBus(),
        targets={},
        scope="ui",
    )

    assert set(manager.registry.border_effects) == {"border_reflection"}
    assert manager.border_frames_per_second == 24
    idle_delay = manager.border_frame_delay(0)
    assert idle_delay is not None
    assert 30 <= idle_delay <= 120

    output = reflect_border(
        context(0, 1.2 * 0.04),
        BorderFragment("─", "class:border.output"),
        progress=0.04,
        gradient_cells=8,
    )
    input_border = reflect_border(
        context(0, 1.2 * 0.04, panel="input"),
        BorderFragment("─", "class:border.input"),
        progress=0.04,
        gradient_cells=8,
    )

    assert output.style == "class:border.output fg:#afc3d7"
    assert input_border.style == "class:border.input fg:#c3d7ff"

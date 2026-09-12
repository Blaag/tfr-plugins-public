from __future__ import annotations

from dataclasses import replace

from tfr.borders import BorderCellContext, BorderEdge, BorderFragment
from tfr.core import CommandBus, EventBus
from tfr.plugins import PluginManager


async def test_bundled_marching_ants_plugin_is_discoverable() -> None:
    manager = await PluginManager.load(
        enabled=("marching_ants",),
        config={"marching_ants": {"frames_per_second": 10}},
        event_bus=EventBus(),
        command_bus=CommandBus(),
        targets={},
        scope="ui",
    )

    assert set(manager.registry.border_effects) == {"marching_ants"}
    assert manager.border_frames_per_second == 10


async def test_marching_ants_pattern_moves_around_the_perimeter() -> None:
    manager = await PluginManager.load(
        enabled=("marching_ants",),
        config={},
        event_bus=EventBus(),
        command_bus=CommandBus(),
        targets={},
        scope="ui",
    )
    context = BorderCellContext(
        panel="output",
        world="alpha",
        edge=BorderEdge.TOP,
        edge_index=0,
        perimeter_index=0,
        perimeter_length=20,
        width=8,
        height=4,
        focused=True,
        elapsed_seconds=0,
    )
    fragment = BorderFragment("─", "class:border.output")

    first = manager.transform_border(context, fragment)
    moved = manager.transform_border(replace(context, elapsed_seconds=3 / 8), fragment)

    assert first.style.endswith(" reverse")
    assert moved == fragment

    next_cell = manager.transform_border(replace(context, perimeter_index=3), fragment)
    next_cell_moved = manager.transform_border(
        replace(context, perimeter_index=3, elapsed_seconds=1 / 8),
        fragment,
    )
    assert next_cell == fragment
    assert next_cell_moved.style.endswith(" reverse")

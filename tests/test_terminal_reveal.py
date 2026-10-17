from __future__ import annotations

from dataclasses import dataclass
from string import ascii_letters, digits, punctuation
from uuid import UUID

import pytest
from tfr.core import CommandBus, EventBus
from tfr.events import Direction, Event, EventKind
from tfr.plugins import PluginManager

from tfr_plugins_public.terminal_reveal import plugin


@dataclass
class FakeEntryPoint:
    name: str
    plugin: object

    def load(self) -> object:
        return self.plugin


def event(
    text: str,
    *,
    kind: EventKind = EventKind.RAW_OUTPUT,
    world: str = "alpha",
    event_id: int = 7,
) -> Event:
    return Event(
        session_id=UUID(int=1),
        world=world,
        connection_generation=1,
        sequence=1,
        direction=Direction.INBOUND,
        kind=kind,
        canonical_text=text,
        plain_text=text,
        display_text=text,
        event_id=UUID(int=event_id),
    )


async def load(config: dict[str, object]) -> PluginManager:
    return await PluginManager.load(
        enabled=("terminal_reveal",),
        config={"terminal_reveal": config},
        event_bus=EventBus(),
        command_bus=CommandBus(),
        targets={},
        discovered=(FakeEntryPoint("terminal_reveal", plugin),),
        scope="ui",
    )


async def test_default_configuration_models_9600_baud_serial_text() -> None:
    manager = await load({})
    incoming = event("\x1b[1mhello\x1b[0m\n")

    program = manager.presentation_programs(incoming, "hello")[0]
    reveal = program.variants[0].character_reveal

    assert reveal is not None
    assert program.start == 0
    assert program.end == 5
    assert 9600 * 0.75 <= 20 / reveal.interval_seconds <= 9600 * 1.25
    assert program.frames_per_second == 30
    assert reveal.glitch_width == 3
    assert reveal.settle_width == 3
    assert reveal.glitch_characters == ascii_letters + digits + punctuation
    assert reveal.accent_color == "#ffffff"
    assert reveal.base_color == "#d7d7d7"
    assert reveal.seed == 7
    assert reveal.inline_glitch_chance == 0.05


async def test_each_line_gets_a_stable_speed_within_the_configured_variation() -> None:
    manager = await load(
        {"baud_rate": 300, "speed_variation": 0.25, "maximum_duration_seconds": 30}
    )

    intervals = [
        manager.presentation_programs(event("hello", event_id=event_id), "hello")[0]
        .variants[0]
        .character_reveal.interval_seconds
        for event_id in range(1, 9)
    ]
    repeated = manager.presentation_programs(event("hello", event_id=1), "hello")[0]

    assert len(set(intervals)) > 1
    assert all(300 * 0.75 <= 20 / interval <= 300 * 1.25 for interval in intervals)
    assert repeated.variants[0].character_reveal.interval_seconds == intervals[0]


async def test_configuration_filters_worlds_and_event_kinds() -> None:
    manager = await load(
        {
            "baud_rate": 1200,
            "frames_per_second": 20,
            "glitch_width": 2,
            "glitch_characters": "#%",
            "glitch_color": "#00ff00",
            "trail_color": "#204060",
            "speed_variation": 0,
            "inline_glitch_chance": 0.2,
            "kinds": ["say"],
            "worlds": ["Alpha"],
        }
    )

    matching = manager.presentation_programs(event("hello", kind=EventKind.SAY), "hello")
    reveal = matching[0].variants[0].character_reveal

    assert reveal.interval_seconds == pytest.approx(20 / 1200)
    assert reveal.accent_color == "#00ff00"
    assert reveal.base_color == "#204060"
    assert reveal.glitch_characters == "#%"
    assert reveal.inline_glitch_chance == 0.2
    assert (
        manager.presentation_programs(event("hello", kind=EventKind.PAGE, event_id=8), "hello")
        == ()
    )
    assert (
        manager.presentation_programs(
            event("hello", kind=EventKind.SAY, world="beta", event_id=9), "hello"
        )
        == ()
    )


async def test_long_lines_are_bounded_or_accelerated() -> None:
    skipped = await load({"maximum_characters": 4})
    accelerated = await load(
        {
            "baud_rate": 100,
            "glitch_width": 2,
            "maximum_duration_seconds": 0.5,
        }
    )

    assert skipped.presentation_programs(event("hello"), "hello") == ()
    program = accelerated.presentation_programs(event("abcdefghij"), "abcdefghij")[0]
    assert program.duration_seconds == pytest.approx(0.5)


@pytest.mark.parametrize(
    "config",
    [
        {"baud_rate": 0},
        {"frames_per_second": 31},
        {"glitch_width": 0},
        {"settle_width": 21},
        {"speed_variation": 0.96},
        {"inline_glitch_chance": 1.01},
        {"glitch_characters": " "},
        {"trail_color": "gray"},
        {"maximum_characters": 4_097},
        {"maximum_duration_seconds": 31},
        {"kinds": ["not_an_event"]},
        {"unknown": True},
    ],
)
async def test_invalid_configuration_does_not_register_the_decorator(
    config: dict[str, object],
) -> None:
    manager = await load(config)

    assert manager.registry.presentation_decorators == {}

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

import pytest
from tfr.core import CommandBus, EventBus
from tfr.eventlog import serialize_event
from tfr.events import Direction, Event, EventKind
from tfr.plugins import (
    PluginCommandContext,
    PluginManager,
    PluginRegistrar,
    PluginRegistrationError,
    PluginRegistry,
)
from tfr.replay import event_from_dict

import tfr_plugins_public.gag as gag_module
from tfr_plugins_public.gag import GagPlugin


@dataclass
class FakeEntryPoint:
    name: str
    plugin: object

    def load(self) -> object:
        return self.plugin


class MemorySink:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def write(self, event: Event) -> None:
        self.events.append(event)

    async def close(self) -> None:
        pass


def event(
    text: str,
    *,
    world: str = "alpha",
    direction: Direction = Direction.INBOUND,
) -> Event:
    return Event(
        session_id=UUID(int=1),
        world=world,
        connection_generation=1,
        sequence=1,
        direction=direction,
        kind=EventKind.RAW_OUTPUT,
        canonical_text=text,
        plain_text=text,
        display_text=text,
    )


def register(plugin: GagPlugin, worlds: object) -> PluginRegistry:
    registry = PluginRegistry()
    plugin.register(PluginRegistrar("gag", registry, "ui"), {"worlds": worlds})
    return registry


def context(world: str = "alpha") -> tuple[PluginCommandContext, list[str]]:
    notices: list[str] = []
    command_context = PluginCommandContext(
        plugin="gag",
        world=world,
        targets={},
        command_bus=CommandBus(),
        notice=lambda notice_world, text: notices.append(f"{notice_world}: {text}"),
    )
    return command_context, notices


def test_gag_lists_configured_world_local_expressions() -> None:
    plugin = GagPlugin()
    registry = register(plugin, {"alpha": [r"^spam", "foo bar", r"^spam"]})
    alpha, alpha_notices = context()
    beta, beta_notices = context("beta")

    plugin.command(alpha, ("LIST",))
    plugin.command(beta, ())

    assert plugin.active_expressions("alpha") == (r"^spam", "foo bar")
    assert "1. ^spam\n  2. foo bar" in alpha_notices[-1]
    assert beta_notices == ["beta: No active gag expressions for beta."]
    assert "gag" in registry.commands
    assert "gag" in registry.display_transforms

    with pytest.raises(ValueError, match=r"usage: /gag \[list\]"):
        plugin.command(alpha, ("remove", r"^spam"))


@pytest.mark.parametrize(
    ("worlds", "message"),
    [
        ([], "worlds must be an object"),
        ({"": ["hidden"]}, "world names must be non-empty strings"),
        ({"alpha": "hidden"}, "expressions for alpha must be a list"),
        ({"alpha": [7]}, "expressions for alpha must contain strings"),
        ({"alpha": ["[invalid"]}, "invalid gag expression for alpha"),
        ({"alpha": ["x" * 1_001]}, "cannot exceed 1000 characters"),
        (
            {"alpha": [f"expression-{index}" for index in range(101)]},
            "cannot contain more than 100 entries",
        ),
    ],
)
def test_gag_rejects_invalid_configuration(worlds: object, message: str) -> None:
    with pytest.raises(PluginRegistrationError, match=message):
        register(GagPlugin(), worlds)


def test_gag_fails_open_when_match_budget_is_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = GagPlugin()
    register(plugin, {"alpha": [r"(a|aa)+$"]})
    monkeypatch.setattr(gag_module, "_MATCH_BUDGET_SECONDS", 0)
    incoming = "a" * 1_000 + "b"

    assert plugin.transform(event(incoming), incoming) == incoming


def test_gag_matches_visible_ansi_text_only_for_inbound_events() -> None:
    plugin = GagPlugin()
    register(plugin, {"alpha": [r"^Error: disk \d+$"]})
    styled = "\x1b[31mError: disk 7\x1b[0m"

    assert plugin.transform(event(styled), styled) is None
    assert plugin.transform(event("Error: disk x"), "Error: disk x") == "Error: disk x"
    assert plugin.transform(event(styled, direction=Direction.OUTBOUND), styled) == styled
    assert plugin.transform(event(styled, world="beta"), styled) == styled


async def test_gag_suppresses_display_without_removing_canonical_event() -> None:
    sink = MemorySink()
    event_bus = EventBus([sink])
    plugin = GagPlugin()
    manager = await PluginManager.load(
        enabled=("gag",),
        config={"gag": {"worlds": {"alpha": ["secret"]}}},
        event_bus=event_bus,
        command_bus=CommandBus(),
        targets={},
        discovered=(FakeEntryPoint("gag", plugin),),
        scope="ui",
    )
    notices: list[tuple[str, str]] = []
    manager.set_notice_handler(lambda world, text: notices.append((world, text)))
    assert await manager.execute_command("gag", (), "alpha")
    incoming = event("a secret remains canonical")

    await event_bus.publish(incoming)

    assert sink.events == [incoming]
    assert sink.events[0].canonical_text == "a secret remains canonical"
    assert manager.transform_display(sink.events[0]) is None
    assert event_from_dict(json.loads(serialize_event(sink.events[0]))) == incoming
    assert notices == [("alpha", "Active gag expressions for alpha:\n  1. secret")]


def test_gag_rejects_unknown_configuration() -> None:
    with pytest.raises(PluginRegistrationError, match="unknown gag fields: expressions"):
        GagPlugin().register(
            PluginRegistrar("gag", PluginRegistry(), "ui"),
            {"expressions": ["hidden"]},
        )

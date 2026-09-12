from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from tfr.core import CommandBus, EventBus
from tfr.plugin_api import PluginCommandContext, PluginWorldInfo, escape_world_text
from tfr.plugins import PluginManager, PluginRegistrar, PluginRegistry

from tfr_plugins_public.cat import CatPlugin


def context(
    command_bus: CommandBus,
    session_id: UUID,
    *,
    server: str = "tinymux",
    encoding: str = "utf-8",
) -> PluginCommandContext:
    return PluginCommandContext(
        plugin="cat",
        world="alpha",
        targets={"alpha": session_id},
        command_bus=command_bus,
        worlds={"alpha": PluginWorldInfo(server=server, encoding=encoding)},
    )


def test_escape_line_preserves_whitespace_and_uses_server_rules() -> None:
    text = " a\t[%]{x}(),;#\\"

    assert escape_world_text(text, "bare") == text
    assert escape_world_text(text, "tinymux") == r"%ba%t\[\%\]\{x\}\(\)\,\;\#\\"
    assert escape_world_text(text, "tinymush") == r"%ba%t\[\%\]\{x\}(),\;#\\"


async def test_cat_sends_first_line_immediately_then_paces_remaining_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "message with spaces.txt"
    source.write_text("one\r\n two\n\n", encoding="utf-8")
    command_bus = CommandBus()
    session_id = uuid4()
    queue = command_bus.register(session_id)
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("tfr_plugins_public.cat.asyncio.sleep", sleep)
    plugin = CatPlugin()

    await plugin.command(context(command_bus, session_id), (str(source),))

    requests = [queue.get_nowait(), queue.get_nowait(), queue.get_nowait()]
    assert [request.text for request in requests] == ["@emit one", "@emit %btwo", "@emit "]
    assert sleeps == [0.5, 0.5]
    assert requests[0].metadata == {"cat_line": 1, "cat_total_lines": 3}
    assert requests[2].metadata == {"cat_line": 3, "cat_total_lines": 3}
    assert plugin.active_worlds == set()


async def test_cat_preflights_all_lines_before_submitting(tmp_path: Path) -> None:
    source = tmp_path / "message.txt"
    source.write_text("short\nthis line is too long\n", encoding="utf-8")
    command_bus = CommandBus()
    session_id = uuid4()
    queue = command_bus.register(session_id)
    plugin = CatPlugin()
    plugin.maximum_command_bytes = 15

    with pytest.raises(ValueError, match="line 2"):
        await plugin.command(context(command_bus, session_id), (str(source),))

    assert queue.empty()
    assert plugin.active_worlds == set()


async def test_cat_rejects_unknown_server_type(tmp_path: Path) -> None:
    source = tmp_path / "message.txt"
    source.write_text("hello\n", encoding="utf-8")
    command_bus = CommandBus()
    session_id = uuid4()
    command_bus.register(session_id)

    with pytest.raises(ValueError, match="bare, tinymush, or tinymux"):
        await CatPlugin().command(
            context(command_bus, session_id, server="generic"),
            (str(source),),
        )


async def test_bundled_cat_plugin_is_discoverable() -> None:
    manager = await PluginManager.load(
        enabled=("cat",),
        config={"cat": {"delay_seconds": 0}},
        event_bus=EventBus(),
        command_bus=CommandBus(),
        targets={},
    )

    assert "cat" in manager.registry.commands


@pytest.mark.parametrize(
    "config",
    [
        {"delay_seconds": float("nan")},
        {"delay_seconds": float("inf")},
        {"delay_seconds": 61},
        {"maximum_bytes": 1_048_577},
        {"maximum_lines": 10_001},
        {"maximum_command_bytes": 7_001},
    ],
)
def test_cat_configuration_cannot_remove_resource_bounds(config: dict[str, object]) -> None:
    plugin = CatPlugin()
    registrar = PluginRegistrar("cat", PluginRegistry(), "ui")

    with pytest.raises(ValueError):
        plugin.register(registrar, config)

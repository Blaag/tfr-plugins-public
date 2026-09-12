from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tfr.plugin_api import PluginCommandContext, PluginRegistrar, escape_world_text


def _read_lines(path: Path, maximum_bytes: int) -> tuple[str, ...]:
    with path.open("rb") as source:
        content = source.read(maximum_bytes + 1)
    if len(content) > maximum_bytes:
        raise ValueError(f"file exceeds {maximum_bytes} byte limit")

    text = content.decode("utf-8-sig")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and not lines[-1]:
        lines.pop()
    return tuple(lines)


def _positive_integer(
    config: Mapping[str, Any],
    name: str,
    default: int,
    maximum: int,
) -> int:
    value = config.get(name, default)
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"cat plugin {name} must be an integer between 1 and {maximum}")
    return value


class CatPlugin:
    api_version = 1

    def __init__(self) -> None:
        self.delay_seconds = 0.5
        self.maximum_bytes = 1_048_576
        self.maximum_lines = 10_000
        self.maximum_command_bytes = 7_000
        self.active_worlds: set[str] = set()

    def register(self, registrar: PluginRegistrar, config: Mapping[str, Any]) -> None:
        delay = config.get("delay_seconds", 0.5)
        if (
            isinstance(delay, bool)
            or not isinstance(delay, int | float)
            or not math.isfinite(delay)
            or not 0 <= delay <= 60
        ):
            raise ValueError("cat plugin delay_seconds must be between 0 and 60")
        self.delay_seconds = float(delay)
        self.maximum_bytes = _positive_integer(config, "maximum_bytes", 1_048_576, 1_048_576)
        self.maximum_lines = _positive_integer(config, "maximum_lines", 10_000, 10_000)
        self.maximum_command_bytes = _positive_integer(
            config, "maximum_command_bytes", 7_000, 7_000
        )
        registrar.register_command(
            "cat",
            self.command,
            help="send a UTF-8 file as paced @emit lines",
        )

    async def command(
        self,
        context: PluginCommandContext,
        arguments: tuple[str, ...],
    ) -> None:
        if len(arguments) != 1:
            raise ValueError("usage: /cat <file>")
        if context.world in self.active_worlds:
            raise RuntimeError(f"a /cat transfer is already active for {context.world}")

        server = context.world_info.server
        if server not in {"bare", "tinymush", "tinymux"}:
            raise ValueError("/cat requires a bare, tinymush, or tinymux world")

        self.active_worlds.add(context.world)
        try:
            path = Path(arguments[0]).expanduser()
            lines = await asyncio.to_thread(_read_lines, path, self.maximum_bytes)
            if len(lines) > self.maximum_lines:
                raise ValueError(f"file exceeds {self.maximum_lines} line limit")

            commands = tuple(f"@emit {escape_world_text(line, server)}" for line in lines)
            encoding = context.world_info.encoding
            for line_number, command in enumerate(commands, start=1):
                try:
                    command_size = len(command.encode(encoding, errors="strict"))
                except (LookupError, UnicodeEncodeError) as exc:
                    raise ValueError(f"line {line_number} cannot be encoded as {encoding}") from exc
                if command_size > self.maximum_command_bytes:
                    raise ValueError(
                        f"line {line_number} exceeds the "
                        f"{self.maximum_command_bytes} byte command limit"
                    )

            for line_number, command in enumerate(commands, start=1):
                if line_number > 1:
                    await asyncio.sleep(self.delay_seconds)
                await context.submit(
                    command,
                    metadata={
                        "cat_line": line_number,
                        "cat_total_lines": len(commands),
                    },
                )
        finally:
            self.active_worlds.discard(context.world)


plugin = CatPlugin()

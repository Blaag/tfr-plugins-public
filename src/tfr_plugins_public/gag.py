from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

import regex
from tfr.plugin_api import (
    PLUGIN_API_VERSION,
    Direction,
    Event,
    PluginCommandContext,
    PluginRegistrar,
    PluginRegistrationError,
    terminal_plain_text,
)

_MAX_ACTIVE_EXPRESSIONS = 100
_MAX_EXPRESSION_CHARACTERS = 1_000
_MATCH_BUDGET_SECONDS = 0.01


class GagPlugin:
    api_version = PLUGIN_API_VERSION

    def __init__(self) -> None:
        self._expressions: dict[str, dict[str, regex.Pattern[str]]] = {}

    def register(self, registrar: PluginRegistrar, config: Mapping[str, Any]) -> None:
        unknown = set(config) - {"worlds"}
        if unknown:
            raise PluginRegistrationError("unknown gag fields: " + ", ".join(sorted(unknown)))
        configured = self._compile_config(config.get("worlds", {}))
        registrar.register_command(
            "gag",
            self.command,
            help="list configured regular expressions that hide inbound output",
        )
        registrar.register_display_transform("gag", self.transform)
        self._expressions = configured

    @staticmethod
    def _compile_config(worlds: Any) -> dict[str, dict[str, regex.Pattern[str]]]:
        if not isinstance(worlds, Mapping):
            raise PluginRegistrationError("gag worlds must be an object")

        configured: dict[str, dict[str, regex.Pattern[str]]] = {}
        for world, expressions in worlds.items():
            if not isinstance(world, str) or not world:
                raise PluginRegistrationError("gag world names must be non-empty strings")
            if not isinstance(expressions, list):
                raise PluginRegistrationError(f"gag expressions for {world} must be a list")
            if len(expressions) > _MAX_ACTIVE_EXPRESSIONS:
                raise PluginRegistrationError(
                    f"gag expressions for {world} cannot contain more than "
                    f"{_MAX_ACTIVE_EXPRESSIONS} entries"
                )

            patterns: dict[str, regex.Pattern[str]] = {}
            for expression in expressions:
                if not isinstance(expression, str):
                    raise PluginRegistrationError(
                        f"gag expressions for {world} must contain strings"
                    )
                if len(expression) > _MAX_EXPRESSION_CHARACTERS:
                    raise PluginRegistrationError(
                        f"gag expressions cannot exceed {_MAX_EXPRESSION_CHARACTERS} characters"
                    )
                if expression in patterns:
                    continue
                try:
                    patterns[expression] = regex.compile(expression)
                except regex.error as exc:
                    raise PluginRegistrationError(
                        f"invalid gag expression for {world}: {expression!r}: {exc}"
                    ) from exc
            configured[world] = patterns
        return configured

    def active_expressions(self, world: str) -> tuple[str, ...]:
        return tuple(self._expressions.get(world, ()))

    def command(self, context: PluginCommandContext, arguments: tuple[str, ...]) -> None:
        if arguments and not (len(arguments) == 1 and arguments[0].casefold() == "list"):
            raise ValueError("usage: /gag [list]")
        self._list(context)

    def _list(self, context: PluginCommandContext) -> None:
        expressions = self.active_expressions(context.world)
        if expressions:
            context.notice(
                "Active gag expressions for "
                f"{context.world}:\n"
                + "\n".join(
                    f"  {index}. {expression}" for index, expression in enumerate(expressions, 1)
                )
            )
        else:
            context.notice(f"No active gag expressions for {context.world}.")

    def transform(self, event: Event, text: str) -> str | None:
        if event.direction is not Direction.INBOUND:
            return text
        expressions = self._expressions.get(event.world)
        if not expressions:
            return text
        visible_text = terminal_plain_text(text)
        deadline = time.monotonic() + _MATCH_BUDGET_SECONDS
        for pattern in expressions.values():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                if pattern.search(visible_text, timeout=remaining):
                    return None
            except TimeoutError:
                break
        return text


plugin = GagPlugin()

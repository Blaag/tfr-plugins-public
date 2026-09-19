from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from string import ascii_letters, digits, punctuation
from typing import Any

from tfr.plugin_api import (
    PLUGIN_API_VERSION,
    Event,
    EventKind,
    PluginRegistrar,
    PluginRegistrationError,
    TextDecoration,
    TextEffectKind,
    terminal_plain_text,
    validate_color,
)

_FIELDS = frozenset(
    {
        "baud_rate",
        "frames_per_second",
        "glitch_width",
        "glitch_characters",
        "glitch_color",
        "inline_glitch_chance",
        "kinds",
        "maximum_characters",
        "maximum_duration_seconds",
        "settle_width",
        "speed_variation",
        "trail_color",
        "worlds",
    }
)

_UINT64_MASK = (1 << 64) - 1


def _positive_number(value: object, field: str, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PluginRegistrationError(f"terminal_reveal {field} must be a number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise PluginRegistrationError(f"terminal_reveal {field} must be positive")
    return result


def _fraction(value: object, field: str, default: float, maximum: float = 1.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PluginRegistrationError(f"terminal_reveal {field} must be a number")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= maximum:
        raise PluginRegistrationError(f"terminal_reveal {field} must be between 0 and {maximum:g}")
    return result


def _event_unit_interval(seed: int) -> float:
    value = (seed + 0x9E3779B97F4A7C15) & _UINT64_MASK
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & _UINT64_MASK
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & _UINT64_MASK
    return (value ^ (value >> 31)) / _UINT64_MASK


def _string_list(value: object, field: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise PluginRegistrationError(f"terminal_reveal {field} must be a list")
    result = tuple(value)
    if not result or any(not isinstance(item, str) or not item for item in result):
        raise PluginRegistrationError(f"terminal_reveal {field} must contain strings")
    return result


class TerminalRevealPlugin:
    api_version = PLUGIN_API_VERSION

    def register(self, registrar: PluginRegistrar, config: Mapping[str, Any]) -> None:
        unknown = set(config) - _FIELDS
        if unknown:
            raise PluginRegistrationError(
                "unknown terminal_reveal fields: " + ", ".join(sorted(unknown))
            )
        baud_rate = _positive_number(config.get("baud_rate"), "baud_rate", 1200.0)
        frames_per_second = _positive_number(
            config.get("frames_per_second"), "frames_per_second", 30.0
        )
        if frames_per_second > 30:
            raise PluginRegistrationError("terminal_reveal frames_per_second cannot exceed 30")
        speed_variation = _fraction(config.get("speed_variation"), "speed_variation", 0.25, 0.95)
        inline_glitch_chance = _fraction(
            config.get("inline_glitch_chance"), "inline_glitch_chance", 0.35
        )
        glitch_width = config.get("glitch_width", 3)
        if (
            not isinstance(glitch_width, int)
            or isinstance(glitch_width, bool)
            or not 1 <= glitch_width <= 20
        ):
            raise PluginRegistrationError(
                "terminal_reveal glitch_width must be an integer between 1 and 20"
            )
        maximum_characters = config.get("maximum_characters", 4096)
        if (
            not isinstance(maximum_characters, int)
            or isinstance(maximum_characters, bool)
            or not 1 <= maximum_characters <= 16_384
        ):
            raise PluginRegistrationError(
                "terminal_reveal maximum_characters must be an integer between 1 and 16384"
            )
        settle_width = config.get("settle_width", 3)
        if (
            not isinstance(settle_width, int)
            or isinstance(settle_width, bool)
            or not 0 <= settle_width <= 20
        ):
            raise PluginRegistrationError(
                "terminal_reveal settle_width must be an integer between 0 and 20"
            )
        maximum_duration_seconds = _positive_number(
            config.get("maximum_duration_seconds"), "maximum_duration_seconds", 10.0
        )
        if maximum_duration_seconds > 30:
            raise PluginRegistrationError(
                "terminal_reveal maximum_duration_seconds cannot exceed 30"
            )
        glitch_characters = config.get("glitch_characters", ascii_letters + digits + punctuation)
        if not isinstance(glitch_characters, str):
            raise PluginRegistrationError("terminal_reveal glitch_characters must be a string")
        if not glitch_characters or any(
            not character.isascii() or not character.isprintable() or character.isspace()
            for character in glitch_characters
        ):
            raise PluginRegistrationError(
                "terminal_reveal glitch_characters must contain visible ASCII characters"
            )
        try:
            glitch_color = validate_color(config.get("glitch_color", "#ffffff"))
            trail_color = validate_color(config.get("trail_color", "#d7d7d7"))
        except ValueError as exc:
            raise PluginRegistrationError(str(exc)) from exc
        try:
            kinds = frozenset(
                EventKind(value.casefold())
                for value in _string_list(
                    config.get("kinds", tuple(kind.value for kind in EventKind)), "kinds"
                )
            )
        except ValueError as exc:
            raise PluginRegistrationError(
                "terminal_reveal kinds contains an unknown event kind"
            ) from exc
        worlds_value = config.get("worlds")
        worlds = (
            frozenset(value.casefold() for value in _string_list(worlds_value, "worlds"))
            if worlds_value is not None
            else None
        )

        def decorate(event: Event, text: str) -> tuple[TextDecoration, ...]:
            if event.kind not in kinds:
                return ()
            if worlds is not None and event.world.casefold() not in worlds:
                return ()
            visible_text = terminal_plain_text(text).rstrip("\r\n")
            if not visible_text or len(visible_text) > maximum_characters:
                return ()
            speed_multiplier = 1 + speed_variation * (
                2 * _event_unit_interval(event.event_id.int) - 1
            )
            interval_seconds = min(
                20 / (baud_rate * speed_multiplier),
                maximum_duration_seconds / (len(visible_text) + glitch_width + settle_width),
            )
            return (
                TextDecoration(
                    start=0,
                    end=len(visible_text),
                    effect=TextEffectKind.TERMINAL_REVEAL,
                    base_color=trail_color,
                    accent_color=glitch_color,
                    interval_seconds=interval_seconds,
                    frames_per_second=frames_per_second,
                    loop=False,
                    effect_width=glitch_width,
                    seed=event.event_id.int & 0xFFFFFFFF,
                    glitch_characters=glitch_characters,
                    settle_width=settle_width,
                    inline_glitch_chance=inline_glitch_chance,
                ),
            )

        registrar.register_display_decorator("terminal-reveal", decorate)


plugin = TerminalRevealPlugin()

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from tfr.plugin_api import (
    PLUGIN_API_VERSION,
    Event,
    EventKind,
    PluginRegistrar,
    PluginRegistrationError,
    TextDecoration,
    TextEffectKind,
    derive_bright_color,
    terminal_plain_text,
    validate_color,
)

_SUPPORTED_KINDS = frozenset({EventKind.SAY, EventKind.POSE})
_RULE_FIELDS = frozenset(
    {
        "speaker",
        "effect",
        "color",
        "accent_color",
        "end_color",
        "period_seconds",
        "step_seconds",
        "duration_seconds",
        "repeat_seconds",
        "loop",
        "frames_per_second",
        "shimmer_width",
        "trail_width",
        "wave_width",
        "sparkle_count",
        "kinds",
        "worlds",
    }
)
_STEPPED_EFFECTS = {
    TextEffectKind.CAPITALIZATION_ROLL,
    TextEffectKind.CASE_WAVE,
}
_DURATION_DEFAULTS = {
    TextEffectKind.COMET: 1.2,
    TextEffectKind.SPARKLE: 1.2,
    TextEffectKind.UNDERLINE_SWEEP: 1.0,
    TextEffectKind.BOLD_SWEEP: 1.0,
    TextEffectKind.EMBER: 1.8,
    TextEffectKind.FROST: 1.6,
    TextEffectKind.RAINBOW_WAVE: 1.8,
    TextEffectKind.COLOR_PULSE: 1.2,
    TextEffectKind.REVERSE_SWEEP: 1.0,
    TextEffectKind.AGE_DECAY: 30.0,
}
_WAVE_WIDTH_EFFECTS = {
    TextEffectKind.UNDERLINE_SWEEP,
    TextEffectKind.BOLD_SWEEP,
    TextEffectKind.FROST,
    TextEffectKind.CASE_WAVE,
    TextEffectKind.REVERSE_SWEEP,
}
_ACCENT_EFFECTS = {
    TextEffectKind.SHIMMER,
    TextEffectKind.CAPITALIZATION_ROLL,
    TextEffectKind.COMET,
    TextEffectKind.SPARKLE,
    TextEffectKind.FROST,
    TextEffectKind.COLOR_PULSE,
    TextEffectKind.CASE_WAVE,
}
_SPEAKER_EFFECTS = frozenset(TextEffectKind) - {TextEffectKind.TERMINAL_REVEAL}


@dataclass(frozen=True, slots=True)
class SpeakerRule:
    speaker: str
    effect: TextEffectKind
    color: str
    accent_color: str
    interval_seconds: float
    repeat_seconds: float
    frames_per_second: float
    shimmer_width: float
    loop: bool
    effect_width: int
    sparkle_count: int
    kinds: frozenset[EventKind]
    worlds: frozenset[str] | None

    def decoration(self, event: Event, start: int, end: int) -> TextDecoration:
        return TextDecoration(
            start=start,
            end=end,
            effect=self.effect,
            base_color=self.color,
            accent_color=self.accent_color,
            interval_seconds=self.interval_seconds,
            repeat_seconds=self.repeat_seconds,
            frames_per_second=self.frames_per_second,
            shimmer_width=self.shimmer_width,
            loop=self.loop,
            effect_width=self.effect_width,
            sparkle_count=self.sparkle_count,
            seed=event.event_id.int & 0xFFFFFFFF,
        )


def _number(value: object, field: str, *, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PluginRegistrationError(f"speaker effect {field} must be a number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise PluginRegistrationError(f"speaker effect {field} must be positive")
    return result


def _strings(value: object, field: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise PluginRegistrationError(f"speaker effect {field} must be a list")
    values = tuple(value)
    if not values or any(not isinstance(item, str) or not item for item in values):
        raise PluginRegistrationError(f"speaker effect {field} must contain non-empty strings")
    return values


def _boolean(value: object, field: str, *, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise PluginRegistrationError(f"speaker effect {field} must be a boolean")
    return value


def _integer(value: object, field: str, *, default: int, maximum: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
        raise PluginRegistrationError(
            f"speaker effect {field} must be an integer between 1 and {maximum}"
        )
    return value


def _parse_rule(value: object) -> SpeakerRule:
    if not isinstance(value, Mapping):
        raise PluginRegistrationError("each speaker effect rule must be an object")
    unknown = set(value) - _RULE_FIELDS
    if unknown:
        raise PluginRegistrationError(
            "unknown speaker effect rule fields: " + ", ".join(sorted(unknown))
        )
    speaker = value.get("speaker")
    if not isinstance(speaker, str) or not speaker.strip():
        raise PluginRegistrationError("speaker effect speaker must be a non-empty string")
    try:
        effect = TextEffectKind(value.get("effect"))
    except (TypeError, ValueError) as exc:
        supported = ", ".join(effect.value for effect in _SPEAKER_EFFECTS)
        raise PluginRegistrationError(
            f"unsupported speaker effect; choose from {supported}"
        ) from exc
    if effect not in _SPEAKER_EFFECTS:
        supported = ", ".join(candidate.value for candidate in _SPEAKER_EFFECTS)
        raise PluginRegistrationError(f"unsupported speaker effect; choose from {supported}")
    try:
        if effect is TextEffectKind.AGE_DECAY:
            if "color" in value:
                raise PluginRegistrationError("age_decay uses end_color instead of color")
            color = validate_color(value.get("end_color"))
        else:
            if "end_color" in value:
                raise PluginRegistrationError("end_color is supported only by age_decay")
            color = validate_color(value.get("color"))
        if "accent_color" in value and effect not in _ACCENT_EFFECTS:
            raise PluginRegistrationError("accent_color is not supported by this effect")
        accent_value = value.get("accent_color")
        if accent_value is None:
            accent_color = (
                "#d7ffff" if effect is TextEffectKind.FROST else derive_bright_color(color)
            )
        else:
            accent_color = validate_color(accent_value)
    except ValueError as exc:
        raise PluginRegistrationError(str(exc)) from exc
    try:
        kinds = frozenset(
            EventKind(kind.casefold())
            for kind in _strings(value.get("kinds", ("say", "pose")), "kinds")
        )
    except ValueError as exc:
        raise PluginRegistrationError("speaker effect kinds support only say and pose") from exc
    if not kinds <= _SUPPORTED_KINDS:
        raise PluginRegistrationError("speaker effect kinds support only say and pose")
    worlds_value = value.get("worlds")
    worlds = (
        frozenset(world.casefold() for world in _strings(worlds_value, "worlds"))
        if worlds_value is not None
        else None
    )
    if "period_seconds" in value and effect is not TextEffectKind.SHIMMER:
        raise PluginRegistrationError("period_seconds is supported only by shimmer")
    if "step_seconds" in value and effect not in _STEPPED_EFFECTS:
        raise PluginRegistrationError(
            "step_seconds is supported only by capitalization_roll and case_wave"
        )
    if "duration_seconds" in value and effect not in _DURATION_DEFAULTS:
        raise PluginRegistrationError("duration_seconds is not supported by this effect")
    if effect is TextEffectKind.SHIMMER:
        interval = _number(value.get("period_seconds"), "period_seconds", default=1.4)
        burst_duration = interval
    elif effect in _STEPPED_EFFECTS:
        default_step = 0.5 if effect is TextEffectKind.CAPITALIZATION_ROLL else 0.2
        interval = _number(value.get("step_seconds"), "step_seconds", default=default_step)
        burst_duration = interval * len(speaker.strip())
    else:
        interval = _number(
            value.get("duration_seconds"),
            "duration_seconds",
            default=_DURATION_DEFAULTS[effect],
        )
        burst_duration = interval
    loop = _boolean(
        value.get("loop"),
        "loop",
        default=effect is not TextEffectKind.AGE_DECAY,
    )
    if not loop and "repeat_seconds" in value:
        raise PluginRegistrationError("repeat_seconds is supported only when loop is true")
    repeat_seconds = _number(value.get("repeat_seconds"), "repeat_seconds", default=10.0)
    if loop and repeat_seconds <= burst_duration:
        raise PluginRegistrationError(
            "speaker effect repeat_seconds must exceed its burst duration"
        )
    frames_per_second = _number(
        value.get("frames_per_second"),
        "frames_per_second",
        default=20.0,
    )
    if "frames_per_second" in value and effect in _STEPPED_EFFECTS:
        raise PluginRegistrationError(
            "frames_per_second is not used by capitalization effects; configure step_seconds"
        )
    if frames_per_second > 30:
        raise PluginRegistrationError("speaker effect frames_per_second cannot exceed 30")
    shimmer_width = _number(value.get("shimmer_width"), "shimmer_width", default=1.5)
    if "shimmer_width" in value and effect is not TextEffectKind.SHIMMER:
        raise PluginRegistrationError("shimmer_width is supported only by shimmer")
    if "trail_width" in value and effect is not TextEffectKind.COMET:
        raise PluginRegistrationError("trail_width is supported only by comet")
    if "sparkle_count" in value and effect is not TextEffectKind.SPARKLE:
        raise PluginRegistrationError("sparkle_count is supported only by sparkle")
    if "wave_width" in value and effect not in _WAVE_WIDTH_EFFECTS:
        raise PluginRegistrationError("wave_width is not supported by this effect")
    effect_width = _integer(
        value.get("trail_width") if effect is TextEffectKind.COMET else value.get("wave_width"),
        "trail_width" if effect is TextEffectKind.COMET else "wave_width",
        default=3 if effect is TextEffectKind.COMET else 2,
        maximum=20,
    )
    sparkle_count = _integer(
        value.get("sparkle_count"),
        "sparkle_count",
        default=2,
        maximum=10,
    )
    return SpeakerRule(
        speaker=speaker.strip(),
        effect=effect,
        color=color,
        accent_color=accent_color,
        interval_seconds=interval,
        repeat_seconds=repeat_seconds,
        frames_per_second=frames_per_second,
        shimmer_width=shimmer_width,
        loop=loop,
        effect_width=effect_width,
        sparkle_count=sparkle_count,
        kinds=kinds,
        worlds=worlds,
    )


def _speaker_span(event: Event, text: str, speaker: str) -> tuple[int, int] | None:
    plain = terminal_plain_text(text)
    prefix_end = plain.find("] ") if plain.startswith("[") else -1
    start = prefix_end + 2 if prefix_end >= 0 else 0
    while start < len(plain) and plain[start].isspace() and plain[start] not in "\r\n":
        start += 1
    end = start + len(speaker)
    if plain[start:end].casefold() != speaker.casefold():
        return None
    if end < len(plain) and (plain[end].isalnum() or plain[end] == "_"):
        return None
    if event.kind is EventKind.SAY:
        remainder = plain[end:].lstrip()
        if re.match(r"says?,", remainder, re.IGNORECASE) is None:
            return None
    return start, end


class SpeakerEffectsPlugin:
    api_version = PLUGIN_API_VERSION

    def register(self, registrar: PluginRegistrar, config: Mapping[str, Any]) -> None:
        unknown = set(config) - {"rules"}
        if unknown:
            raise PluginRegistrationError(
                "unknown speaker_effects fields: " + ", ".join(sorted(unknown))
            )
        rule_values = config.get("rules")
        if isinstance(rule_values, str) or not isinstance(rule_values, Sequence):
            raise PluginRegistrationError("speaker_effects rules must be a list")
        rules = tuple(_parse_rule(value) for value in rule_values)
        if not rules:
            raise PluginRegistrationError("speaker_effects requires at least one rule")

        def decorate(event: Event, text: str) -> tuple[TextDecoration, ...]:
            decorations: list[TextDecoration] = []
            sender = event.provenance.sender_name if event.provenance is not None else None
            for rule in rules:
                if event.kind not in rule.kinds:
                    continue
                if rule.worlds is not None and event.world.casefold() not in rule.worlds:
                    continue
                if sender is not None and sender.casefold() != rule.speaker.casefold():
                    continue
                span = _speaker_span(event, text, rule.speaker)
                if span is None:
                    continue
                decorations.append(rule.decoration(event, *span))
                break
            return tuple(decorations)

        registrar.register_display_decorator("speaker-effects", decorate)


plugin = SpeakerEffectsPlugin()

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import pytest
from tfr.core import CommandBus, EventBus
from tfr.events import Direction, Event, EventKind, Provenance
from tfr.plugins import PluginManager
from tfr.text_effects import TextEffectKind


@dataclass
class FakeEntryPoint:
    name: str
    plugin: object

    def load(self) -> object:
        return self.plugin


def speech(
    text: str,
    *,
    kind: EventKind = EventKind.SAY,
    sender: str | None = None,
    event_id: UUID | None = None,
) -> Event:
    values: dict[str, Any] = {}
    if event_id is not None:
        values["event_id"] = event_id
    return Event(
        session_id=UUID(int=1),
        world="alpha",
        connection_generation=1,
        sequence=1,
        direction=Direction.INBOUND,
        kind=kind,
        canonical_text=text,
        plain_text=text,
        display_text=text,
        provenance=Provenance(sender_name=sender) if sender is not None else None,
        **values,
    )


async def manager() -> PluginManager:
    from tfr_plugins_public.speaker_effects import plugin

    return await PluginManager.load(
        enabled=("speaker_effects",),
        config={
            "speaker_effects": {
                "rules": [
                    {
                        "speaker": "Alice",
                        "effect": "shimmer",
                        "color": "#d70000",
                        "accent_color": "#ffffff",
                        "period_seconds": 1.4,
                        "kinds": ["say", "pose"],
                    },
                    {
                        "speaker": "carol",
                        "effect": "capitalization_roll",
                        "color": "#a9914a",
                        "accent_color": "#e6c965",
                        "step_seconds": 0.5,
                        "kinds": ["say", "pose"],
                    },
                ]
            }
        },
        event_bus=EventBus(),
        command_bus=CommandBus(),
        targets={},
        discovered=(FakeEntryPoint("speaker_effects", plugin),),
        scope="ui",
    )


async def test_rules_match_attributed_speakers_case_insensitively() -> None:
    plugins = await manager()
    alice = speech("\x1b[1mALICE\x1b[0m says, hello", sender="alice")
    carol = speech("Carol waves.", kind=EventKind.POSE, sender="CAROL")

    alice_decorations = plugins.decorate_display(alice, alice.display_text or "")
    carol_decorations = plugins.decorate_display(carol, carol.display_text or "")

    assert alice_decorations[0].effect is TextEffectKind.SHIMMER
    assert (alice_decorations[0].start, alice_decorations[0].end) == (0, 5)
    assert carol_decorations[0].effect is TextEffectKind.CAPITALIZATION_ROLL


async def test_rules_do_not_match_mentions_or_misattributed_names() -> None:
    plugins = await manager()

    assert (
        plugins.decorate_display(
            speech("Someone says, Alice is here", sender="Someone"),
            "Someone says, Alice is here",
        )
        == ()
    )
    assert (
        plugins.decorate_display(
            speech("Alice says, hello", sender="Someone"),
            "Alice says, hello",
        )
        == ()
    )
    assert (
        plugins.decorate_display(
            speech("Someone says, Alice is here"),
            "Someone says, Alice is here",
        )
        == ()
    )


async def test_rules_find_name_after_visible_nospoof_prefix() -> None:
    plugins = await manager()
    event = speech("[#12] Alice says, hello", sender="Alice")

    decoration = plugins.decorate_display(event, event.display_text or "")[0]

    assert (decoration.start, decoration.end) == (6, 11)


async def test_rule_offsets_ignore_unsupported_cursor_controls() -> None:
    plugins = await manager()
    event = speech("\x1b[3CAlice says, hello", sender="Alice")

    decoration = plugins.decorate_display(event, event.display_text or "")[0]

    assert (decoration.start, decoration.end) == (0, 5)


async def test_rules_default_to_a_ten_second_repeat_cycle() -> None:
    plugins = await manager()
    first = speech("Alice says, one", sender="Alice", event_id=UUID(int=1))
    second = speech("Alice says, two", sender="Alice", event_id=UUID(int=2))

    first_decoration = plugins.decorate_display(first, first.display_text or "")[0]
    second_decoration = plugins.decorate_display(second, second.display_text or "")[0]

    assert first_decoration.repeat_seconds == 10
    assert second_decoration.repeat_seconds == 10


@pytest.mark.parametrize(
    "effect", [effect for effect in TextEffectKind if effect is not TextEffectKind.TERMINAL_REVEAL]
)
def test_every_effect_type_has_a_valid_rule_configuration(effect: TextEffectKind) -> None:
    from tfr_plugins_public.speaker_effects import _parse_rule

    value: dict[str, object] = {
        "speaker": "Example",
        "effect": effect.value,
    }
    if effect is TextEffectKind.AGE_DECAY:
        value["end_color"] = "#6f7782"
    else:
        value["color"] = "#6f7782"

    rule = _parse_rule(value)

    assert rule.effect is effect
    assert rule.color == "#6f7782"
    assert rule.accent_color != rule.color
    assert rule.loop is (effect is not TextEffectKind.AGE_DECAY)


def test_age_decay_can_loop_only_when_repeat_exceeds_decay_duration() -> None:
    from tfr_plugins_public.speaker_effects import _parse_rule

    with pytest.raises(ValueError, match="repeat_seconds must exceed"):
        _parse_rule(
            {
                "speaker": "Example",
                "effect": "age_decay",
                "end_color": "#6f7782",
                "duration_seconds": 30,
                "loop": True,
                "repeat_seconds": 10,
            }
        )


def test_age_decay_rejects_an_explicit_start_color() -> None:
    from tfr_plugins_public.speaker_effects import _parse_rule

    with pytest.raises(ValueError, match="accent_color is not supported"):
        _parse_rule(
            {
                "speaker": "Example",
                "effect": "age_decay",
                "end_color": "#6f7782",
                "accent_color": "#ffffff",
            }
        )


@pytest.mark.parametrize(
    ("effect", "extra", "message"),
    [
        ("age_decay", {"repeat_seconds": 10}, "repeat_seconds is supported only"),
        (
            "capitalization_roll",
            {"frames_per_second": 20},
            "frames_per_second is not used",
        ),
    ],
)
def test_rules_reject_timing_options_that_cannot_affect_the_effect(
    effect: str,
    extra: dict[str, object],
    message: str,
) -> None:
    from tfr_plugins_public.speaker_effects import _parse_rule

    value: dict[str, object] = {
        "speaker": "Example",
        "effect": effect,
        "color" if effect != "age_decay" else "end_color": "#6f7782",
        **extra,
    }

    with pytest.raises(ValueError, match=message):
        _parse_rule(value)


async def test_first_matching_rule_wins() -> None:
    from tfr_plugins_public.speaker_effects import plugin

    plugins = await PluginManager.load(
        enabled=("speaker_effects",),
        config={
            "speaker_effects": {
                "rules": [
                    {
                        "speaker": "Alice",
                        "effect": "shimmer",
                        "color": "#d70000",
                        "accent_color": "#ffffff",
                    },
                    {
                        "speaker": "alice",
                        "effect": "color_pulse",
                        "color": "#0000ff",
                        "accent_color": "#ffffff",
                    },
                ]
            }
        },
        event_bus=EventBus(),
        command_bus=CommandBus(),
        targets={},
        discovered=(FakeEntryPoint("speaker_effects", plugin),),
        scope="ui",
    )
    event = speech("Alice says, hello", sender="Alice")

    decorations = plugins.decorate_display(event, event.display_text or "")

    assert len(decorations) == 1
    assert decorations[0].effect is TextEffectKind.SHIMMER

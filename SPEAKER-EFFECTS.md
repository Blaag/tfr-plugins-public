# Speaker Effects Reference

This document describes every effect the `speaker_effects` plugin supports:
what each one looks like, which rule fields it accepts, and what those fields
default to. See the [README](README.md#configuration) for how `rules` fits
into the overall `speaker_effects` configuration.

## How rules work

`speaker_effects` decorates only the attributed speaker-name span of `SAY`
and `POSE` events — not mentions of that name elsewhere in a line, and not
lines misattributed to a different sender. When a server adapter attributes the
sender but cannot distinguish a pose and reports `RAW_OUTPUT` or ambiguous
`SPEECH`, a rule that includes `pose` may infer it from the matching speaker
name at the start of the line. Unattributed and say-shaped output is not inferred
as a pose. Matching is case-insensitive.

Each rule is an object with at least `speaker` and `effect`. Rules are
checked in order; the first rule whose `speaker` (and optional `worlds`,
`kinds`) matches an event wins, and only one decoration is ever applied per
event. Fields common to every effect:

| Field | Default | Meaning |
| --- | --- | --- |
| `speaker` | *(required)* | Case-insensitive name to match against the event's attributed sender. |
| `effect` | *(required)* | One of the effect names below. |
| `kinds` | `["say", "pose"]` | Restricts which event kinds this rule matches. |
| `worlds` | all worlds | Restricts this rule to specific world names, case-insensitive. |
| `loop` | `true` (`false` for `age_decay`) | Whether the effect repeats. |
| `repeat_seconds` | `10` | Seconds between the start of each repeat when `loop` is `true`; must exceed the effect's own burst duration. Rejected when `loop` is `false`. |
| `frames_per_second` | `20` | Animation update rate; must not exceed `30`. Not used by `capitalization_roll` or `case_wave` (they advance on `step_seconds` instead). |

Colors (`color`, `end_color`, `accent_color`) are 6-digit hex strings and are
interpolated in OKLab, which tends to keep intermediate colors looking more
natural than direct RGB interpolation. Unless noted otherwise, effects use
`color` as their base/resting color and interpolate toward `accent_color`,
which defaults to an automatically brightened version of `color` if you don't
set it explicitly. Only the effects listed under "Uses `accent_color`" below
accept that field at all; setting it on any other effect is rejected, since
that effect never uses a second color.

Enabling `speaker_effects` with no configuration (`{}`) or an empty `rules`
list loads successfully and decorates nothing — it's a safe no-op default.

## Effects

### `shimmer`

A bright band sweeps back and forth across the name, brightest at its center
and fading outward, continuously looping by default.

- `color` (required), `accent_color` (optional, auto-derived)
- `period_seconds` (default `1.4`) — duration of one sweep pass
- `shimmer_width` (default `1.5`) — width of the bright band, in characters

### `capitalization_roll`

A single character position rolls across the name; the character at that
position is uppercased and colored with `accent_color`, while the rest of
the name is lowercased in `color`.

- `color` (required), `accent_color` (optional, auto-derived)
- `step_seconds` (default `0.5`) — time each character position is "active"
  before the roll advances to the next one

### `comet`

A bright head with a fading trail sweeps once across the name (left to
right), like the `shimmer` effect but directional and trailing instead of
symmetric.

- `color` (required), `accent_color` (optional, auto-derived)
- `duration_seconds` (default `1.2`) — time for one pass across the name
- `trail_width` (default `3`, integer `1`–`20`) — length of the fading tail

### `sparkle`

A small number of character positions flash between `color` and
`accent_color` at a steady rate, with a different random-but-stable set of
positions selected each burst.

- `color` (required), `accent_color` (optional, auto-derived)
- `duration_seconds` (default `1.2`)
- `sparkle_count` (default `2`, integer `1`–`10`) — how many positions flash
  at once

### `underline_sweep`

An underline attribute sweeps once across the name in `color`, matching the
`comet` timing shape but toggling the underline attribute instead of
changing the foreground color.

- `color` (required); does not accept `accent_color`
- `duration_seconds` (default `1.0`)
- `wave_width` (default `2`, integer `1`–`20`) — width of the underlined band

### `bold_sweep`

Identical timing to `underline_sweep`, but toggles bold instead of underline.

- `color` (required); does not accept `accent_color`
- `duration_seconds` (default `1.0`)
- `wave_width` (default `2`, integer `1`–`20`)

### `reverse_sweep`

Identical timing to `underline_sweep`, but toggles reverse video instead of
underline.

- `color` (required); does not accept `accent_color`
- `duration_seconds` (default `1.0`)
- `wave_width` (default `2`, integer `1`–`20`)

### `ember`

A one-shot wave of fire colors (`#ffff5f` → `#ffaf00` → `#ff5f00` → `#d70000`
→ `color`) travels across the name from right to left, like glowing embers
cooling as the burst passes.

- `color` (required); does not accept `accent_color`
- `duration_seconds` (default `1.8`)

### `frost`

The name "frosts over" from `color` to `accent_color` and back, spreading
outward from both ends toward the center and then receding, over one burst.

- `color` (required), `accent_color` (optional, default `#d7ffff` — a pale
  icy blue rather than an auto-derived brightening of `color`)
- `duration_seconds` (default `1.6`)
- `wave_width` (default `2`, integer `1`–`20`) — width of the frosted edge

### `rainbow_wave`

A continuous rainbow gradient sweeps across the name, cycling through hues
over each burst.

- `color` (required); does not accept `accent_color` (the rainbow hues are
  computed independently of `color`, which is used only as the effect's
  resting/fallback color between bursts)
- `duration_seconds` (default `1.8`)

### `color_pulse`

The whole name pulses from `color` to `accent_color` and back once per
burst, following a smooth sine curve.

- `color` (required), `accent_color` (optional, auto-derived)
- `duration_seconds` (default `1.2`)

### `case_wave`

A band of characters is uppercased in `accent_color` while it passes over
them; the rest of the name stays lowercased in `color`. Similar to
`capitalization_roll`, but the active band has width instead of being a
single character.

- `color` (required), `accent_color` (optional, auto-derived)
- `step_seconds` (default `0.2`)
- `wave_width` (default `2`, integer `1`–`20`) — width of the uppercased band

### `age_decay`

A one-shot, non-looping transition from an automatically derived bright
starting color down to `end_color`, meant to convey a name "settling" or
"cooling off" after first appearing. This is the only effect where `loop`
defaults to `false`.

- `end_color` (required) — use `end_color`, not `color`, for this effect
- Does not accept `accent_color` (the bright starting color is always
  derived automatically from `end_color`)
- `duration_seconds` (default `30`)
- Can still loop if you explicitly set `loop: true`, but only if
  `repeat_seconds` exceeds `duration_seconds`

## Uses `accent_color`

`shimmer`, `capitalization_roll`, `comet`, `sparkle`, `frost`, `color_pulse`,
and `case_wave` accept `accent_color`. All other effects reject it if set
explicitly, because they don't use a second color.

## Example

```jsonc
"plugins": {
  "enabled": ["speaker_effects"],
  "config": {
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
          "speaker": "Bob",
          "effect": "age_decay",
          "end_color": "#a9914a",
          "duration_seconds": 30,
          "loop": false,
        },
      ],
    },
  },
}
```

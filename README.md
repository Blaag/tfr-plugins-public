# TFR Public Plugins

Public, optional plugins for TFR. This distribution currently provides:

- `cat`: send a UTF-8 file as paced `@emit` lines.
- `border_reflection`: periodically reflect a highlight around UI borders.
- `film_burn`: open irregular projector-burn holes through visible output.
- `flame`: burn visible output into drifting smoke when clearing the screen.
- `marching_ants`: animate alternating cells around UI borders.
- `speaker_effects`: apply configurable effects to attributed speaker names.
- `terminal_reveal`: reveal incoming lines through a glitching serial-terminal edge.
- `vortex`: pull visible output into an expanding, center-out whirlpool.
- `water`: turn visible characters into falling, sloshing, draining droplets.

Plugins are trusted Python code and run with TFR's process privileges.

The simplest way to use this collection is to add it to `plugins.sources` in
your TFR `config.jsonc` so TFR clones it directly:

```jsonc
"plugins": {
  "enabled": ["cat", "border_reflection", "film_burn"],
  "sources": [
    { "repo": "blaag/tfr-plugins-public" },
  ],
}
```

See the TFR README's "Installing Plugins From a GitHub Repository" section for
`ref`/`auto_update`/`path` options and the trust model. Alternatively, install
this distribution as an ordinary package in the same environment as a
compatible TFR installation and enable entry-point names under
`plugins.enabled`; TFR discovers plugins from their `tfr.plugins.v1` package
entry points either way.

This project is distributed under the [MIT License](LICENSE).

## Development Installation

To work on this repository itself (rather than just using it), install it
beside a local TFR checkout through a private runtime project or an editable
environment; see `[tool.uv.sources]` in `pyproject.toml`.

## Configuration

Choose how Ctrl-L selects among enabled screen-clear plugins in the main TFR UI
configuration:

```jsonc
"ui": {
  "screen_clear": {
    "mode": "cycle", // cycle, random, or locked
    // "effect": "flame", // required only for locked mode
  },
}
```

Enable any installed entry-point names in the main TFR configuration:

```jsonc
"plugins": {
  "enabled": ["cat", "border_reflection", "film_burn", "flame", "marching_ants", "speaker_effects", "terminal_reveal", "vortex", "water"],
  "config": {
    "cat": {},
    "border_reflection": {
      "duration_seconds": 1.2,
      "frames_per_second": 24,
      "gradient_cells": 8,
      "minimum_interval_seconds": 30,
      "maximum_interval_seconds": 120,
    },
    "flame": {
      "duration_seconds": 2.1,
      "frames_per_second": 24,
    },
    "film_burn": {
      "minimum_holes": 3,
      "maximum_holes": 7,
      "maximum_appearance_delay_seconds": 3,
      "minimum_growth_duration_seconds": 3.5,
      "maximum_growth_duration_seconds": 6,
      "burn_duration_seconds": 0.7,
      "frames_per_second": 24,
    },
    "speaker_effects": {
      "rules": [
        {
          "speaker": "Example Name",
          "effect": "shimmer",
          "color": "#d70000",
          "accent_color": "#ffffff",
          "period_seconds": 1.4,
          "repeat_seconds": 10,
          "loop": true,
          "kinds": ["say", "pose"],
        },
      ],
    },
    "terminal_reveal": {
      "baud_rate": 9600,
      "frames_per_second": 30,
      "glitch_width": 3,
      "settle_width": 3,
      "speed_variation": 0.25,
      "inline_glitch_chance": 0.05,
      "glitch_characters": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~",
      "glitch_color": "#ffffff",
      "trail_color": "#d7d7d7",
      "maximum_characters": 4096,
      "maximum_duration_seconds": 10,
    },
    "vortex": {
      "direction": "clockwise",
      "duration_seconds": 2.8,
      "edge_softness": 0.18,
      "frames_per_second": 24,
      "turns": 2.25,
    },
    "water": {
      "color_mode": "dynamic",
      "drain_rate": 60,
      "duration_seconds": 10,
      "floor_restitution": 0.75,
      "frames_per_second": 24,
      "gravity": 9,
      "pressure": 18,
      "slosh_strength": 0.85,
      "smoothing_radius": 1.45,
      "surface_tension": 1.4,
      "viscosity": 2.2,
    },
  },
}
```

## Plugin Notes

`cat` sends a UTF-8 text file to an active bare, TinyMUX, or TinyMUSH world with
`/cat PATH`. It preserves spaces and tabs, applies server-specific softcode
escaping, preflights the complete file, sends the first line immediately, and
paces later lines.

`marching_ants` animates alternating cells clockwise around both UI borders.
Configure `frames_per_second` to a value greater than zero and at most 30.

`border_reflection` runs a synchronized reflection over both visible pane
borders. Its configurable values are `duration_seconds`, `frames_per_second`,
`gradient_cells`, `minimum_interval_seconds`, and `maximum_interval_seconds`.

`film_burn` opens several seeded, irregular holes through the visible output.
One hole ignites immediately; the remaining holes appear randomly before the
configured delay. Burn fronts continue expanding independently while every
character they touch progresses from burnt orange through deep red, brown, and
black before disappearing. Overlapping holes use the earliest ignition time.
Characters retain their original style until ignition, and non-foreground style
attributes remain active while burning.

| Option | Default | Valid values | Meaning |
| --- | ---: | --- | --- |
| `minimum_holes` | `3` | Integer from `1` to `32` | Inclusive lower bound for the seeded hole count. |
| `maximum_holes` | `7` | Integer from `minimum_holes` to `32` | Inclusive upper bound for the seeded hole count. |
| `maximum_appearance_delay_seconds` | `3` | `0` through `30` | Latest time a hole may ignite; the first always starts at zero. |
| `minimum_growth_duration_seconds` | `3.5` | Positive; at least the appearance delay | Fastest time for a hole to expand across the pane. |
| `maximum_growth_duration_seconds` | `6` | At least the minimum; no greater than `60` | Slowest time for a hole to expand across the pane. |
| `burn_duration_seconds` | `0.7` | Greater than `0`; no greater than `10` | Time each character spends traversing all four burn colors. |
| `frames_per_second` | `24` | `1` through `30` | Requested display update rate. |

The minimum growth duration plus burn duration cannot exceed 60 seconds.
Keeping the minimum growth duration at least as long as the appearance delay
ensures every hole ignites before the fastest one could finish crossing the pane.

`flame` replaces the normal screen-clear transition with a deterministic
fire, smoke, and ash animation of the visible output. `duration_seconds` must be
a positive number no greater than 10. `frames_per_second` must be positive and
no greater than 30. Both fields are optional, and unknown configuration fields
are rejected.

`vortex` starts at the center and expands outward, pulling each character
gradually into a tightening circular orbit until it disappears into the center.
The softened leading edge avoids a rigid boundary between still and moving text,
and characters retain their visible colors throughout the transition. Terminal
cell proportions are included in the orbit geometry, so characters in rectangular
panes can leave the visible area and rotate back through it. Set `direction` to
`clockwise` or `counterclockwise`; `turns` must be positive and no greater than 6.
`edge_softness` controls how gradually characters become entrained and must be a
positive number no greater than `0.5`. Increase `duration_seconds` to slow the
entire transition; it can be any positive number up to 60. `frames_per_second`
must be positive and no greater than 30.

`water` treats every non-whitespace character as a continuous Smoothed Particle
Hydrodynamics (SPH) particle. A spatial hash bounds neighbor searches; local
density drives pressure, viscosity transfers momentum, surface tension keeps the
fluid cohesive, and gravity pulls it toward the bottom. The terminal grid is only
the final projection of the continuous simulation. Configure those forces with
`pressure`, `viscosity`, `surface_tension`, `gravity`, and `smoothing_radius`.
`slosh_strength` ranges from `0` to `1` and adds container-scale acceleration from
the changing center of mass. Bottom, left, and right outlets share the drain
budget evenly, independent of slosh direction. `drain_rate` sets the baseline
characters per second; dense snapshots raise that rate as needed to keep the
effect within its bounded completion window. If particles remain at
`duration_seconds`, they accelerate toward their assigned outlets and the
transition continues until they finish draining. The effect preserves each
character and its visible style when `color_mode` is `source`, which is the
default. Set `color_mode` to `dynamic` to color slow particles deep blue, shift
fast particles toward cyan, and brighten pressurized particles toward white.
`floor_restitution` controls impact rebound from `0` through `1`; the default is
`0.22`, while values around `0.7` produce visible splashes. Other source style
attributes remain active in dynamic mode. `frames_per_second` must be between 1
and 30.

`speaker_effects` decorates only the attributed speaker-name span of `SAY` and
`POSE` events. Matching is case-insensitive. Rules can be restricted with
`worlds` and `kinds`, use first-match precedence, and support looping or one-shot
timing. The original event, logs, retained text, wrapping geometry, and copied
text remain unchanged.

Available speaker effects are:

- `shimmer`
- `capitalization_roll`
- `comet`
- `sparkle`
- `underline_sweep`
- `bold_sweep`
- `ember`
- `frost`
- `rainbow_wave`
- `color_pulse`
- `case_wave`
- `reverse_sweep`
- `age_decay`

`shimmer` uses `period_seconds`; capitalization effects use `step_seconds`; the
other effects use `duration_seconds`. `comet` accepts `trail_width`, `sparkle`
accepts `sparkle_count`, and sweep, frost, and case-wave effects accept
`wave_width`. Colors are interpolated in OKLab. `age_decay` derives a bright
starting color and finishes at the exact configured `end_color`.

`terminal_reveal` draws each incoming line progressively while a deterministic
band of replacement glyphs flickers at the leading edge. It uses 20 baud units
per rendered character, intentionally half the speed of raw ten-bit serial
framing; 300 baud therefore displays about 15 characters per second. Rendering
is capped by `frames_per_second`, which must not exceed 30. Each line gets a
stable deterministic speed adjustment within `speed_variation`; the default
`0.25` varies effective line speed from 75% to 125% of the configured baud rate.

Use `glitch_width`, `glitch_characters`, and `glitch_color` to control the edge.
The three newest cells glitch in white by default; `settle_width` controls the
cells behind them that settle from white toward their existing ANSI or speaker
color. `trail_color` supplies the temporary fade target for text that uses the
terminal's unspecified default foreground. The default glitch set contains all
ASCII letters, digits, and punctuation characters available from a standard
keyboard; whitespace and control characters remain prohibited.
While a line is filling, `inline_glitch_chance` selects character positions for
one additional in-place glitch and fade pulse. Selection and timing are stable
for replay, and no inline pulses occur after the line has filled. The default
chance is `0.05`; use `0` to disable inline glitches.
Optional `worlds` and `kinds` lists restrict which incoming events are affected.
Lines longer than `maximum_characters` are shown immediately, and long eligible
lines accelerate as needed to finish within `maximum_duration_seconds`; their
hard limits are 16,384 characters and 30 seconds. Intermediate reveal state is
quantized to the configured frame rate even when unrelated UI activity causes
extra redraws; final completion still occurs at the calculated duration.
The complete original line is retained immediately for logs, wrapping,
scrollback, selection, and copying. Existing ANSI and speaker decorations remain
intact behind the reveal, and disabling animations shows the complete line
immediately.

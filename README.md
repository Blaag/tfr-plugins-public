# TFR Public Plugins

Public, optional plugins for TFR. This distribution currently provides:

- `acid_rain`: dissolve visible output under falling corrosive streaks.
- `cat`: send a UTF-8 file as paced `@emit` lines.
- `border_reflection`: periodically reflect a highlight around UI borders.
- `doom_fire`: consume visible output with a bottom-fed cellular fire simulation.
- `film_burn`: open irregular projector-burn holes through visible output.
- `flame`: burn visible output into drifting smoke when clearing the screen.
- `gag`: hide inbound lines matching world-local regular expressions.
- `sandstorm`: break visible output into wind-driven earth-tone particles.
- `speaker_effects`: apply configurable effects to attributed speaker names.
  See [SPEAKER-EFFECTS.md](SPEAKER-EFFECTS.md) for every effect, what it
  looks like, and its parameters.
- `terminal_reveal`: reveal incoming lines through a glitching serial-terminal edge.
- `vortex`: pull visible output into an expanding, center-out whirlpool.
- `water`: turn visible characters into falling, sloshing, draining droplets.
- `water_ripple`: dissolve visible output in expanding density-glyph rings.

## Boss Views

This collection does not currently provide any boss views. Core TFR bundles the
`tfr.boss` plugin, which supplies the `/boss` command and the dependable
`build-dashboard` fallback view. It is always available and should not be added
to `plugins.enabled`.

Optional and experimental boss views may be added to this collection in the
future. They complement the bundled fallback and use the same public boss-view
plugin API. See TFR's [Boss Views reference](https://github.com/Blaag/tfr/blob/main/BOSS-VIEWS.md)
for view selection, configuration, registration, render context, operational
events, and safety limits.

Plugins are trusted Python code and run with TFR's process privileges.

## Stable Releases

Stable releases use immutable annotated semantic-version tags and include a
strict `plugin-manifest.json`. The manifest binds the release version to its
exact Git commit, wheel digest, exported plugin names, supported TFR versions,
and plugin API range. Compatible TFR versions can consume this channel with a
`stable-auto` or `stable-notify` source policy; `pinned` sources select an exact
40-character commit. Stable policies never fall back to the mutable `main`
branch. See [SECURITY.md](SECURITY.md) for the trust boundary and
[MAINTAINER.md](MAINTAINER.md) for the publication process.

The recommended installation uses this repository's immutable stable channel:

```jsonc
"plugins": {
  "enabled": ["cat", "border_reflection", "film_burn"],
  "sources": [
    {
      "repo": "Blaag/tfr-plugins-public",
      "policy": "stable-auto",
      "manifest_url": "https://github.com/Blaag/tfr-plugins-public/releases/latest/download/plugin-manifest.json",
    },
  ],
}
```

See the TFR README's plugin source section for `stable-notify`, exact
commit pins, rollback, and legacy development options. Alternatively, install
this distribution as an ordinary package in the same environment as a
compatible TFR installation and enable entry-point names under
`plugins.enabled`; TFR discovers plugins from their `tfr.plugins.v1` package
entry points either way.

To update a configured `stable-auto` or `stable-notify` source immediately
instead of waiting for the next TFR restart, run this from a repository
checkout:

```sh
./scripts/install-from-checkout
```

The installer uses the active managed TFR interpreter, reads the normal TFR
configuration, verifies the live stable manifest and annotated release tag,
and activates the exact release in `plugins.state_directory`. Restart TFR to
load it. If TFR uses a non-default managed root, set `TFR_MANAGED_ROOT`; for a
non-managed installation, set `TFR_PYTHON` to a virtual-environment or system
Python that can import TFR in isolated mode. Use `--config PATH` for a
non-default TFR configuration. The manual updater intentionally accepts only
the official public-plugin repository and stable manifest.

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
  "enabled": [
    "acid_rain",
    "cat",
    "border_reflection",
    "doom_fire",
    "film_burn",
    "flame",
    "gag",
    "sandstorm",
    "speaker_effects",
    "terminal_reveal",
    "vortex",
    "water",
    "water_ripple",
  ],
  "config": {
    "acid_rain": {
      "density": 0.32,
      "duration_seconds": 3,
      "frames_per_second": 24,
      "streak_length": 4,
    },
    "cat": {},
    "border_reflection": {
      "duration_seconds": 1.2,
      "frames_per_second": 24,
      "gradient_cells": 8,
      "minimum_interval_seconds": 30,
      "maximum_interval_seconds": 120,
    },
    "doom_fire": {
      "duration_seconds": 3.2,
      "frames_per_second": 24,
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
    "gag": {
      "worlds": {
        "example-world": [
          "^A noisy line$",
          "repeated message \\d+",
        ],
      },
    },
    "sandstorm": {
      "direction": "left-to-right",
      "duration_seconds": 2.8,
      "frames_per_second": 24,
      "gust_strength": 1.4,
    },
    "speaker_effects": {
      // Enabling with no rules (or omitting config entirely) is a safe
      // no-op: it loads successfully and decorates nothing. See
      // SPEAKER-EFFECTS.md for the full effect list and their parameters.
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
      "baud_rate": 1200,
      "frames_per_second": 30,
      "glitch_width": 3,
      "settle_width": 3,
      "speed_variation": 0.25,
      "inline_glitch_chance": 0.35,
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
      "color_mode": "source",
      "drain_rate": 45,
      "duration_seconds": 5,
      "floor_restitution": 0.75,
      "frames_per_second": 30,
      "gravity": 12,
      "pressure": 48,
      "slosh_strength": 1.0,
      "smoothing_radius": 1.4,
      "surface_tension": 0.5,
      "viscosity": 0.6,
    },
    "water_ripple": {
      "duration_seconds": 2.6,
      "frames_per_second": 24,
    },
  },
}
```

## Plugin Notes

`cat` sends a UTF-8 text file to an active bare, TinyMUX, or TinyMUSH world with
`/cat PATH`. It preserves spaces and tabs, applies server-specific softcode
escaping, preflights the complete file, sends the first line immediately, and
paces later lines.

`gag` suppresses matching inbound lines from the active world's display while
leaving their canonical events available to logging and replay. Expressions are
persistent configuration under `plugins.config.gag.worlds`, keyed by exact world
alias. Use `/gag` or `/gag list` to display the active world's configured
expressions. Each world may have up to 100 expressions of 1,000 characters each.
Matching has a 10-millisecond per-line budget and fails open if that budget is
exhausted, so an expensive expression cannot stall inbound display processing.

`border_reflection` runs a synchronized reflection over both visible pane
borders. Its configurable values are `duration_seconds`, `frames_per_second`,
`gradient_cells`, `minimum_interval_seconds`, and `maximum_interval_seconds`.

`acid_rain` sends seeded neon-green streaks down empty regions while a staggered
contact front corrodes text from top to bottom. Touched characters pass through
bright acid, olive decay, brown residue, and disappearance stages. `density`
ranges from `0` to `1` and controls how many visible rain columns are active;
`streak_length` is an integer from `1` through `12`. `duration_seconds` must be
positive and no greater than 60, and `frames_per_second` must be between 1 and 30.

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

`doom_fire` is a separate bottom-fed cellular simulation inspired by the classic
fire effect. A seeded heat row flickers below the pane, intensity propagates
upward with lateral variation and cooling, and touched cells stay consumed after
the flame has moved on. Its glyph and color ramp runs from dark-red embers through
orange and gold to a white-hot peak. `duration_seconds` must be positive and no
greater than 60; `frames_per_second` must be between 1 and 30.

`sandstorm` advances a softened wind front across the pane, breaks non-whitespace
characters into seeded dust particles, and drives them offscreen with turbulent
vertical drift. Source styles remain intact until each character is entrained.
Set `direction` to `left-to-right` or `right-to-left`; `gust_strength` ranges
from `0` for straight-line travel through `4` for strong turbulence.
`duration_seconds` must be positive and no greater than 60, and
`frames_per_second` must be between 1 and 30.

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
effect within its bounded completion window. `duration_seconds` (default `5`)
is a target, not a hard cutoff: once it elapses, remaining particles accelerate
toward their assigned outlets, and the transition continues rendering until
every particle has actually drained. The effect preserves each character and
its visible style when `color_mode` is `source`, which is the default. Set
`color_mode` to `dynamic` to color slow particles deep blue, shift fast
particles toward cyan, and brighten pressurized particles toward white.
`floor_restitution` controls impact rebound from `0` through `1`; the default is
`0.75`, which produces a visible splash, while values near `0` barely rebound at
all. Other source style attributes remain active in dynamic mode.
`frames_per_second` must be between 1 and 30.

`water_ripple` begins at the pane center and expands outward using terminal-cell
aspect-corrected distance. Each contacted character flashes at the wavefront,
then steps through solid, dark, medium, and light density glyphs before
disappearing. This is a geometric dissolution rather than the falling SPH fluid
simulation provided by `water`. `duration_seconds` must be positive and no
greater than 60, and `frames_per_second` must be between 1 and 30.

`speaker_effects` decorates only the attributed speaker-name span of `SAY` and
`POSE` events, including attributed `RAW_OUTPUT` or ambiguous `SPEECH` that a
pose-enabled rule can safely identify as a pose. Matching is case-insensitive.
Rules can be restricted with `worlds` and `kinds`, use first-match precedence,
and support looping or one-shot timing. The original event, logs, retained text,
wrapping geometry, and copied text remain unchanged. Enabling this plugin with
no `rules` configured (or no `speaker_effects` configuration at all) loads
successfully and decorates nothing, so it is safe to include in a default
enabled list.

See [SPEAKER-EFFECTS.md](SPEAKER-EFFECTS.md) for every available effect, what
it looks like, and the parameters it accepts.

`terminal_reveal` draws each incoming line progressively while a deterministic
band of replacement glyphs flickers at the leading edge. It uses 20 baud units
per rendered character, intentionally half the speed of raw ten-bit serial
framing; 300 baud therefore displays about 15 characters per second, and the
default is 1200 baud. Rendering is capped by `frames_per_second`, which must not
exceed 30. Each line gets a stable deterministic speed adjustment within
`speed_variation`; the default `0.25` varies effective line speed from 75% to
125% of the configured baud rate.

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
chance is `0.35`; use `0` to disable inline glitches.
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

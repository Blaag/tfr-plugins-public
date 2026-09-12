from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Any

import pytest
from prompt_toolkit.formatted_text import fragment_list_to_text
from tfr.plugin_api import PluginRegistrationError, ScreenClearContext, terminal_cell_width

from tfr_plugins_public.water import (
    _advance_sph,
    _densities,
    _drain_particles,
    _dynamic_water_style,
    _graphemes,
    _Particle,
    _render_particles,
    _spatial_hash,
    _styled_graphemes,
    _WaterRenderer,
    _WaterState,
    plugin,
    render_water,
)


@dataclass
class RegisteredEffect:
    handler: Any
    duration_seconds: float
    frames_per_second: float
    is_complete: Any = None


class RecordingRegistrar:
    def __init__(self) -> None:
        self.effects: list[RegisteredEffect] = []

    def register_screen_clear_effect(
        self,
        handler: Any,
        *,
        duration_seconds: float,
        frames_per_second: float,
        is_complete: Any = None,
    ) -> None:
        self.effects.append(
            RegisteredEffect(handler, duration_seconds, frames_per_second, is_complete)
        )


def context(
    lines: tuple[str, ...],
    width: int,
    progress: float,
    *,
    elapsed_seconds: float | None = None,
) -> ScreenClearContext:
    return ScreenClearContext(
        lines=lines,
        width=width,
        progress=progress,
        seed=11,
        elapsed_seconds=elapsed_seconds,
    )


def particle(
    identifier: int,
    x: float,
    y: float,
    *,
    vx: float = 0,
    vy: float = 0,
    floor_impacts: int = 0,
) -> _Particle:
    return _Particle(
        identifier,
        x,
        y,
        vx,
        vy,
        1,
        chr(65 + identifier),
        "",
        floor_impacts=floor_impacts,
    )


def advance(
    state: _WaterState,
    *,
    height: int = 10,
    width: int = 20,
    gravity: float = 0,
    pressure: float = 0,
    viscosity: float = 0,
    surface_tension: float = 0,
    smoothing_radius: float = 1.45,
    slosh_strength: float = 0,
    floor_restitution: float = 0.22,
) -> None:
    _advance_sph(
        state,
        height=height,
        width=width,
        frames_per_second=24,
        drain_rate=0,
        gravity=gravity,
        pressure=pressure,
        viscosity=viscosity,
        surface_tension=surface_tension,
        smoothing_radius=smoothing_radius,
        slosh_strength=slosh_strength,
        floor_restitution=floor_restitution,
    )


def test_water_starts_with_source_text() -> None:
    lines = ("FIRST", "SECOND")

    initial = fragment_list_to_text(render_water(context(lines, 8, 0)))

    assert initial == "FIRST\nSECOND"


def test_sph_density_increases_with_nearby_particles() -> None:
    particles = [particle(0, 2, 2), particle(1, 2.4, 2), particle(2, 2.8, 2)]
    cells = _spatial_hash(particles, 1.45)

    density = _densities(particles, cells, 1.45)

    assert density[1] > density[0]
    assert density[1] > 2


def test_sph_pressure_separates_a_dense_cluster() -> None:
    particles = [particle(index, 2 + index * 0.15, 3) for index in range(5)]
    state = _WaterState(particles)
    initial_span = particles[-1].x - particles[0].x

    for _ in range(4):
        advance(state, pressure=60)

    assert particles[-1].x - particles[0].x > initial_span
    assert particles[0].vx < 0
    assert particles[-1].vx > 0
    assert all(item.local_pressure > 0 for item in particles[1:-1])


def test_simulated_pressure_drives_rendered_brightness_and_clears() -> None:
    particles = [particle(index, 2 + index * 0.15, 3) for index in range(5)]
    state = _WaterState(particles)

    advance(state, pressure=60)
    compressed_styles = {
        style
        for style, text in _render_particles(
            particles,
            height=10,
            width=20,
            color_mode="dynamic",
        )
        if text.strip()
    }

    assert any(style != "fg:#0c2d56" for style in compressed_styles)

    for index, item in enumerate(particles):
        item.x = 2 + index * 2
        item.vx = 0
        item.vy = 0
    advance(state, pressure=60)
    advance(state, pressure=60)
    for item in particles:
        item.vx = 0
        item.vy = 0

    assert all(item.local_pressure == 0 for item in particles)
    relaxed_styles = {
        style
        for style, text in _render_particles(
            particles,
            height=10,
            width=20,
            color_mode="dynamic",
        )
        if text.strip()
    }
    assert relaxed_styles == {"fg:#0c2d56"}


def test_sph_viscosity_equalizes_neighbor_velocities() -> None:
    particles = [particle(0, 2, 3, vx=3), particle(1, 2.5, 3, vx=-3)]
    state = _WaterState(particles)

    advance(state, viscosity=10)

    assert abs(particles[0].vx - particles[1].vx) < 6


def test_sph_surface_tension_pulls_neighbors_together() -> None:
    particles = [particle(0, 2, 3), particle(1, 3, 3)]
    state = _WaterState(particles)

    advance(state, surface_tension=10)

    assert particles[0].vx > 0
    assert particles[1].vx < 0


def test_sph_internal_forces_conserve_momentum_for_asymmetric_density() -> None:
    particles = [
        particle(0, 2, 3),
        particle(1, 2.2, 3),
        particle(2, 2.4, 3),
        particle(3, 3.3, 3),
    ]
    state = _WaterState(particles)

    advance(state, pressure=50, viscosity=4, surface_tension=3)

    assert sum(item.vx for item in particles) == pytest.approx(0, abs=1e-12)
    assert sum(item.vy for item in particles) == pytest.approx(0, abs=1e-12)


def test_sph_force_clamping_preserves_internal_momentum() -> None:
    particles = [particle(index, 20 + index * 0.01, 20) for index in range(12)]
    state = _WaterState(particles)

    for _ in range(8):
        advance(state, height=50, width=100, pressure=100, viscosity=20, surface_tension=20)

    assert sum(item.vx for item in particles) == pytest.approx(0, abs=1e-10)
    assert sum(item.vy for item in particles) == pytest.approx(0, abs=1e-10)


def test_gravity_moves_particles_continuously() -> None:
    renderer = _WaterRenderer(
        duration_seconds=10,
        frames_per_second=24,
        drain_rate=0.01,
        gravity=9,
        pressure=18,
        viscosity=2.2,
        surface_tension=1.4,
        smoothing_radius=1.45,
        slosh_strength=0,
    )

    for _ in range(3):
        renderer(context(("A", "", "", ""), 5, 0.05, elapsed_seconds=0.5))

    assert renderer._state is not None
    assert renderer._state.particles[0].y > 0.5
    assert renderer._state.particles[0].vy > 0


def test_floor_restitution_controls_splash_height() -> None:
    low_bounce = particle(0, 2, 8.9, vy=5)
    high_bounce = particle(0, 2, 8.9, vy=5)

    advance(_WaterState([low_bounce]), floor_restitution=0.22)
    advance(_WaterState([high_bounce]), floor_restitution=0.75)

    assert low_bounce.vy < 0
    assert high_bounce.vy < low_bounce.vy


def test_floor_restitution_produces_visible_rebound_before_drainage() -> None:
    def rebound_height(floor_restitution: float) -> tuple[float, bool]:
        item = particle(0, 2, 8.9, vy=5)
        state = _WaterState([item], step=100, initial_particle_count=1)
        highest_position = item.y
        for _ in range(90):
            _advance_sph(
                state,
                height=10,
                width=20,
                frames_per_second=30,
                drain_rate=45,
                gravity=12,
                pressure=0,
                viscosity=0,
                surface_tension=0,
                smoothing_radius=1.45,
                slosh_strength=0,
                duration_seconds=7,
                floor_restitution=floor_restitution,
            )
            if not state.particles:
                break
            highest_position = min(highest_position, item.y)
        return highest_position, not state.particles

    low_position, low_drained = rebound_height(0.22)
    high_position, high_drained = rebound_height(0.75)

    assert high_position < low_position - 0.4
    assert low_drained is True
    assert high_drained is True


def test_corner_impact_rebounds_before_side_drainage() -> None:
    item = particle(0, 0.3, 8.9, vx=-10, vy=5)
    state = _WaterState([item], step=100, initial_particle_count=1)

    for _ in range(2):
        _advance_sph(
            state,
            height=10,
            width=20,
            frames_per_second=30,
            drain_rate=45,
            gravity=12,
            pressure=0,
            viscosity=0,
            surface_tension=0,
            smoothing_radius=1.45,
            slosh_strength=0,
            duration_seconds=7,
            floor_restitution=0.75,
        )

    assert state.particles == [item]
    assert item.floor_impacts == 1
    assert item.y < 9


def test_dynamic_color_uses_velocity_and_pressure() -> None:
    slow = particle(0, 2, 2)
    fast = particle(1, 2, 2, vx=10)
    pressurized = particle(2, 2, 2, vx=10)
    slow.style = "bold"
    pressurized.local_pressure = 72

    slow_style = _dynamic_water_style(slow)
    fast_style = _dynamic_water_style(fast)
    pressure_style = _dynamic_water_style(pressurized)

    assert slow_style == "bold fg:#0c2d56"
    assert fast_style == "fg:#20aaff"
    assert pressure_style == "fg:#8dd6ff"


def test_dynamic_color_uses_a_bounded_palette() -> None:
    item = particle(0, 2, 2)
    styles = set()
    for speed in range(101):
        for local_pressure in range(0, 201, 2):
            item.vx = speed / 10
            item.local_pressure = local_pressure
            styles.add(_dynamic_water_style(item))

    assert len(styles) <= 25


def test_dynamic_color_mode_overrides_only_the_foreground() -> None:
    source = ScreenClearContext(
        lines=("AB",),
        width=2,
        progress=0,
        seed=11,
        styled_lines=((("#d70000 ansired red default bold bg:#000000 underline", "AB"),),),
    )

    rendered = render_water(source, color_mode="dynamic")
    visible_styles = {style for style, text in rendered if text.strip()}

    assert visible_styles == {"bold bg:#000000 underline fg:#0c2d56"}


def test_left_right_and_bottom_outlets_share_drain_budget() -> None:
    state = _WaterState(
        [
            particle(0, 0, 1),
            particle(1, 2, 2, floor_impacts=1),
            particle(2, 4, 1),
        ],
        step=100,
    )

    _drain_particles(
        state,
        height=3,
        width=9,
        frames_per_second=1,
        drain_rate=3,
    )

    assert state.particles == []


def test_particles_are_not_removed_before_reaching_an_outlet() -> None:
    state = _WaterState(
        [particle(0, 2, 1)],
        step=100,
        initial_particle_count=1,
    )

    removed = _drain_particles(
        state,
        height=5,
        width=10,
        frames_per_second=1,
        drain_rate=100,
        duration_seconds=1,
    )

    assert removed is False
    assert len(state.particles) == 1


@pytest.mark.parametrize("progress", [0, 0.05, 0.1, 0.2])
def test_water_preserves_styles_and_terminal_width(progress: float) -> None:
    source = ScreenClearContext(
        lines=("界A", "e\u0301x"),
        width=3,
        progress=progress,
        seed=11,
        styled_lines=((("fg:#d70000", "界A"),), (("fg:#5f87af bold", "e\u0301x"),)),
    )

    rendered = render_water(source, drain_rate=0.1)
    lines = fragment_list_to_text(rendered).split("\n")
    visible_styles = {style for style, text in rendered if text.strip()}

    assert len(lines) == 2
    assert all(terminal_cell_width(line) <= 3 for line in lines)
    assert visible_styles
    assert visible_styles <= {"fg:#d70000", "fg:#5f87af bold"}
    if progress == 0:
        assert visible_styles == {"fg:#d70000", "fg:#5f87af bold"}


def test_water_keeps_joined_unicode_sequences_together() -> None:
    source = "\u0301A 🇺🇸👩\u200d💻"

    assert _graphemes(source) == ["\u0301A", " ", "🇺🇸", "👩\u200d💻"]
    styled_source = ScreenClearContext(
        lines=(source,),
        width=10,
        progress=0,
        seed=11,
        styled_lines=((("fg:#d70000", "\u0301A 🇺🇸👩\u200d"), ("fg:#5f87af", "💻")),),
    )

    assert _styled_graphemes(styled_source.styled_lines[0]) == [
        ("fg:#d70000", "\u0301A"),
        ("fg:#d70000", " "),
        ("fg:#d70000", "🇺🇸"),
        ("fg:#d70000", "👩\u200d💻"),
    ]
    assert fragment_list_to_text(render_water(styled_source)) == source


def test_renderer_updates_state_at_display_frame_rate() -> None:
    lines = tuple(
        "".join("X" if (row * 7 + column * 11) % 3 else " " for column in range(20))
        for row in range(8)
    )
    renderer = _WaterRenderer(
        duration_seconds=10,
        frames_per_second=24,
        drain_rate=0.1,
        gravity=9,
        pressure=18,
        viscosity=2.2,
        surface_tension=1.4,
        smoothing_radius=1.45,
        slosh_strength=0.85,
    )
    frames = [
        tuple(
            renderer(
                context(
                    lines,
                    20,
                    frame / 240,
                    elapsed_seconds=frame / 24,
                )
            )
        )
        for frame in range(12)
    ]

    assert sum(left != right for left, right in pairwise(frames)) >= 8


def test_renderer_bounds_missed_frame_catch_up() -> None:
    renderer = _WaterRenderer(
        duration_seconds=10,
        frames_per_second=24,
        drain_rate=1,
        gravity=9,
        pressure=18,
        viscosity=2.2,
        surface_tension=1.4,
        smoothing_radius=1.45,
        slosh_strength=0.85,
    )

    renderer(context(("X" * 20,) * 8, 20, 1, elapsed_seconds=100))

    assert renderer._state is not None
    assert renderer._state.step == 4


def test_renderer_continues_past_duration_until_particles_drain() -> None:
    renderer = _WaterRenderer(
        duration_seconds=1,
        frames_per_second=4,
        drain_rate=1,
        gravity=9,
        pressure=18,
        viscosity=2.2,
        surface_tension=1.4,
        smoothing_radius=1.45,
        slosh_strength=0,
    )
    source = context(("ABCD",), 4, 1)

    at_duration = renderer(source)

    assert fragment_list_to_text(at_duration).strip()
    assert renderer.is_complete() is False

    finished = renderer(context(source.lines, source.width, 1, elapsed_seconds=10))
    for _ in range(10):
        if renderer.is_complete():
            break
        finished = renderer(context(source.lines, source.width, 1, elapsed_seconds=10))

    assert finished == []
    assert renderer.is_complete() is True


def test_renderer_continues_draining_without_elapsed_time() -> None:
    renderer = _WaterRenderer(
        duration_seconds=1,
        frames_per_second=4,
        drain_rate=1,
        gravity=9,
        pressure=18,
        viscosity=2.2,
        surface_tension=1.4,
        smoothing_radius=1.45,
        slosh_strength=0,
    )
    source = context(("ABCD",), 4, 1)

    renderer(source)
    state = renderer._state
    for _ in range(9):
        renderer(source)

    assert renderer.is_complete() is True
    assert renderer._state is state
    assert renderer._state is not None
    assert renderer._state.step > 4


def test_dense_snapshot_with_slow_drain_completes_near_duration() -> None:
    renderer = _WaterRenderer(
        duration_seconds=1,
        frames_per_second=4,
        drain_rate=0.01,
        gravity=0.01,
        pressure=18,
        viscosity=2.2,
        surface_tension=1.4,
        smoothing_radius=1.45,
        slosh_strength=0,
    )
    lines = ("X" * 20,) * 8

    completion_frame = None
    for frame in range(81):
        renderer(context(lines, 20, min(1, frame / 4), elapsed_seconds=frame / 4))
        if renderer.is_complete():
            completion_frame = frame
            break

    assert completion_frame is not None
    assert completion_frame / 4 <= 10


def test_empty_snapshot_is_immediately_complete() -> None:
    renderer = _WaterRenderer(
        duration_seconds=10,
        frames_per_second=24,
        drain_rate=30,
        gravity=9,
        pressure=18,
        viscosity=2.2,
        surface_tension=1.4,
        smoothing_radius=1.45,
        slosh_strength=0.85,
    )

    assert renderer(context((), 20, 0)) == []
    assert renderer.is_complete() is True


def test_plugin_registers_configured_sph_physics() -> None:
    registrar = RecordingRegistrar()

    plugin.register(
        registrar,
        {
            "drain_rate": 20,
            "duration_seconds": 9,
            "color_mode": "dynamic",
            "floor_restitution": 0.7,
            "frames_per_second": 20,
            "gravity": 8,
            "pressure": 24,
            "slosh_strength": 0.7,
            "smoothing_radius": 1.6,
            "surface_tension": 1.8,
            "viscosity": 3,
        },
    )

    assert len(registrar.effects) == 1
    assert registrar.effects[0].duration_seconds == 9
    assert registrar.effects[0].frames_per_second == 20
    assert callable(registrar.effects[0].is_complete)
    assert registrar.effects[0].handler.color_mode == "dynamic"
    assert registrar.effects[0].handler.floor_restitution == 0.7


@pytest.mark.parametrize(
    "config",
    [
        {"duration_seconds": 0},
        {"duration_seconds": 61},
        {"frames_per_second": 0},
        {"frames_per_second": 0.99},
        {"frames_per_second": 31},
        {"drain_rate": 0},
        {"drain_rate": 10_001},
        {"gravity": 0},
        {"gravity": 51},
        {"pressure": 0},
        {"pressure": 101},
        {"viscosity": 0},
        {"viscosity": 21},
        {"surface_tension": 0},
        {"surface_tension": 21},
        {"smoothing_radius": 0.5},
        {"smoothing_radius": 3.1},
        {"slosh_strength": -0.1},
        {"slosh_strength": 1.1},
        {"slosh_strength": True},
        {"color_mode": "rainbow"},
        {"color_mode": []},
        {"floor_restitution": -0.1},
        {"floor_restitution": 1.1},
        {"floor_restitution": True},
        {"gravity": 10**1000},
        {"unknown": True},
    ],
)
def test_invalid_configuration_is_rejected(config: dict[str, object]) -> None:
    registrar = RecordingRegistrar()

    with pytest.raises(PluginRegistrationError):
        plugin.register(registrar, config)

    assert registrar.effects == []

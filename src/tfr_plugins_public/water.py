from __future__ import annotations

import math
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from tfr.plugin_api import (
    MAX_SCREEN_CLEAR_DURATION_SECONDS,
    PLUGIN_API_VERSION,
    PluginRegistrar,
    PluginRegistrationError,
    ScreenClearContext,
    terminal_cell_width,
)

_FIELDS = frozenset(
    {
        "color_mode",
        "drain_rate",
        "duration_seconds",
        "floor_restitution",
        "frames_per_second",
        "gravity",
        "pressure",
        "slosh_strength",
        "smoothing_radius",
        "surface_tension",
        "viscosity",
    }
)
_CELL_ASPECT = 0.5
_REST_DENSITY = 2.4
_FORCE_INTERVAL = 2
_MAX_CATCH_UP_STEPS = 4
_COLOR_LEVELS = 5
_BARE_FOREGROUND_COLORS = frozenset(
    {
        "black",
        "blue",
        "brightblack",
        "brightblue",
        "brightcyan",
        "brightgreen",
        "brightmagenta",
        "brightred",
        "brightwhite",
        "brightyellow",
        "cyan",
        "default",
        "green",
        "magenta",
        "red",
        "white",
        "yellow",
    }
)


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PluginRegistrationError(f"water {field} must be a number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as error:
        raise PluginRegistrationError(f"water {field} must be finite") from error
    if not math.isfinite(result):
        raise PluginRegistrationError(f"water {field} must be finite")
    return result


def _positive_number(value: object, field: str) -> float:
    result = _number(value, field)
    if result <= 0:
        raise PluginRegistrationError(f"water {field} must be positive")
    return result


@dataclass(slots=True)
class _Particle:
    identifier: int
    x: float
    y: float
    vx: float
    vy: float
    width: int
    character: str
    style: str
    local_pressure: float = 0.0
    floor_impacts: int = 0
    last_floor_impact_step: int = -1


@dataclass(slots=True)
class _WaterState:
    particles: list[_Particle]
    step: int = 0
    drain_credit: float = 0.0
    accelerations: dict[int, tuple[float, float]] = field(default_factory=dict)
    initial_particle_count: int = 0


def _graphemes(text: str) -> list[str]:
    graphemes: list[str] = []
    cluster = ""
    for character in text:
        joins_cluster = bool(cluster) and (
            unicodedata.combining(character) != 0
            or character == "\u200d"
            or cluster.endswith("\u200d")
            or "\ufe00" <= character <= "\ufe0f"
            or "\U0001f3fb" <= character <= "\U0001f3ff"
            or "\U000e0020" <= character <= "\U000e007f"
            or terminal_cell_width(cluster) == 0
            or (
                "\U0001f1e6" <= character <= "\U0001f1ff"
                and all("\U0001f1e6" <= item <= "\U0001f1ff" for item in cluster)
                and len(cluster) % 2 == 1
            )
        )
        if cluster and not joins_cluster:
            graphemes.append(cluster)
            cluster = ""
        cluster += character
    if cluster:
        graphemes.append(cluster)
    return graphemes


def _styled_graphemes(fragments: tuple[tuple[str, str], ...]) -> list[tuple[str, str]]:
    codepoints = [(style, character) for style, text in fragments for character in text]
    result: list[tuple[str, str]] = []
    offset = 0
    for grapheme in _graphemes("".join(character for _style, character in codepoints)):
        cluster = codepoints[offset : offset + len(grapheme)]
        style = next(
            (
                candidate_style
                for candidate_style, character in cluster
                if terminal_cell_width(character) > 0
            ),
            cluster[0][0],
        )
        result.append((style, grapheme))
        offset += len(grapheme)
    return result


def _source_particles(context: ScreenClearContext) -> list[_Particle]:
    particles: list[_Particle] = []
    styled_lines = context.styled_lines or tuple((("", line),) for line in context.lines)
    identifier = 0
    for row, fragments in enumerate(styled_lines):
        column = 0
        line_particles: list[_Particle] = []
        for style, character in _styled_graphemes(fragments):
            width = terminal_cell_width(character)
            if width <= 0:
                if line_particles:
                    line_particles[-1].character += character
                continue
            if column + width > context.width:
                break
            if not character.isspace():
                center_column = column + (width - 1) / 2
                horizontal_jitter = ((identifier * 37 + context.seed * 17) % 101 / 100 - 0.5) * 0.44
                vertical_jitter = ((identifier * 61 + context.seed * 29) % 103 / 102 - 0.5) * 0.88
                line_particles.append(
                    _Particle(
                        identifier=identifier,
                        x=center_column * _CELL_ASPECT + horizontal_jitter,
                        y=min(len(context.lines) - 1, max(0.0, row + vertical_jitter)),
                        vx=0.0,
                        vy=0.0,
                        width=width,
                        character=character,
                        style=style,
                    )
                )
                identifier += 1
            column += width
        particles.extend(line_particles)
    return particles


def _spatial_hash(
    particles: list[_Particle],
    smoothing_radius: float,
) -> dict[tuple[int, int], list[int]]:
    cells: dict[tuple[int, int], list[int]] = {}
    for index, particle in enumerate(particles):
        key = (
            math.floor(particle.x / smoothing_radius),
            math.floor(particle.y / smoothing_radius),
        )
        cells.setdefault(key, []).append(index)
    return cells


def _neighbor_indices(
    particle: _Particle,
    cells: dict[tuple[int, int], list[int]],
    smoothing_radius: float,
) -> list[int]:
    cell_x = math.floor(particle.x / smoothing_radius)
    cell_y = math.floor(particle.y / smoothing_radius)
    return [
        index
        for offset_y in (-1, 0, 1)
        for offset_x in (-1, 0, 1)
        for index in cells.get((cell_x + offset_x, cell_y + offset_y), ())
    ]


def _kernel(distance_squared: float, radius_squared: float) -> float:
    if distance_squared >= radius_squared:
        return 0.0
    value = 1 - distance_squared / radius_squared
    return value * value * value


def _neighbor_pairs(
    particles: list[_Particle],
    cells: dict[tuple[int, int], list[int]],
    smoothing_radius: float,
) -> list[tuple[int, int, float, float, float, float]]:
    radius_squared = smoothing_radius * smoothing_radius
    pairs: list[tuple[int, int, float, float, float, float]] = []
    for index, particle in enumerate(particles):
        for neighbor_index in _neighbor_indices(particle, cells, smoothing_radius):
            if neighbor_index <= index:
                continue
            neighbor = particles[neighbor_index]
            dx = particle.x - neighbor.x
            dy = particle.y - neighbor.y
            distance_squared = dx * dx + dy * dy
            if distance_squared <= 1e-9 or distance_squared >= radius_squared:
                continue
            distance = math.sqrt(distance_squared)
            pairs.append(
                (
                    index,
                    neighbor_index,
                    dx,
                    dy,
                    distance,
                    1 - distance / smoothing_radius,
                )
            )
    return pairs


def _densities(
    particles: list[_Particle],
    cells: dict[tuple[int, int], list[int]],
    smoothing_radius: float,
) -> list[float]:
    values = [1.0] * len(particles)
    radius_squared = smoothing_radius * smoothing_radius
    for index, neighbor_index, _dx, _dy, distance, _proximity in _neighbor_pairs(
        particles, cells, smoothing_radius
    ):
        weight = _kernel(distance * distance, radius_squared)
        values[index] += weight
        values[neighbor_index] += weight
    return values


def _boundary_x(particle: _Particle, width: int) -> tuple[float, float]:
    half_width = (particle.width - 1) * _CELL_ASPECT / 2
    return half_width, max(half_width, (width - 1) * _CELL_ASPECT - half_width)


def _drain_particles(
    state: _WaterState,
    *,
    height: int,
    width: int,
    frames_per_second: float,
    drain_rate: float,
    duration_seconds: float | None = None,
) -> bool:
    settling_steps = max(1, round(min(2.0, height / 8) * frames_per_second))
    rebound_steps = max(2, round(0.15 * frames_per_second))
    if state.step <= settling_steps:
        return False
    effective_drain_rate = drain_rate
    if duration_seconds is not None and state.initial_particle_count:
        settling_seconds = settling_steps / frames_per_second
        effective_drain_rate = max(
            drain_rate,
            state.initial_particle_count / max(1.0, duration_seconds - settling_seconds),
        )
    state.drain_credit += effective_drain_rate / frames_per_second
    allowance = int(state.drain_credit)
    state.drain_credit -= allowance
    if allowance == 0:
        return False

    rebound_ids = {
        particle.identifier
        for particle in state.particles
        if particle.floor_impacts == 1
        and state.step - particle.last_floor_impact_step <= rebound_steps
    }
    bottom = sorted(
        (
            particle
            for particle in state.particles
            if particle.y >= height - 1.2
            and particle.identifier not in rebound_ids
            and particle.floor_impacts > 0
        ),
        key=lambda particle: (abs(particle.x - width * _CELL_ASPECT / 2), particle.identifier),
    )
    bottom_ids = {particle.identifier for particle in bottom}
    left = sorted(
        (
            particle
            for particle in state.particles
            if particle.identifier not in bottom_ids
            and particle.identifier not in rebound_ids
            and particle.x <= _boundary_x(particle, width)[0] + 0.12
        ),
        key=lambda particle: (-particle.y, particle.identifier),
    )
    left_ids = {particle.identifier for particle in left}
    right = sorted(
        (
            particle
            for particle in state.particles
            if particle.identifier not in bottom_ids
            and particle.identifier not in left_ids
            and particle.identifier not in rebound_ids
            and particle.x >= _boundary_x(particle, width)[1] - 0.12
        ),
        key=lambda particle: (-particle.y, particle.identifier),
    )
    outlets = (bottom, left, right)
    selected: list[_Particle] = []
    outlet_index = state.step % len(outlets)
    while len(selected) < allowance and any(outlets):
        outlet = outlets[outlet_index % len(outlets)]
        if outlet:
            selected.append(outlet.pop(0))
        outlet_index += 1
    removed = {particle.identifier for particle in selected}
    state.particles = [
        particle for particle in state.particles if particle.identifier not in removed
    ]
    return bool(removed)


def _advance_sph(
    state: _WaterState,
    *,
    height: int,
    width: int,
    frames_per_second: float,
    drain_rate: float,
    gravity: float,
    pressure: float,
    viscosity: float,
    surface_tension: float,
    smoothing_radius: float,
    slosh_strength: float,
    duration_seconds: float | None = None,
    floor_restitution: float = 0.22,
) -> None:
    state.step += 1
    drained = _drain_particles(
        state,
        height=height,
        width=width,
        frames_per_second=frames_per_second,
        drain_rate=drain_rate,
        duration_seconds=duration_seconds,
    )
    particles = state.particles
    if not particles:
        return

    if drained or state.step % _FORCE_INTERVAL == 1 or not state.accelerations:
        cells = _spatial_hash(particles, smoothing_radius)
        pairs = _neighbor_pairs(particles, cells, smoothing_radius)
        radius_squared = smoothing_radius * smoothing_radius
        density = [1.0] * len(particles)
        for index, neighbor_index, _dx, _dy, distance, _proximity in pairs:
            weight = _kernel(distance * distance, radius_squared)
            density[index] += weight
            density[neighbor_index] += weight
        particle_pressure = [max(0.0, pressure * (value - _REST_DENSITY)) for value in density]
        for particle, local_pressure in zip(particles, particle_pressure, strict=True):
            particle.local_pressure = local_pressure
        pane_center = (width - 1) * _CELL_ASPECT / 2
        mass_center = sum(particle.x for particle in particles) / len(particles)
        imbalance = (pane_center - mass_center) / max(0.5, pane_center)
        elapsed_seconds = state.step / frames_per_second
        slosh = slosh_strength * (imbalance * 3 + math.sin(elapsed_seconds * 1.7) * 0.45)
        acceleration_x = [slosh] * len(particles)
        acceleration_y = [gravity] * len(particles)
        for index, neighbor_index, dx, dy, distance, proximity in pairs:
            inverse_density = 1 / density[index]
            inverse_neighbor_density = 1 / density[neighbor_index]
            pair_inverse_density = (inverse_density + inverse_neighbor_density) * 0.5
            pressure_force = (
                (particle_pressure[index] + particle_pressure[neighbor_index])
                * 0.5
                * proximity
                * proximity
            )
            unit_x = dx / distance
            unit_y = dy / distance
            acceleration_x[index] += pressure_force * unit_x * pair_inverse_density
            acceleration_y[index] += pressure_force * unit_y * pair_inverse_density
            acceleration_x[neighbor_index] -= pressure_force * unit_x * pair_inverse_density
            acceleration_y[neighbor_index] -= pressure_force * unit_y * pair_inverse_density

            particle = particles[index]
            neighbor = particles[neighbor_index]
            viscous_weight = viscosity * proximity
            velocity_x = neighbor.vx - particle.vx
            velocity_y = neighbor.vy - particle.vy
            acceleration_x[index] += velocity_x * viscous_weight * pair_inverse_density
            acceleration_y[index] += velocity_y * viscous_weight * pair_inverse_density
            acceleration_x[neighbor_index] -= velocity_x * viscous_weight * pair_inverse_density
            acceleration_y[neighbor_index] -= velocity_y * viscous_weight * pair_inverse_density

            cohesive_weight = surface_tension * proximity * proximity
            acceleration_x[index] -= cohesive_weight * dx * pair_inverse_density
            acceleration_y[index] -= cohesive_weight * dy * pair_inverse_density
            acceleration_x[neighbor_index] += cohesive_weight * dx * pair_inverse_density
            acceleration_y[neighbor_index] += cohesive_weight * dy * pair_inverse_density

        if duration_seconds is not None and state.step >= duration_seconds * frames_per_second:
            for index, particle in enumerate(particles):
                outlet = particle.identifier % 3
                if outlet == 0:
                    target_x = particle.x
                    target_y = height - 1
                elif outlet == 1:
                    target_x = _boundary_x(particle, width)[0]
                    target_y = particle.y
                else:
                    target_x = _boundary_x(particle, width)[1]
                    target_y = particle.y
                direction_x = target_x - particle.x
                direction_y = target_y - particle.y
                distance = math.hypot(direction_x, direction_y)
                if distance > 1e-9:
                    acceleration_x[index] += 60 * direction_x / distance
                    acceleration_y[index] += 60 * direction_y / distance

        maximum_acceleration = max(
            math.hypot(value_x, value_y)
            for value_x, value_y in zip(acceleration_x, acceleration_y, strict=True)
        )
        acceleration_scale = min(1.0, 60 / maximum_acceleration) if maximum_acceleration else 1.0
        state.accelerations = {}
        for particle, value_x, value_y in zip(
            particles, acceleration_x, acceleration_y, strict=True
        ):
            state.accelerations[particle.identifier] = (
                value_x * acceleration_scale,
                value_y * acceleration_scale,
            )

    delta = 1 / frames_per_second
    for particle in particles:
        acceleration_x, acceleration_y = state.accelerations[particle.identifier]
        particle.vx += acceleration_x * delta
        particle.vy += acceleration_y * delta
    maximum_speed = max(math.hypot(particle.vx, particle.vy) for particle in particles)
    velocity_scale = min(1.0, 10 / maximum_speed) if maximum_speed else 1.0
    for particle in particles:
        particle.vx *= velocity_scale
        particle.vy *= velocity_scale
        particle.x += particle.vx * delta
        particle.y += particle.vy * delta

        minimum_x, maximum_x = _boundary_x(particle, width)
        if particle.x < minimum_x:
            particle.x = minimum_x
            particle.vx = abs(particle.vx) * 0.35
        elif particle.x > maximum_x:
            particle.x = maximum_x
            particle.vx = -abs(particle.vx) * 0.35
        if particle.y < 0:
            particle.y = 0
            particle.vy = abs(particle.vy) * 0.2
        elif particle.y > height - 1:
            particle.y = height - 1
            particle.vy = -abs(particle.vy) * floor_restitution
            particle.floor_impacts += 1
            particle.last_floor_impact_step = state.step


def _candidate_cells(particle: _Particle) -> list[tuple[int, int]]:
    row = round(particle.y)
    column = round(particle.x / _CELL_ASPECT - (particle.width - 1) / 2)
    candidates = [(row, column)]
    for radius in range(1, 4):
        candidates.extend(
            (row - vertical, column + horizontal)
            for vertical in range(radius + 1)
            for horizontal in (-radius, radius)
        )
        candidates.append((row - radius, column))
    return candidates


def _dynamic_water_style(particle: _Particle) -> str:
    speed_intensity = min(1.0, math.hypot(particle.vx, particle.vy) / 10)
    pressure_intensity = (
        particle.local_pressure / (particle.local_pressure + 24)
        if particle.local_pressure > 0
        else 0.0
    )
    speed_intensity = round(speed_intensity * (_COLOR_LEVELS - 1)) / (_COLOR_LEVELS - 1)
    pressure_intensity = round(pressure_intensity * (_COLOR_LEVELS - 1)) / (_COLOR_LEVELS - 1)
    slow_blue = (12, 45, 86)
    fast_blue = (32, 170, 255)
    velocity_color = tuple(
        round(slow + (fast - slow) * speed_intensity)
        for slow, fast in zip(slow_blue, fast_blue, strict=True)
    )
    pressure_brightness = pressure_intensity * 0.75
    color = tuple(
        round(channel + (highlight - channel) * pressure_brightness)
        for channel, highlight in zip(velocity_color, (225, 248, 255), strict=True)
    )
    foreground = "#" + "".join(f"{channel:02x}" for channel in color)
    source_attributes = " ".join(
        token
        for token in particle.style.split()
        if not token.startswith(("fg:", "#", "ansi"))
        and token.casefold() not in _BARE_FOREGROUND_COLORS
    )
    return f"{source_attributes} fg:{foreground}".strip()


def _render_particles(
    particles: list[_Particle],
    *,
    height: int,
    width: int,
    color_mode: str = "source",
) -> list[tuple[str, str]]:
    grid: list[list[tuple[str, str] | None]] = [[None for _ in range(width)] for _ in range(height)]
    for particle in sorted(particles, key=lambda item: (item.y, item.identifier), reverse=True):
        destination = None
        for row, column in _candidate_cells(particle):
            if not (0 <= row < height and column >= 0 and column + particle.width <= width):
                continue
            if particle.width == 1:
                available = grid[row][column] is None
            else:
                available = all(
                    grid[row][cell] is None for cell in range(column, column + particle.width)
                )
            if available:
                destination = (row, column)
                break
        if destination is None:
            continue
        row, column = destination
        style = _dynamic_water_style(particle) if color_mode == "dynamic" else particle.style
        grid[row][column] = (style, particle.character)
        padding = max(0, particle.width - terminal_cell_width(particle.character))
        for offset in range(1, particle.width):
            grid[row][column + offset] = ("", " " if offset <= padding else "")

    fragments: list[tuple[str, str]] = []
    for row_number, row in enumerate(grid):
        active_style = ""
        active_text = ""
        for cell in row:
            style, character = ("", " ") if cell is None else cell
            if style != active_style and active_text:
                fragments.append((active_style, active_text))
                active_text = ""
            active_style = style
            active_text += character
        if active_text:
            fragments.append((active_style, active_text.rstrip()))
        if row_number + 1 < height:
            fragments.append(("", "\n"))
    return fragments


class _WaterRenderer:
    def __init__(
        self,
        *,
        duration_seconds: float,
        frames_per_second: float,
        drain_rate: float,
        gravity: float,
        pressure: float,
        viscosity: float,
        surface_tension: float,
        smoothing_radius: float,
        slosh_strength: float,
        color_mode: str = "source",
        floor_restitution: float = 0.22,
    ) -> None:
        self.duration_seconds = duration_seconds
        self.frames_per_second = frames_per_second
        self.drain_rate = drain_rate
        self.gravity = gravity
        self.pressure = pressure
        self.viscosity = viscosity
        self.surface_tension = surface_tension
        self.smoothing_radius = smoothing_radius
        self.slosh_strength = slosh_strength
        self.color_mode = color_mode
        self.floor_restitution = floor_restitution
        self._key: tuple[object, ...] | None = None
        self._state: _WaterState | None = None

    def __call__(self, context: ScreenClearContext) -> list[tuple[str, str]]:
        if not context.lines:
            self._key = (context.lines, context.styled_lines, context.width, context.seed)
            self._state = _WaterState([])
            return []
        key = (context.lines, context.styled_lines, context.width, context.seed)
        elapsed_seconds = (
            context.elapsed_seconds
            if context.elapsed_seconds is not None
            else context.progress * self.duration_seconds
        )
        target_step = int(elapsed_seconds * self.frames_per_second)
        continued_without_elapsed = (
            self._state is not None and context.elapsed_seconds is None and context.progress >= 1
        )
        if (
            self._key != key
            or self._state is None
            or (target_step < self._state.step and not continued_without_elapsed)
        ):
            self._key = key
            particles = _source_particles(context)
            self._state = _WaterState(
                particles,
                initial_particle_count=len(particles),
            )
        elif (
            context.elapsed_seconds is None
            and context.progress >= 1
            and target_step <= self._state.step
        ):
            target_step = self._state.step + 1
        catch_up_steps = 0
        while self._state.step < target_step and catch_up_steps < _MAX_CATCH_UP_STEPS:
            _advance_sph(
                self._state,
                height=len(context.lines),
                width=context.width,
                frames_per_second=self.frames_per_second,
                drain_rate=self.drain_rate,
                gravity=self.gravity,
                pressure=self.pressure,
                viscosity=self.viscosity,
                surface_tension=self.surface_tension,
                smoothing_radius=self.smoothing_radius,
                slosh_strength=self.slosh_strength,
                duration_seconds=self.duration_seconds,
                floor_restitution=self.floor_restitution,
            )
            catch_up_steps += 1
        if not self._state.particles:
            return []
        return _render_particles(
            self._state.particles,
            height=len(context.lines),
            width=context.width,
            color_mode=self.color_mode,
        )

    def is_complete(self) -> bool:
        return self._state is not None and not self._state.particles


def render_water(
    context: ScreenClearContext,
    *,
    duration_seconds: float = 10.0,
    frames_per_second: float = 24.0,
    drain_rate: float = 60.0,
    gravity: float = 9.0,
    pressure: float = 18.0,
    viscosity: float = 2.2,
    surface_tension: float = 1.4,
    smoothing_radius: float = 1.45,
    slosh_strength: float = 0.85,
    color_mode: str = "source",
    floor_restitution: float = 0.22,
) -> list[tuple[str, str]]:
    return _WaterRenderer(
        duration_seconds=duration_seconds,
        frames_per_second=frames_per_second,
        drain_rate=drain_rate,
        gravity=gravity,
        pressure=pressure,
        viscosity=viscosity,
        surface_tension=surface_tension,
        smoothing_radius=smoothing_radius,
        slosh_strength=slosh_strength,
        color_mode=color_mode,
        floor_restitution=floor_restitution,
    )(context)


class WaterPlugin:
    api_version = PLUGIN_API_VERSION

    def register(self, registrar: PluginRegistrar, config: Mapping[str, Any]) -> None:
        unknown = set(config) - _FIELDS
        if unknown:
            raise PluginRegistrationError("unknown water fields: " + ", ".join(sorted(unknown)))
        duration_seconds = _positive_number(
            config.get("duration_seconds", 10.0), "duration_seconds"
        )
        if duration_seconds > MAX_SCREEN_CLEAR_DURATION_SECONDS:
            raise PluginRegistrationError(
                f"water duration_seconds cannot exceed {MAX_SCREEN_CLEAR_DURATION_SECONDS:g}"
            )
        frames_per_second = _positive_number(
            config.get("frames_per_second", 24.0), "frames_per_second"
        )
        if frames_per_second < 1:
            raise PluginRegistrationError("water frames_per_second cannot be less than 1")
        if frames_per_second > 30:
            raise PluginRegistrationError("water frames_per_second cannot exceed 30")
        drain_rate = _positive_number(config.get("drain_rate", 60.0), "drain_rate")
        if drain_rate > 10_000:
            raise PluginRegistrationError("water drain_rate cannot exceed 10000")
        gravity = _positive_number(config.get("gravity", 9.0), "gravity")
        if gravity > 50:
            raise PluginRegistrationError("water gravity cannot exceed 50")
        pressure = _positive_number(config.get("pressure", 18.0), "pressure")
        if pressure > 100:
            raise PluginRegistrationError("water pressure cannot exceed 100")
        viscosity = _positive_number(config.get("viscosity", 2.2), "viscosity")
        if viscosity > 20:
            raise PluginRegistrationError("water viscosity cannot exceed 20")
        surface_tension = _positive_number(config.get("surface_tension", 1.4), "surface_tension")
        if surface_tension > 20:
            raise PluginRegistrationError("water surface_tension cannot exceed 20")
        smoothing_radius = _positive_number(
            config.get("smoothing_radius", 1.45), "smoothing_radius"
        )
        if not 0.75 <= smoothing_radius <= 3:
            raise PluginRegistrationError("water smoothing_radius must be between 0.75 and 3")
        slosh_strength = _number(config.get("slosh_strength", 0.85), "slosh_strength")
        if not 0 <= slosh_strength <= 1:
            raise PluginRegistrationError("water slosh_strength must be between 0 and 1")
        color_mode = config.get("color_mode", "source")
        if not isinstance(color_mode, str) or color_mode not in {"source", "dynamic"}:
            raise PluginRegistrationError("water color_mode must be source or dynamic")
        floor_restitution = _number(config.get("floor_restitution", 0.22), "floor_restitution")
        if not 0 <= floor_restitution <= 1:
            raise PluginRegistrationError("water floor_restitution must be between 0 and 1")
        renderer = _WaterRenderer(
            duration_seconds=duration_seconds,
            frames_per_second=frames_per_second,
            drain_rate=drain_rate,
            gravity=gravity,
            pressure=pressure,
            viscosity=viscosity,
            surface_tension=surface_tension,
            smoothing_radius=smoothing_radius,
            slosh_strength=slosh_strength,
            color_mode=color_mode,
            floor_restitution=floor_restitution,
        )
        registrar.register_screen_clear_effect(
            renderer,
            duration_seconds=duration_seconds,
            frames_per_second=frames_per_second,
            is_complete=renderer.is_complete,
        )


plugin = WaterPlugin()

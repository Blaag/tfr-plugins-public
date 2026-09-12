from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tfr.plugin_api import BorderCellContext, BorderFragment, PluginRegistrar


class MarchingAntsPlugin:
    api_version = 1

    def register(self, registrar: PluginRegistrar, config: Mapping[str, Any]) -> None:
        frames_per_second = float(config.get("frames_per_second", 8))
        registrar.register_border_effect(
            "marching_ants",
            lambda context, fragment: self.transform(
                context,
                fragment,
                frames_per_second,
            ),
            frames_per_second=frames_per_second,
        )

    @staticmethod
    def transform(
        context: BorderCellContext,
        fragment: BorderFragment,
        frames_per_second: float,
    ) -> BorderFragment:
        phase = int(context.elapsed_seconds * frames_per_second)
        if (context.perimeter_index - phase) % 6 < 3:
            return BorderFragment(fragment.character, f"{fragment.style} reverse")
        return fragment


plugin = MarchingAntsPlugin()

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from tfr.config import (
    ConfigurationError,
    UiConfiguration,
    default_config_path,
    load_ui_configuration,
)
from tfr.plugin_releases import (
    PluginReleaseError,
    PluginReleaseLayout,
    PluginReleaseManifest,
    fetch_plugin_release_manifest,
    install_plugin_release,
)
from tfr.plugin_sources import normalize_repo_url, source_slug

_OFFICIAL_REPOSITORY = "https://github.com/Blaag/tfr-plugins-public"
_OFFICIAL_MANIFEST_URL = (
    "https://github.com/Blaag/tfr-plugins-public/releases/latest/download/plugin-manifest.json"
)


class PluginInstallationError(ValueError):
    """Raised when the configured public plugin source cannot be updated safely."""


def _repository_identity(value: str) -> str:
    return normalize_repo_url(value).removesuffix(".git").rstrip("/").lower()


@contextmanager
def _isolated_git_environment() -> Iterator[None]:
    managed_names = {name for name in os.environ if name.startswith("GIT_")} | {
        "GIT_ATTR_NOSYSTEM",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_NOSYSTEM",
        "GIT_TEMPLATE_DIR",
        "GIT_TERMINAL_PROMPT",
        "GCM_INTERACTIVE",
    }
    original = {name: os.environ[name] for name in managed_names if name in os.environ}
    for name in managed_names:
        os.environ.pop(name, None)
    with tempfile.TemporaryDirectory(prefix="tfr-plugin-git-template-") as template:
        os.environ.update(
            {
                "GIT_ATTR_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TEMPLATE_DIR": template,
                "GIT_TERMINAL_PROMPT": "0",
                "GCM_INTERACTIVE": "Never",
            }
        )
        try:
            yield
        finally:
            for name in managed_names:
                os.environ.pop(name, None)
            os.environ.update(original)


def install_latest_stable(
    bundle: UiConfiguration,
    *,
    timeout: float = 10.0,
    fetch_manifest: Callable[..., PluginReleaseManifest] = fetch_plugin_release_manifest,
    install_release: Callable[..., Path] = install_plugin_release,
) -> PluginReleaseManifest:
    sources = tuple(
        source
        for source in bundle.main.plugins.sources
        if _repository_identity(source.repo) == _repository_identity(_OFFICIAL_REPOSITORY)
        and source.policy in {"stable-auto", "stable-notify"}
    )
    if len(sources) != 1:
        raise PluginInstallationError(
            "configuration must contain exactly one stable Blaag/tfr-plugins-public source"
        )
    source = sources[0]
    if source.path != ".":
        raise PluginInstallationError("the public plugin source path must be '.'")
    manifest_url = str(source.manifest_url)
    if manifest_url != _OFFICIAL_MANIFEST_URL:
        raise PluginInstallationError(
            "the public plugin source must use the official stable manifest URL"
        )
    manifest = fetch_manifest(manifest_url, timeout=timeout)
    if manifest.project != "tfr-plugins-public":
        raise PluginInstallationError("stable manifest project must be tfr-plugins-public")
    manifest.assert_compatible()
    repository_url = normalize_repo_url(source.repo)
    layout = PluginReleaseLayout(
        (
            bundle.main.plugins.state_directory.expanduser()
            / "managed"
            / source_slug(repository_url)
        ).resolve()
    )
    with _isolated_git_environment():
        install_release(
            layout,
            manifest,
            repo_url=repository_url,
            manifest_url=manifest_url,
            source_path=source.path,
        )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install-from-checkout",
        description="Install the latest verified stable public plugin release for TFR.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config_path(),
        help="main TFR JSONC configuration file (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="manifest request timeout in seconds (default: %(default)s)",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0 < args.timeout <= 60:
        print(
            "install-from-checkout: --timeout must be greater than zero and at most 60",
            file=sys.stderr,
        )
        return 2
    try:
        bundle = load_ui_configuration(args.config)
        manifest = install_latest_stable(bundle, timeout=args.timeout)
    except (ConfigurationError, OSError, PluginInstallationError, PluginReleaseError) as exc:
        print(f"install-from-checkout: {exc}", file=sys.stderr)
        return 2
    print(f"Installed and activated tfr-plugins-public {manifest.version} ({manifest.commit}).")
    print("Restart TFR to load the updated plugins.")
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from tfr.config import PluginSource
from tfr.plugin_releases import PluginReleaseManifest

import tfr_plugins_public.install_checkout as install_checkout_module
from tfr_plugins_public.install_checkout import PluginInstallationError, install_latest_stable

OFFICIAL_MANIFEST = (
    "https://github.com/Blaag/tfr-plugins-public/releases/latest/download/plugin-manifest.json"
)


def manifest() -> PluginReleaseManifest:
    return PluginReleaseManifest(
        project="tfr-plugins-public",
        version="0.1.3",
        tag="v0.1.3",
        commit="a" * 40,
        tfr_minimum="0.1.1",
        tfr_maximum_exclusive="0.2.0",
        plugin_api_minimum=1,
        plugin_api_maximum=1,
        plugins=("gag",),
        release_url="https://example.invalid/releases/v0.1.3",
        artifact_url="https://example.invalid/releases/plugin.whl",
        artifact_size=1,
        artifact_sha256="b" * 64,
    )


def bundle(tmp_path: Path, *sources: PluginSource) -> SimpleNamespace:
    return SimpleNamespace(
        main=SimpleNamespace(
            plugins=SimpleNamespace(
                sources=sources,
                state_directory=tmp_path / "plugins",
            )
        )
    )


def test_installs_configured_stable_public_release(tmp_path: Path) -> None:
    source = PluginSource(
        repo="Blaag/tfr-plugins-public",
        policy="stable-notify",
        manifest_url=OFFICIAL_MANIFEST,
    )
    release = manifest()
    installed: dict[str, object] = {}

    def install(layout: object, received: object, **options: object) -> Path:
        installed.update(layout=layout, manifest=received, **options)
        installed["git_config_global"] = os.environ.get("GIT_CONFIG_GLOBAL")
        installed["git_template"] = os.environ.get("GIT_TEMPLATE_DIR")
        return tmp_path / "checkout"

    result = install_latest_stable(
        bundle(tmp_path, source),  # type: ignore[arg-type]
        timeout=7,
        fetch_manifest=lambda url, *, timeout: (
            release
            if (url, timeout) == (str(source.manifest_url), 7)
            else pytest.fail("unexpected manifest request")
        ),
        install_release=install,
    )

    assert result is release
    assert installed["manifest"] is release
    assert installed["repo_url"] == "https://github.com/Blaag/tfr-plugins-public.git"
    assert installed["manifest_url"] == str(source.manifest_url)
    assert installed["source_path"] == "."
    assert installed["git_config_global"] == os.devnull
    assert Path(str(installed["git_template"])).is_dir() is False


def test_requires_exactly_one_configured_stable_public_source(tmp_path: Path) -> None:
    unrelated = PluginSource(repo="owner/other")

    with pytest.raises(PluginInstallationError, match="exactly one stable"):
        install_latest_stable(bundle(tmp_path, unrelated))  # type: ignore[arg-type]


def test_rejects_a_nonofficial_manifest_authority(tmp_path: Path) -> None:
    source = PluginSource(
        repo="Blaag/tfr-plugins-public",
        policy="stable-auto",
        manifest_url="https://mirror.invalid/plugin-manifest.json",
    )

    with pytest.raises(PluginInstallationError, match="official stable manifest"):
        install_latest_stable(bundle(tmp_path, source))  # type: ignore[arg-type]


def test_shell_installer_resolves_external_symlink(tmp_path: Path) -> None:
    script = Path(__file__).parents[1] / "scripts" / "install-from-checkout"
    link = tmp_path / "public-plugin-installer"
    link.symlink_to(script)

    result = subprocess.run(
        [str(link), "--help"],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "TFR_PYTHON": sys.executable},
    )

    assert result.returncode == 0
    assert "latest verified stable public plugin release" in result.stdout


def test_cli_needs_only_the_ui_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "config.jsonc"
    config.write_text(
        '{"schema_version": 1, "worlds_file": "missing-worlds.jsonc", '
        '"agents_file": "missing-agents.jsonc", "plugins": {"sources": [{'
        '"repo": "Blaag/tfr-plugins-public", "policy": "stable-auto", '
        f'"manifest_url": "{OFFICIAL_MANIFEST}"'
        "}]}}",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        install_checkout_module,
        "install_latest_stable",
        lambda _bundle, *, timeout: manifest(),
    )

    assert install_checkout_module.run(["--config", str(config)]) == 0


def test_cli_reports_filesystem_errors_without_a_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "config.jsonc"
    config.write_text('{"schema_version": 1}', encoding="utf-8")

    def fail(_bundle: object, *, timeout: float) -> PluginReleaseManifest:
        raise PermissionError("state directory is read-only")

    monkeypatch.setattr(install_checkout_module, "install_latest_stable", fail)

    assert install_checkout_module.run(["--config", str(config)]) == 2
    assert "state directory is read-only" in capsys.readouterr().err

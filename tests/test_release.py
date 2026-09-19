from __future__ import annotations

import hashlib
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
PUBLISH_SCRIPT = ROOT / "scripts" / "publish-release"
SPEC = importlib.util.spec_from_file_location(
    "build_plugin_manifest", ROOT / "scripts" / "build_plugin_manifest.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )


def create_repository(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    repository = tmp_path / "repository"
    subprocess.run(
        ["git", "init", "--bare", "--quiet", "--initial-branch=main", str(remote)],
        check=True,
    )
    (repository / "scripts").mkdir(parents=True)
    shutil.copy2(PUBLISH_SCRIPT, repository / "scripts" / "publish-release")
    (repository / "pyproject.toml").write_text(
        '[project]\nname = "tfr-plugins-public"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    git(repository, "init", "--quiet", "--initial-branch=main")
    git(repository, "config", "user.name", "TFR Plugin Tests")
    git(repository, "config", "user.email", "plugins@example.invalid")
    git(repository, "add", ".")
    git(repository, "commit", "--quiet", "-m", "fixture")
    git(repository, "remote", "add", "origin", str(remote))
    git(repository, "push", "--quiet", "--set-upstream", "origin", "main")
    return repository, remote


def publish(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(repository / "scripts" / "publish-release"), *arguments],
        check=False,
        capture_output=True,
        cwd=repository.parent,
        text=True,
    )


def test_manifest_records_compatibility_plugins_and_artifact(tmp_path: Path, monkeypatch) -> None:
    artifact = tmp_path / "plugins.whl"
    artifact.write_bytes(b"wheel")
    monkeypatch.chdir(ROOT)

    manifest = MODULE.build_manifest(
        repository="Blaag/tfr-plugins-public",
        tag="v0.1.1",
        commit="a" * 40,
        artifact=artifact,
    )

    assert manifest["compatibility"] == {
        "tfr_minimum": "0.1.1",
        "tfr_maximum_exclusive": "0.2.0",
        "plugin_api_minimum": 1,
        "plugin_api_maximum": 1,
    }
    assert manifest["plugins"] == sorted(
        [
            "cat",
            "border_reflection",
            "film_burn",
            "flame",
            "speaker_effects",
            "terminal_reveal",
            "vortex",
            "water",
        ]
    )
    assert manifest["artifact"]["sha256"] == hashlib.sha256(b"wheel").hexdigest()


@pytest.mark.parametrize(
    ("tag", "commit", "message"),
    [("v0.1.2", "a" * 40, "does not match"), ("v0.1.1", "abc", "full hexadecimal")],
)
def test_manifest_rejects_inconsistent_identity(
    tmp_path: Path, monkeypatch, tag: str, commit: str, message: str
) -> None:
    artifact = tmp_path / "plugins.whl"
    artifact.write_bytes(b"wheel")
    monkeypatch.chdir(ROOT)
    with pytest.raises(ValueError, match=message):
        MODULE.build_manifest(
            repository="Blaag/tfr-plugins-public", tag=tag, commit=commit, artifact=artifact
        )


def test_publish_preview_does_not_create_tag(tmp_path: Path) -> None:
    repository, remote = create_repository(tmp_path)
    result = publish(repository)
    assert result.returncode == 0
    assert "Release check passed: v0.1.0" in result.stdout
    assert git(repository, "tag", "--list").stdout == ""
    assert git(remote, "tag", "--list").stdout == ""


def test_publish_pushes_only_annotated_release_tag(tmp_path: Path) -> None:
    repository, remote = create_repository(tmp_path)
    git(repository, "tag", "-a", "v0.0.9", "-m", "local only")
    result = publish(repository, "--push")
    assert result.returncode == 0
    assert git(repository, "cat-file", "-t", "refs/tags/v0.1.0").stdout.strip() == "tag"
    assert git(remote, "tag", "--list").stdout == "v0.1.0\n"


def test_publish_rejects_dirty_unpushed_and_nested_tags(tmp_path: Path) -> None:
    repository, _remote = create_repository(tmp_path)
    (repository / "dirty").write_text("dirty", encoding="utf-8")
    assert "modified, staged, or untracked" in publish(repository).stderr
    (repository / "dirty").unlink()
    git(repository, "tag", "-a", "base", "-m", "base")
    git(repository, "tag", "-a", "v0.1.0", "-m", "nested", "base")
    result = publish(repository, "--push")
    assert result.returncode == 2
    assert "does not point directly to a commit" in result.stderr


def test_publish_rejects_non_main_and_unpushed_commits(tmp_path: Path) -> None:
    repository, _remote = create_repository(tmp_path)
    git(repository, "switch", "--quiet", "-c", "feature")
    assert "main branch" in publish(repository).stderr
    git(repository, "switch", "--quiet", "main")
    (repository / "local").write_text("local", encoding="utf-8")
    git(repository, "add", "local")
    git(repository, "commit", "--quiet", "-m", "local")
    assert "have not been pushed" in publish(repository).stderr

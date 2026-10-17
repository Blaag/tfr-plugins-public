from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from pathlib import Path
from urllib.parse import quote

SEMVER_PATTERN = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def _version(value: object, name: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or (match := SEMVER_PATTERN.fullmatch(value)) is None:
        raise ValueError(f"{name} must be a stable semantic version")
    return tuple(int(part) for part in match.groups())


def build_manifest(
    *, repository: str, tag: str, commit: str, artifact: Path
) -> dict[str, object]:
    document = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    project = document["project"]
    version = project.get("version")
    if project.get("name") != "tfr-plugins-public":
        raise ValueError("pyproject.toml must describe tfr-plugins-public")
    _version(version, "project.version")
    if tag != f"v{version}":
        raise ValueError(f"tag {tag!r} does not match project version {version!r}")
    commit = commit.casefold()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("commit must be a full hexadecimal Git commit")
    if REPOSITORY_PATTERN.fullmatch(repository) is None:
        raise ValueError("repository must be OWNER/REPOSITORY")
    if not artifact.is_file():
        raise ValueError(f"artifact does not exist: {artifact}")

    compatibility = document.get("tool", {}).get("tfr-release", {})
    expected_keys = {
        "tfr-minimum",
        "tfr-maximum-exclusive",
        "plugin-api-minimum",
        "plugin-api-maximum",
    }
    if set(compatibility) != expected_keys:
        raise ValueError(
            "[tool.tfr-release] must contain exactly the supported compatibility fields"
        )
    tfr_minimum = compatibility["tfr-minimum"]
    tfr_maximum = compatibility["tfr-maximum-exclusive"]
    if _version(tfr_minimum, "tfr-minimum") >= _version(
        tfr_maximum, "tfr-maximum-exclusive"
    ):
        raise ValueError("tfr-minimum must be lower than tfr-maximum-exclusive")
    api_minimum = compatibility["plugin-api-minimum"]
    api_maximum = compatibility["plugin-api-maximum"]
    if (
        not isinstance(api_minimum, int)
        or isinstance(api_minimum, bool)
        or not isinstance(api_maximum, int)
        or isinstance(api_maximum, bool)
        or api_minimum < 1
        or api_maximum < api_minimum
    ):
        raise ValueError("plugin API compatibility must be a positive inclusive range")

    entry_points = project.get("entry-points", {}).get("tfr.plugins.v1", {})
    if not isinstance(entry_points, dict) or not entry_points:
        raise ValueError("the release must contain tfr.plugins.v1 entry points")
    plugins = sorted(entry_points)
    if any(not isinstance(name, str) or not name for name in plugins):
        raise ValueError("plugin entry-point names must be nonempty strings")

    content = artifact.read_bytes()
    release_base = f"https://github.com/{repository}/releases"
    return {
        "schema_version": 1,
        "project": "tfr-plugins-public",
        "channel": "stable",
        "version": version,
        "tag": tag,
        "commit": commit,
        "compatibility": {
            "tfr_minimum": tfr_minimum,
            "tfr_maximum_exclusive": tfr_maximum,
            "plugin_api_minimum": api_minimum,
            "plugin_api_maximum": api_maximum,
        },
        "plugins": plugins,
        "release_url": f"{release_base}/tag/{quote(tag, safe='')}",
        "artifact": {
            "url": (
                f"{release_base}/download/{quote(tag, safe='')}/{quote(artifact.name, safe='')}"
            ),
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the stable TFR plugin manifest.")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("plugin-manifest.json"))
    args = parser.parse_args()
    try:
        manifest = build_manifest(
            repository=args.repository,
            tag=args.tag,
            commit=args.commit,
            artifact=args.artifact,
        )
    except (KeyError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

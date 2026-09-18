# Maintainer Guide

## Stable Releases

Stable releases are immutable, annotated Git tags named `vMAJOR.MINOR.PATCH`.
The project version, TFR compatibility range, plugin API range, and exported
entry-point names are authoritative in `pyproject.toml`.

1. Update `project.version` and compatibility metadata as needed.
2. Run `uv lock`, `uv sync --frozen`, `uv run ruff check .`, `uv run pytest -q`, and `uv build`.
3. Commit and push the reviewed change to `main`; wait for CI to pass.
4. Run `./scripts/publish-release` to preview all release checks.
5. Run `./scripts/publish-release --push` to create and push only the exact annotated tag.
6. Approve the protected `release` environment deployment after reviewing its commit and assets.

The workflow rebuilds from the tagged commit, verifies that the tag points
directly to that commit and remains on `main`, then publishes distributions and
`plugin-manifest.json`. Never move or recreate a stable tag, replace release
assets, or publish a lower version. Correct a release with a new version.

Repository administrators must protect `v*` tags from updates/deletion and
restrict tag creation, require review for the `release` environment, protect
`main`, and enable immutable GitHub releases.

## Recovery

If validation fails before the tag push, fix the branch and retry. If a tag was
pushed but publication failed, retain the tag and rerun the workflow for the
same commit. If released content is wrong, leave it intact, publish a corrected
higher version, and document the superseded release.

# Security Policy

## Trust Model

Plugins are trusted Python code loaded into the TFR process with the same
filesystem, network, and credential access as TFR. Install only releases from a
repository and maintainers you trust.

The stable channel binds four identities: an annotated semantic-version tag, a
full Git commit, package metadata, and `plugin-manifest.json`. Compatible TFR
versions verify those identities and the declared TFR/plugin API ranges before
importing plugin code. A release manifest is metadata, not a signature; GitHub
repository, workflow, tag, environment, and account security remain part of the
trust boundary.

Stable tags and release assets are immutable. Downgrades and a different commit
for an already seen version must be rejected. Consumers should retain their
previous verified checkout for rollback and must not silently fall back to
`main` when release retrieval or verification fails.

Report vulnerabilities privately through GitHub's security advisory interface.
Do not include credentials, private configuration, logs containing secrets, or
working exploits in a public issue.

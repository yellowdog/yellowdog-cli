# Release Process

## Branch Model

| Branch | Purpose |
|--------|---------|
| `main` | Current released version — always matches what is on PyPI |
| `next-version` | Ongoing development; pushed to origin to allow co-development |
| `feature/*` (or any name) | Larger features; branched from `next-version`, merged back when ready |

```
main          ──────────────────────────────●─────────────────────────────●──
                                            ↑ merge + tag                 ↑
next-version  ──────────────────────────────●─────────────────────────────●──
                             ↑ branch                            ↑ merge
feature/xyz   ───────────────●───────────────────────────────────●
```

## Quick Release (Automated)

Run `release.sh` from the `next-version` branch with a clean working tree:

```shell
./release.sh            # dry run — print every step without executing (default)
./release.sh --release  # execute the release for real
```

The script handles everything: version bump, format, tests, merge, tag, push, PyPI upload.

## Manual Release Steps

If you need to release without the script, or want to understand what it does:

### 1. Pre-flight

```shell
git checkout next-version
git status              # must be clean
git pull origin next-version
```

### 2. Bump the version

Edit `yellowdog_cli/_version.py`:
```python
__version__ = "X.Y.Z"
```

### 3. Format, check, and test

```shell
make format
make pypi_check         # builds and checks the distribution
pytest -v
```

### 4. Commit the version bump

```shell
git add yellowdog_cli/_version.py
git commit -m "Bump version to X.Y.Z"
```

### 5. Merge to `main` and tag

```shell
git checkout main
git merge --no-ff next-version -m "Release vX.Y.Z"
git tag -a vX.Y.Z -m "Version X.Y.Z"
```

### 6. Push `main` and tags

```shell
git push origin main --tags
```

### 7. Upload to PyPI

```shell
make pypi_upload
```

Requires a `~/.pypirc` entry named `yellowdog-cli` with the appropriate API token.

### 8. Return to `next-version`

```shell
git checkout next-version
git push origin next-version
```

## Pull Requests

When a PR is required (e.g. for external contributions or review), it should target the `next-version` branch, not `main`.

## Feature Branch Workflow

```shell
# Start a feature
git checkout next-version
git checkout -b feature/my-feature

# ... develop, commit ...

# Merge back when ready
git checkout next-version
git merge --no-ff feature/my-feature -m "Merge feature/my-feature"
git branch -d feature/my-feature
git push origin next-version
```

## Versioning Convention

`MAJOR.MINOR.PATCH` — increment:
- **MAJOR** for breaking changes or large feature sets
- **MINOR** for new features that are backwards-compatible
- **PATCH** for bug fixes and minor improvements

## PyPI Credentials

Twine reads `~/.pypirc`. The entry name must match the `--repository` argument in the Makefile.

For production PyPI (`make pypi_upload`):

```ini
[yellowdog-cli]
  repository = https://upload.pypi.org/legacy/
  username = __token__
  password = pypi-...
```

For Test PyPI (`make pypi_test_upload`):

```ini
[yellowdog-testpypi]
  repository = https://test.pypi.org/legacy/
  username = __token__
  password = pypi-...
```

Both passwords can be found in BitWarden.

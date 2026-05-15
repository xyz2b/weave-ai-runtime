# PyPI Release Readiness

This guide is the maintainer-facing release contract for the first public PyPI train of the concrete `packages/` workspace.

## Publication scope

- Publish only the self-contained concrete packages rooted at `packages/**/pyproject.toml`.
- Keep the repository root `pyproject.toml` unpublished. `weavert-workspace` remains a workspace coordinator for local development and repo-wide validation only.
- Keep repository-bound maintainer utilities such as `packages/toolchain/scripts` out of the public TestPyPI/PyPI train even when they keep package-local metadata for repo-local installs.
- Build, validate, and upload from each public package directory instead of from the repository root.

## Public package matrix

### Core runtime

| Package root | PyPI distribution | Import root | Runtime activation | Exposure tier |
| --- | --- | --- | --- | --- |
| `packages/framework-core` | `weavert` | `weavert` | `weavert-core` | Primary public runtime |

### Framework packs

| Package root | PyPI distribution | Import root | Runtime activation | Exposure tier |
| --- | --- | --- | --- | --- |
| `packages/framework-packs/capabilities/memory` | `weavert-memory` | `weavert_memory` | `weavert-memory` | Direct add-on |
| `packages/framework-packs/capabilities/team` | `weavert-team` | `weavert_team` | `weavert-team` | Direct add-on |
| `packages/framework-packs/mechanisms/compaction` | `weavert-compaction` | `weavert_compaction` | `weavert-compaction` | Direct add-on |
| `packages/framework-packs/mechanisms/isolation` | `weavert-isolation` | `weavert_isolation` | `weavert-isolation` | Direct add-on |
| `packages/framework-packs/integrations/openai` | `weavert-openai` | `weavert_openai` | `weavert-openai` | Direct add-on |
| `packages/framework-packs/integrations/hosts-reference` | `weavert-hosts-reference` | `weavert_hosts_reference` | `weavert-hosts-reference` | Direct add-on |
| `packages/framework-packs/integrations/stores-file` | `weavert-stores-file` | `weavert_stores_file` | `weavert-stores-file` | Direct add-on |
| `packages/framework-packs/workflows/planning` | `weavert-planning` | `weavert_planning` | `weavert-planning` | Direct add-on |
| `packages/framework-packs/workflows/devtools` | `weavert-devtools` | `weavert_devtools` | `weavert-devtools` | Direct add-on |
| `packages/framework-packs/workflows/builtin-workflows` | `weavert-builtin-workflows` | `weavert_builtin_workflows` | `weavert-builtin-workflows` | Direct add-on |

Framework-pack runtime activation names intentionally match the public install names. The identity layers are still separate even when the string is the same.

### Common kits

| Package root | PyPI distribution | Import root | Runtime activation | Exposure tier |
| --- | --- | --- | --- | --- |
| `packages/product-kits/common/retrieval` | `weavert-kit-common-retrieval` | `weavert_kit_common_retrieval` | `weavert-shared-retrieval` | Lower-layer shared kit |
| `packages/product-kits/common/web` | `weavert-kit-common-web` | `weavert_kit_common_web` | `weavert-bridge-web` | Lower-layer shared kit |
| `packages/product-kits/common/git` | `weavert-kit-common-git` | `weavert_kit_common_git` | `weavert-shared-git` | Lower-layer shared kit |
| `packages/product-kits/common/workspace-intelligence` | `weavert-kit-common-workspace-intelligence` | `weavert_kit_common_workspace_intelligence` | `weavert-shared-workspace-intelligence` | Lower-layer shared kit |
| `packages/product-kits/common/browser` | `weavert-kit-common-browser` | `weavert_kit_common_browser` | `weavert-bridge-browser` | Lower-layer shared kit |
| `packages/product-kits/common/local-os` | `weavert-kit-common-local-os` | `weavert_kit_common_local_os` | `weavert-bridge-local-os` | Lower-layer shared kit |
| `packages/product-kits/common/pim` | `weavert-kit-common-pim` | `weavert_kit_common_pim` | `weavert-bridge-pim` | Lower-layer shared kit |

### Scenario kits

| Package root | PyPI distribution | Import root | Runtime activation | Exposure tier |
| --- | --- | --- | --- | --- |
| `packages/product-kits/chat` | `weavert-kit-chat` | `weavert_kit_chat` | `weavert-scenario-chat` | Higher-layer profile entrypoint |
| `packages/product-kits/coding` | `weavert-kit-coding` | `weavert_kit_coding` | `weavert-scenario-coding` | Higher-layer profile entrypoint |
| `packages/product-kits/local-assistant` | `weavert-kit-local-assistant` | `weavert_kit_local_assistant` | `weavert-scenario-local-assistant` | Higher-layer profile entrypoint |

### Toolchain packages

| Package root | PyPI distribution | Import root | Runtime activation | Exposure tier |
| --- | --- | --- | --- | --- |
| `packages/toolchain/starter` | `weavert-starter` | `weavert_starter` | none | Developer entrypoint |
| `packages/toolchain/testing` | `weavert-testing` | `weavert_testing` | none | Developer entrypoint |

## Repository-bound maintainer utilities

| Package root | Local install name | Import or script surface | Runtime activation | Exposure tier |
| --- | --- | --- | --- | --- |
| `packages/toolchain/scripts` | `weavert-toolchain-scripts` | `check_workspace_layout`, `openai_responses_live_smoke`, or direct script paths | none | Workspace-owned maintainer utility outside the public PyPI train |

## Shared metadata baseline

Every public package under `packages/` must satisfy the same baseline before the first upload:

- `readme = "README.md"`
- `license = "Apache-2.0"`
- `authors = [{ name = "WeaveRT Maintainers" }]`
- project URLs for homepage, documentation, repository, and issues
- shared release classifiers for alpha-stage Python developer tooling
- package-family keywords that still include the `weavert` umbrella identity
- bounded first-party dependency ranges aligned to the first release train: `>=0.1.0,<0.2.0`

The baseline is intentionally uniform so maintainers can audit the public package set with one checklist instead of a different convention for each package.
Repository-bound maintainer utilities should still keep package-local metadata and bounded first-party dependency ranges for any first-party imports they expose at import time.

## First-release validation flow

### 1. Prepare an isolated maintainer environment

```bash
python3 -m venv .venv-release
source .venv-release/bin/activate
python -m pip install --upgrade pip build twine
```

### 2. Build and metadata-check every public package

Run the build from each public package directory, not from the repository root:

```bash
rg --files packages -g 'pyproject.toml' | while read -r manifest; do
  [ "$manifest" = "packages/toolchain/scripts/pyproject.toml" ] && continue
  pkg_dir=$(dirname "$manifest")
  (
    set -e
    cd "$pkg_dir"
    find . -maxdepth 1 -mindepth 1 \( -name dist -o -name build -o -name '*.egg-info' \) -exec rm -rf {} +
    python -m build --sdist --wheel
    python -m twine check dist/*
  )
done
```

This loop is the canonical proof that the release process targets the concrete package matrix directly and does not depend on publishing the root workspace coordinator.

### 3. Smoke-install public packages in a clean environment

Create a second empty environment and install only the public package artifacts from locally built wheels or from TestPyPI.

Smoke checks must cover:

- `weavert` import and a minimal runtime boot path
- one import per framework-pack family
- one import per common-kit and scenario-kit package
- `weavert-starter --help`
- `import weavert_testing`

Do not add `weavert-toolchain-scripts` to this public smoke-install matrix. Verify repository-bound maintainer utilities separately through a repo-local path.

### 4. Rehearse public uploads on TestPyPI

- Upload only the public wheel and sdist artifacts to TestPyPI first.
- Repeat the clean-environment smoke checks against TestPyPI installs for that same public package set.
- Treat production PyPI as blocked until the TestPyPI rehearsal passes for all public release waves.

### 5. Verify repository-bound maintainer utilities separately

These checks help maintainers validate repository-owned utilities, but they are not release gates for the first public PyPI train.

From a repository checkout:

```bash
python3 packages/toolchain/scripts/check_workspace_layout.py
OPENAI_API_KEY=... python3 packages/toolchain/scripts/openai_responses_live_smoke.py
```

For a repo-local maintainer install path:

```bash
python -m pip install -e packages/framework-core \
  -e packages/framework-packs/integrations/openai \
  -e packages/toolchain/scripts
python -m check_workspace_layout
python -c "import check_workspace_layout, openai_responses_live_smoke"
```

Use `OPENAI_API_KEY=... python -m openai_responses_live_smoke` only when you want the live OpenAI smoke through that local install path. Do not block the public release train on TestPyPI or PyPI publication of `weavert-toolchain-scripts`.

## Publication waves

Publish public packages in dependency-aware waves:

1. Wave 1: `weavert`
2. Wave 2: lower-layer packages that depend only on `weavert`
3. Wave 3: higher-layer scenario kits that depend on lower-layer common kits

### Wave 2 package set

- `weavert-memory`
- `weavert-team`
- `weavert-compaction`
- `weavert-isolation`
- `weavert-openai`
- `weavert-hosts-reference`
- `weavert-stores-file`
- `weavert-planning`
- `weavert-devtools`
- `weavert-builtin-workflows`
- `weavert-kit-common-retrieval`
- `weavert-kit-common-web`
- `weavert-kit-common-git`
- `weavert-kit-common-workspace-intelligence`
- `weavert-kit-common-browser`
- `weavert-kit-common-local-os`
- `weavert-kit-common-pim`
- `weavert-starter`
- `weavert-testing`

### Wave 3 package set

- `weavert-kit-chat`
- `weavert-kit-coding`
- `weavert-kit-local-assistant`

## Trusted Publishing follow-on contract

Future GitHub Actions and PyPI automation must implement this manual contract rather than inventing a second release process:

- use GitHub OIDC Trusted Publishing for both TestPyPI and PyPI
- drive publication from an explicit matrix of public concrete package roots
- run build, metadata check, and smoke-install gates before any publish step
- publish in the same dependency-aware waves documented above
- keep the root `pyproject.toml` out of the publish matrix
- keep repository-bound maintainer utilities such as `packages/toolchain/scripts` out of the TestPyPI/PyPI publish matrix

The automation can change how maintainers trigger a release, but it must not change what gets published or the order in which dependent packages become available.

## Deferred follow-on questions

- Should convenience extras or metapackages exist after the first public release?
- Should production release automation trigger from signed tags, manual dispatch, or a hybrid model?
- When should the project revisit lockstep versioning in favor of independently versioned packages?

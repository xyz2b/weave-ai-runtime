#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[3]
ROOT_PYPROJECT = ROOT / "pyproject.toml"
PUBLIC_PACKAGE_ROOTS = (
    "packages/framework-core",
    "packages/framework-packs/capabilities/memory",
    "packages/framework-packs/capabilities/team",
    "packages/framework-packs/capabilities/web-research",
    "packages/framework-packs/mechanisms/compaction",
    "packages/framework-packs/mechanisms/isolation",
    "packages/framework-packs/integrations/openai",
    "packages/framework-packs/integrations/hosts-reference",
    "packages/framework-packs/integrations/stores-file",
    "packages/framework-packs/workflows/planning",
    "packages/framework-packs/workflows/devtools",
    "packages/framework-packs/workflows/builtin-workflows",
    "packages/distributions/full",
    "packages/product-kits/common/retrieval",
    "packages/product-kits/common/web-research",
    "packages/product-kits/common/git",
    "packages/product-kits/common/workspace-intelligence",
    "packages/product-kits/common/browser",
    "packages/product-kits/common/local-os",
    "packages/product-kits/common/pim",
    "packages/toolchain/starter",
    "packages/toolchain/testing",
    "packages/product-kits/chat",
    "packages/product-kits/coding",
    "packages/product-kits/local-assistant",
)
WAVE_ROOTS = {
    "1": ("packages/framework-core",),
    "2": (
        "packages/framework-packs/capabilities/memory",
        "packages/framework-packs/capabilities/team",
        "packages/framework-packs/capabilities/web-research",
        "packages/framework-packs/mechanisms/compaction",
        "packages/framework-packs/mechanisms/isolation",
        "packages/framework-packs/integrations/openai",
        "packages/framework-packs/integrations/hosts-reference",
        "packages/framework-packs/integrations/stores-file",
        "packages/framework-packs/workflows/planning",
        "packages/framework-packs/workflows/devtools",
        "packages/framework-packs/workflows/builtin-workflows",
        "packages/distributions/full",
        "packages/product-kits/common/retrieval",
        "packages/product-kits/common/web-research",
        "packages/product-kits/common/git",
        "packages/product-kits/common/workspace-intelligence",
        "packages/product-kits/common/browser",
        "packages/product-kits/common/local-os",
        "packages/product-kits/common/pim",
        "packages/toolchain/starter",
        "packages/toolchain/testing",
    ),
    "3": (
        "packages/product-kits/chat",
        "packages/product-kits/coding",
        "packages/product-kits/local-assistant",
    ),
}
BUILD_ARTIFACT_NAMES = ("dist", "build")
UPLOAD_RETRY_DELAYS = (15, 30, 60)


@dataclass(frozen=True, slots=True)
class Package:
    root: Path
    rel_root: str
    name: str
    version: str
    wave: str

    @property
    def manifest(self) -> Path:
        return self.root / "pyproject.toml"

    @property
    def dist_dir(self) -> Path:
        return self.root / "dist"

    @property
    def display(self) -> str:
        return f"{self.name} ({self.rel_root})"


def _load_toml(path: Path) -> dict[str, object]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _workspace_concrete_roots() -> tuple[str, ...]:
    data = _load_toml(ROOT_PYPROJECT)
    workspace = data.get("tool", {}).get("weavert_workspace", {})
    roots = workspace.get("concrete_package_roots", ())
    return tuple(str(root) for root in roots)


def _build_package_catalog() -> tuple[Package, ...]:
    workspace_roots = set(_workspace_concrete_roots())
    catalog: list[Package] = []
    seen: set[str] = set()
    for wave, roots in WAVE_ROOTS.items():
        for rel_root in roots:
            if rel_root in seen:
                raise SystemExit(f"duplicate wave assignment for package root: {rel_root}")
            if rel_root not in workspace_roots:
                raise SystemExit(f"package root missing from workspace metadata: {rel_root}")
            manifest = ROOT / rel_root / "pyproject.toml"
            data = _load_toml(manifest)
            project = data.get("project", {})
            name = str(project.get("name", "")).strip()
            version = str(project.get("version", "")).strip()
            if not name or not version:
                raise SystemExit(f"invalid project metadata in {manifest}")
            catalog.append(Package(root=manifest.parent, rel_root=rel_root, name=name, version=version, wave=wave))
            seen.add(rel_root)
    if tuple(pkg.rel_root for pkg in catalog) != PUBLIC_PACKAGE_ROOTS:
        raise SystemExit("public package root order drifted from the documented publication scope")
    return tuple(catalog)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build, validate, and upload the public WeaveRT package train in "
            "documented dependency-aware waves."
        )
    )
    parser.add_argument(
        "command",
        choices=("list", "matrix", "build-check", "upload", "release"),
        help="Operation to run across the public package train.",
    )
    parser.add_argument(
        "--wave",
        action="append",
        choices=("1", "2", "3", "all"),
        help="Restrict the package selection to one or more release waves. Defaults to all public waves.",
    )
    parser.add_argument(
        "--package",
        action="append",
        help="Restrict the selection to one or more public distribution names, such as weavert or weavert-kit-coding.",
    )
    parser.add_argument(
        "--repository",
        choices=("testpypi", "pypi"),
        help="Target repository for upload or release commands.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Pass --skip-existing through to twine upload.",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Keep existing dist/build/*.egg-info artifacts before building.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Acknowledge that upload or release commands will publish artifacts to the selected repository.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the package plan and commands without mutating package directories or uploading artifacts.",
    )
    return parser.parse_args()


def _selected_waves(args: argparse.Namespace) -> tuple[str, ...]:
    waves = tuple(args.wave or ("all",))
    if "all" in waves:
        return ("1", "2", "3")
    return tuple(dict.fromkeys(waves))


def _select_packages(args: argparse.Namespace, catalog: Iterable[Package]) -> tuple[Package, ...]:
    selected_waves = set(_selected_waves(args))
    selected = [pkg for pkg in catalog if pkg.wave in selected_waves]
    if args.package:
        names = {name.strip() for name in args.package if name.strip()}
        selected = [pkg for pkg in selected if pkg.name in names]
        missing = sorted(names - {pkg.name for pkg in selected})
        if missing:
            raise SystemExit(
                "unknown or non-public package selection: " + ", ".join(missing)
            )
    if not selected:
        raise SystemExit("no packages selected")
    return tuple(selected)


def _run(
    command: list[str],
    *,
    cwd: Path,
    dry_run: bool,
) -> None:
    printable = " ".join(command)
    print(f"[cmd] ({cwd.relative_to(ROOT)}) {printable}")
    if dry_run:
        return
    subprocess.run(command, cwd=cwd, check=True)


def _run_upload(
    command: list[str],
    *,
    cwd: Path,
    dry_run: bool,
) -> None:
    printable = " ".join(command)
    print(f"[cmd] ({cwd.relative_to(ROOT)}) {printable}")
    if dry_run:
        return

    attempts = len(UPLOAD_RETRY_DELAYS) + 1
    for attempt in range(1, attempts + 1):
        completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
        if completed.stdout:
            print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
        if completed.stderr:
            print(completed.stderr, end="" if completed.stderr.endswith("\n") else "\n", file=sys.stderr)
        if completed.returncode == 0:
            return

        combined_output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
        if "429 Too Many Requests" not in combined_output or attempt == attempts:
            raise subprocess.CalledProcessError(completed.returncode, command)

        delay = UPLOAD_RETRY_DELAYS[attempt - 1]
        print(
            f"[retry] ({cwd.relative_to(ROOT)}) rate limited by repository; "
            f"retrying in {delay}s ({attempt}/{attempts})"
        )
        time.sleep(delay)


def _clean_package(package: Package, *, dry_run: bool) -> None:
    for artifact_name in BUILD_ARTIFACT_NAMES:
        artifact = package.root / artifact_name
        if artifact.exists():
            print(f"[clean] {package.display}: remove {artifact_name}/")
            if not dry_run:
                shutil.rmtree(artifact)
    for egg_info in package.root.glob("*.egg-info"):
        print(f"[clean] {package.display}: remove {egg_info.name}")
        if not dry_run:
            shutil.rmtree(egg_info)


def _require_dist(package: Package) -> None:
    if not package.dist_dir.is_dir():
        raise SystemExit(f"missing dist directory for {package.display}; run build-check first")
    files = tuple(sorted(path for path in package.dist_dir.iterdir() if path.is_file()))
    if not files:
        raise SystemExit(f"no dist artifacts found for {package.display}; run build-check first")


def _build_check(packages: Iterable[Package], *, clean: bool, dry_run: bool) -> None:
    for package in packages:
        print(f"[build-check] {package.display}")
        if clean:
            _clean_package(package, dry_run=dry_run)
        _run([sys.executable, "-m", "build", "--sdist", "--wheel"], cwd=package.root, dry_run=dry_run)
        if dry_run:
            continue
        dist_files = sorted(str(path) for path in package.dist_dir.iterdir() if path.is_file())
        _run([sys.executable, "-m", "twine", "check", *dist_files], cwd=package.root, dry_run=False)


def _upload(packages: Iterable[Package], *, repository: str, skip_existing: bool, dry_run: bool) -> None:
    for package in packages:
        print(f"[upload] {package.display} -> {repository}")
        if not dry_run:
            _require_dist(package)
        files = sorted(str(path) for path in package.dist_dir.iterdir() if path.is_file()) if package.dist_dir.exists() else [
            "dist/*"
        ]
        command = [
            sys.executable,
            "-m",
            "twine",
            "upload",
            "--disable-progress-bar",
            "--repository",
            repository,
        ]
        if skip_existing:
            command.append("--skip-existing")
        command.extend(files)
        _run_upload(command, cwd=package.root, dry_run=dry_run)


def _print_plan(packages: Iterable[Package]) -> None:
    for package in packages:
        print(f"wave {package.wave}: {package.name} {package.version} -> {package.rel_root}")


def _print_matrix(packages: Iterable[Package]) -> None:
    payload = [
        {
            "name": package.name,
            "version": package.version,
            "wave": package.wave,
            "rel_root": package.rel_root,
        }
        for package in packages
    ]
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def main() -> int:
    args = _parse_args()
    catalog = _build_package_catalog()
    packages = _select_packages(args, catalog)

    if args.command in {"upload", "release"}:
        if not args.repository:
            raise SystemExit("--repository is required for upload and release commands")
        if not args.yes and not args.dry_run:
            raise SystemExit("--yes is required for upload and release commands")

    if args.command == "list":
        _print_plan(packages)
        return 0
    if args.command == "matrix":
        _print_matrix(packages)
        return 0

    clean = not args.no_clean
    if args.command in {"build-check", "release"}:
        _build_check(packages, clean=clean, dry_run=args.dry_run)
    if args.command in {"upload", "release"}:
        _upload(packages, repository=args.repository, skip_existing=args.skip_existing, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.request import urlopen

CONSTRAINTS_PATH = Path(__file__).with_name("django-constraints.txt")
PYPI_URL = "https://pypi.org/pypi/Django/json"
STABLE_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def latest_patch(versions: list[str], major: int, minor: int) -> str:
    best_patch = None
    for version in versions:
        match = STABLE_VERSION_RE.match(version)
        if not match:
            continue
        parsed_major, parsed_minor, patch = map(int, match.groups())
        if parsed_major != major or parsed_minor != minor:
            continue
        if best_patch is None or patch > best_patch:
            best_patch = patch
    if best_patch is None:
        raise ValueError(f"No stable release found for {major}.{minor}")
    return f"{major}.{minor}.{best_patch}"


def load_constraints(path: Path) -> dict[str, str]:
    constraints: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, constraint = stripped.split("=", 1)
        constraints[key.strip()] = constraint.strip()
    return constraints


def update_constraints() -> None:
    with urlopen(PYPI_URL) as response:
        data = json.load(response)

    versions = list(data["releases"].keys())
    updated_constraints: dict[str, str] = {}

    for key, constraint in load_constraints(CONSTRAINTS_PATH).items():
        major = int(key[0])
        minor = int(key[1:])
        latest = latest_patch(versions, major, minor)
        match = re.search(r"Django>=[^,]+,(<.+)", constraint)
        if not match:
            raise ValueError(f"Unsupported constraint format: {constraint}")
        upper_bound = match.group(1)
        updated_constraints[key] = f"Django>={latest},{upper_bound}"

    lines = ["# Format: key=Django>=min_version,<max_version"]
    for key in sorted(updated_constraints, key=int):
        lines.append(f"{key}={updated_constraints[key]}")

    CONSTRAINTS_PATH.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    update_constraints()

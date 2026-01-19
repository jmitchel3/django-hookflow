#!/usr/bin/env python
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def compile_requirements(
    python_version: str,
    django_constraint: str,
    output_file: str,
) -> None:
    """Compile requirements with a Django version constraint."""
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        delete=False,
    ) as f:
        f.write(django_constraint)
        constraint_file = f.name

    try:
        subprocess.run(
            [
                "uv",
                "pip",
                "compile",
                "--quiet",
                "--generate-hashes",
                "--constraint",
                constraint_file,
                "requirements.in",
                "--python",
                python_version,
                "--output-file",
                output_file,
                *sys.argv[1:],
            ],
            check=True,
        )
    finally:
        os.unlink(constraint_file)


if __name__ == "__main__":
    os.chdir(Path(__file__).parent)

    # Python 3.10
    compile_requirements("3.10", "Django>=4.2a1,<5.0", "py310-django42.txt")
    compile_requirements("3.10", "Django>=5.0a1,<5.1", "py310-django50.txt")
    compile_requirements("3.10", "Django>=5.1a1,<5.2", "py310-django51.txt")
    compile_requirements("3.10", "Django>=5.2a1,<5.3", "py310-django52.txt")

    # Python 3.11
    compile_requirements("3.11", "Django>=4.2a1,<5.0", "py311-django42.txt")
    compile_requirements("3.11", "Django>=5.0a1,<5.1", "py311-django50.txt")
    compile_requirements("3.11", "Django>=5.1a1,<5.2", "py311-django51.txt")
    compile_requirements("3.11", "Django>=5.2a1,<5.3", "py311-django52.txt")

    # Python 3.12
    compile_requirements("3.12", "Django>=4.2a1,<5.0", "py312-django42.txt")
    compile_requirements("3.12", "Django>=5.0a1,<5.1", "py312-django50.txt")
    compile_requirements("3.12", "Django>=5.1a1,<5.2", "py312-django51.txt")
    compile_requirements("3.12", "Django>=5.2a1,<5.3", "py312-django52.txt")
    compile_requirements("3.12", "Django>=6.0a1,<6.1", "py312-django60.txt")

    # Python 3.13
    compile_requirements("3.13", "Django>=5.1a1,<5.2", "py313-django51.txt")
    compile_requirements("3.13", "Django>=5.2a1,<5.3", "py313-django52.txt")
    compile_requirements("3.13", "Django>=6.0a1,<6.1", "py313-django60.txt")

    # Python 3.14
    compile_requirements("3.14", "Django>=5.1a1,<5.2", "py314-django51.txt")
    compile_requirements("3.14", "Django>=5.2a1,<5.3", "py314-django52.txt")
    compile_requirements("3.14", "Django>=6.0a1,<6.1", "py314-django60.txt")

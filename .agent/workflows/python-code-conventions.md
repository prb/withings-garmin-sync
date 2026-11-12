---
description: Code style and conventions for Python projects.
---

This file contains coding standards and practices for use within this project.

- *Use modern Python.*  Use the latest stable version of Python3 by default.
- *Follow PEP-8.*  Use [PEP 8](https://peps.python.org/pep-0008/) formatting by default.
- *Use type hinting.*  Use [PEP 484](https://peps.python.org/pep-0484/) type hinting.
- *Use `uv`.*  Use `uv` for all dependency management purposes including Python interpreter, libraries, and execution of scripts or parts of the progam.
- *Use project-local dependencies.* 
- *Use dependency cooldowns in `uv`.*  Explicitly set the `exclude-newer` option in `tool.uv` to `P3D`.
- *Use `pytest` for tests.*  Doctests are acceptable only where necessary for good documentation.
- *Use `hypothesis` for property-based testing.*  Particularly where the specifications or code is of a declarative nature, use property-based testing to verify correctness.

- *Use `ruff` for formatting and linting.*  Format with `uv run ruff format` and lint with `uv run ruff check` (`--fix` for autofixes). The rule set and line length are configured in `pyproject.toml`.
- *Use `mypy` for type checking.*  Use the settings in `pyproject.toml`. Each Lambda is checked in its own run because they are all modules named `handler`; `scripts/check.sh` does this for you.
- *Run `scripts/check.sh` before pushing.*  It runs format check, lint, mypy and pytest, the same checks CI runs.
- *CI enforces all of them.*  The `Checks` GitHub Actions workflow must pass before merging.
- *New code passes without new ignores.*  Fix the code instead. Use a narrow, commented ignore (`# noqa: <rule>`, `# type: ignore[<code>]`, or a per-file ignore) only when unavoidable, and say why.

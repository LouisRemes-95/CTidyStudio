# AGENTS.md

## Project Context

- Repository: `LouisRemes-95/CTidyStudio`
- Purpose: build a desktop "studio" interface to load, handle, clean, and cut CT scan stacks
- Current phase: first iteration / foundation
- Current implementation: PySide6 app shell, CLI parsing, TIFF stack loading, example data
- Near-term direction: turn the current shell into a usable interactive CT scan workstation

## Current Truth From Code

- The implemented CLI is in `src/ctidystudio/cli.py`
- The UI shell is in `src/ctidystudio/studio.py`
- TIFF stack loading is in `src/ctidystudio/data_handling.py`
- `Mode` values `reset`, `resume`, and `silent` exist, but behavior is still placeholder
- `pyproject.toml` currently points the package script at `ctidystudio:main`, while `src/ctidystudio/__init__.py` only prints a hello message

## Documentation Rules

- Keep the README aligned to the actual codebase, not planned features
- Separate `implemented today` from `planned next`
- Treat CTidyStudio as a focused CT scan preparation studio
- Prefer plain, direct language over marketing copy

## Engineering Rules For Future Iterations

- Preserve the distinction between project intent and implemented behavior
- Do not claim a feature exists unless it is present in code
- If a CLI or packaging mismatch exists, document it clearly and fix it when appropriate
- Keep the workflow centered on: load scan -> inspect -> clean -> cut -> save -> export
- Prefer incremental improvements over large speculative architecture

## Practical Notes

- Example input data lives in `input_scan_example/`
- The code assumes TIFF slices and stacks them into a `(z, y, x)` NumPy volume
- Dependencies are managed with `uv`
- Python requirement is currently `>=3.13`

## README Update Intent

When rewriting the README in future iterations:

- explain what CTidyStudio is in one short paragraph
- summarize current capabilities
- show how to run the app using the entrypoint that actually works
- mention known gaps honestly
- update the roadmap to match the next concrete iteration

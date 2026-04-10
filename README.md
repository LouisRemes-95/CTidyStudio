# CTidyStudio

CTidyStudio is an early-stage desktop interface for working with CT scan stacks.

The goal of the project is to provide a practical "studio" for:

- loading CT scans from TIFF stacks
- cleaning scan data before downstream processing
- cutting or isolating regions of interest
- saving intermediate work so scans can be resumed later

This repository is the first step in that workflow context. The codebase currently contains the initial PySide6 application shell, a CLI, and TIFF stack loading.

## Current Status

Implemented today:

- Python package scaffolded with `uv`
- desktop app shell built with `PySide6`
- command-line argument parsing for input directory, output directory, mode, and voxel size
- loading a `.tif` slice stack into a 3D NumPy volume
- example CT input data in [`input_scan_example`](/workspace/input_scan_example)

Planned next:

- scan cleaning tools
- interactive cutting tools
- annotations / markers
- cached project state for `resume` and `silent` modes
- output/export pipeline

## Repository Layout

- [`src/ctidystudio/cli.py`](/workspace/src/ctidystudio/cli.py): command-line entrypoint logic
- [`src/ctidystudio/studio.py`](/workspace/src/ctidystudio/studio.py): PySide6 main window and studio runner
- [`src/ctidystudio/data_handling.py`](/workspace/src/ctidystudio/data_handling.py): TIFF stack loading and scan container
- [`input_scan_example`](/workspace/input_scan_example): example CT stack for local testing
- [`pyproject.toml`](/workspace/pyproject.toml): project metadata and dependencies

## Requirements

- Python 3.13+
- `uv`

Project dependencies currently include:

- `numpy`
- `PySide6`
- `rich`
- `tifffile`

## Setup

```bash
git clone https://github.com/LouisRemes-95/CTidyStudio.git
cd CTidyStudio
uv sync
```

## Running The App

At the moment, the implemented CLI lives in [`src/ctidystudio/cli.py`](/workspace/src/ctidystudio/cli.py). You can run it directly with:

```bash
uv run python -m ctidystudio.cli input_scan_example
```

Useful options:

```bash
uv run python -m ctidystudio.cli input_scan_example --voxel-size 1.0
uv run python -m ctidystudio.cli input_scan_example --mode reset
uv run python -m ctidystudio.cli input_scan_example --mode resume
uv run python -m ctidystudio.cli input_scan_example --mode silent
uv run python -m ctidystudio.cli input_scan_example --out ./example_output
```

Arguments:

- `input_dir`: directory containing a TIFF stack
- `--voxel-size`: voxel size used to interpret the scan volume
- `--mode`: `reset`, `resume`, or `silent`
- `--out`: output directory for generated files and future saved state

## Data Assumptions

The current loader expects:

- a directory containing `.tif` files
- one image per slice
- slices sorted by filename

The volume is assembled as a 3D NumPy array with axis order `(z, y, x)`.

## Example Workflow

```text
CT scan TIFF stack
  -> load into CTidyStudio
  -> inspect / clean
  -> cut or isolate region of interest
  -> save state
  -> export for downstream processing
```

Only the loading and window bootstrap stages are implemented today.

## Notes For Development

- The repository currently includes an outdated package-script mapping in [`pyproject.toml`](/workspace/pyproject.toml). The real CLI implementation is in [`src/ctidystudio/cli.py`](/workspace/src/ctidystudio/cli.py).
- `reset`, `resume`, and `silent` modes are defined but not yet behaviorally implemented.
- The main window is currently a starting shell for the future studio UI.

## Direction

This project is intended to grow incrementally into a focused CT scan preparation tool rather than a general-purpose medical imaging platform. The near-term objective is a usable workstation for loading, inspecting, cleaning, and cutting CT scan volumes with a workflow that can be resumed as the project evolves.

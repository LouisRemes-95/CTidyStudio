# CTidyStudio

CTidyStudio is a desktop workstation for preparing CT scan volumes stored as TIFF slice stacks. It provides a focused workflow for loading and inspecting a scan, defining a sampling domain and domain of interest (DOI), saving the working state, and exporting the resulting data for downstream processing.

Built with PySide6, CTidyStudio combines interactive slice inspection with reproducible command-line execution. It is deliberately focused on CT scan preparation rather than serving as a general-purpose medical-image viewer.

## Capabilities

CTidyStudio currently provides:

- TIFF-stack loading from a directory of `.tif` slices.
- Two interactive slice views for inspecting the loaded volume.
- Slice-position controls and optional slice-position overlays.
- Mouse-wheel zooming and right-button panning.
- 90-degree view rotations, with an option to apply the rotation to the scan.
- Sampling-domain bounds for restricting the working volume.
- Configurable unidirectional and bidirectional grid divisions.
- Domain-of-interest selection, including full-domain and seeded subdomain modes.
- Optional automatic DOI depth for unidirectional grids.
- Saved application state for resuming a previous session.
- Optional removal of small foreground objects and filling of small holes at
  export time.
- Compressed NumPy exports of the DOI voxel data and grid-line endpoints.

CTidyStudio is not a general-purpose segmentation or annotation application.
Its export cleanup is limited to binary, threshold-based removal/filling of
small voxel clusters; it does not provide manual segmentation or annotation
tools.

## Installation

This project uses **uv** for environment and dependency management. Python 3.13 or newer is required.

### Clone the repository

```bash
git clone https://github.com/LouisRemes-95/CTidyStudio.git
cd CTidyStudio
uv sync
```

## Usage

Run CTidyStudio with a directory containing a TIFF stack:

```bash
uv run ctidystudio tests/data/test_scan_50x50x50
```

The repository includes a small test stack in
[`tests/data/test_scan_50x50x50`](tests/data/test_scan_50x50x50).

### Command-line options

| Option | Description |
| --- | --- |
| `input_dir` | Required directory containing the TIFF stack. |
| `--voxel-size VALUE` | Cubic voxel size in millimetres. Default: `1.0`. |
| `-o`, `--output-dir PATH` | Directory for exported `.npz` files. |
| `--mode {reset,resume,silent}` | Controls saved-state loading and whether the GUI opens. Default: `resume`. |
| `--doi-output NAME` | Base name for the DOI voxelisation export. Default: `doi_voxelisation`. |
| `--filament-center-lines-output NAME` | Base name for the grid-line export. Default: `filament_center_lines`. |
| `--minimum-cluster-volume VALUE` | Remove foreground objects and fill background holes no larger than this physical volume in mm³ during export. Default: `0.0`. |
| `--seed-override INTEGER` | Replace the saved DOI-selection seed for this run. Must be non-negative. |

For example, run the application with a voxel size of 25 micrometres:

```bash
uv run ctidystudio tests/data/test_scan_50x50x50 --voxel-size 0.025
```

Write exports to a chosen location:

```bash
uv run ctidystudio tests/data/test_scan_50x50x50 --output-dir ./example_output
```

If no output directory is provided, CTidyStudio writes to a sibling directory named `<input_dir>_CTidyStudio_out`.

### Saved state and silent export

The application saves its UI state as `app_state.json` in the input directory after state changes. The modes behave as follows:

- `resume` (default) loads `app_state.json` when it exists, opens the GUI, and exports after the application closes.
- `reset` starts from the initial state, opens the GUI, and exports after the application closes.
- `silent` loads saved state when available and writes exports without opening the GUI. If no saved state exists, it exports the initial full-volume selection.

Start a new session without loading saved state:

```bash
uv run ctidystudio tests/data/test_scan_50x50x50 --mode reset
```

Export a previously configured DOI without opening the GUI:

```bash
uv run ctidystudio tests/data/test_scan_50x50x50 --mode silent
```

## Data model and file format

### Input stack

The loader expects a directory containing one numeric, non-complex,
two-dimensional lowercase `.tif` image per slice. All slices must have the
same dimensions. Files are sorted lexicographically by filename and assembled
into a NumPy volume with axis order `(z, y, x)`.

The loaded volume is converted to an 8-bit representation for the application display and processing workflow.

### Exports

Each normal or silent run writes compressed `.npz` files:

- `doi_voxelisation.npz` contains the selected DOI voxel volume under the `data` key. When `--minimum-cluster-volume` is positive, it has had the corresponding threshold-based small-object and small-hole cleanup applied.
- `filament_center_lines.npz` contains grid-line endpoint pairs, expressed relative to the DOI origin, under the `data` key.

Use `--doi-output` and `--filament-center-lines-output` to change the base names. CTidyStudio adds the `.npz` extension automatically.

## Workflow

CTidyStudio supports the CT-preparation stage of a larger processing pipeline:

```text
CT scan -> load -> inspect -> define sampling domain -> select DOI -> save -> export
```

The exported data can then be used by downstream cleaning, analysis, meshing, or simulation tools.

## Project structure

- [`src/ctidystudio/cli.py`](src/ctidystudio/cli.py) — command-line parsing and application configuration.
- [`src/ctidystudio/studio.py`](src/ctidystudio/studio.py) — PySide6 UI, application state, persistence, and export logic.
- [`src/ctidystudio/data_handling.py`](src/ctidystudio/data_handling.py) — TIFF loading, scan geometry, rotations, sampling-domain, grid, and DOI models.
- [`tests/data/test_scan_50x50x50`](tests/data/test_scan_50x50x50) — small example TIFF stack used by the tests.
- [`pyproject.toml`](pyproject.toml) — package metadata, dependencies, and the `ctidystudio` entry point.

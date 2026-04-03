import argparse
from pathlib import Path
from enum import Enum

from rich.console import Console

from ctidystudio.viewer import open_ctidy_studio
from ctidystudio.data_handling import load_tif_stack


class Mode(str, Enum):
    RESET = "reset"
    RESUME = "resume"
    SILENT = "silent"

def main():
    parser = argparse.ArgumentParser(
        prog = "CTidyStudio", 
        description = "Opens an interface to cut and mark an CT scan",
    )
    parser.add_argument(
        "input_dir",
        type = Path,
        help = "Path to directory containing .tif stack and optinal .json cache file",
    )
    parser.add_argument(
        "--voxel-size",
        type = float,
        default = 1.,
        help = "Voxel size (expects cubic voxel)"
    )
    parser.add_argument(
        "--mode",
        choices = [mode.value for mode in Mode],
        default = "resume",
        help=(
        "reset: start fresh in GUI; "
        "resume: load previous state in GUI; "
        "silent: apply state without opening GUI"
        ),
    )
    parser.add_argument(
        "-o",
        "--out",
        type = Path,
        default = None,
        help = "Path to the directory where outputs need to be saved"
    )

    console = Console()

    console.print("[bold]CTidyStudio[/bold]")

    args = parser.parse_args()

    input_dir = args.input_dir.resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        console.print("[red]Error: input_dir must be an existing directory[/red]")
        return

    out_dir = (args.out or input_dir + "_CTidyStudio_out").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    scan = load_tif_stack(args.input_dir, args.voxel_size)

    with console.status("[cyan]CTidy Studio interface open..."):
        open_ctidy_studio(scan)

    console.print(f"[green]✔ Scan handling complete[/green]")

    try:
        rel = out_dir.relative_to(Path.cwd())
    except ValueError:
        rel = out_dir  # fallback to absolute path
    console.print(f"Wrote to: {rel}")

if __name__ == "__main__":
    main()
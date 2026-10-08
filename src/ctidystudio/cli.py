import sys
import argparse
from pathlib import Path

from rich.traceback import install

install(show_locals=True)

from ctidystudio.common import UserError, console
from ctidystudio.studio import run_ctidy_studio, Mode, AppConfig


class RichArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        console.print(f"[bold red]✖ Argument error:[/bold red] {message}\n")
        self.print_help()
        raise SystemExit(2)


def build_parser() -> RichArgumentParser:
    parser = RichArgumentParser(
        prog="CTidyStudio",
        description="Open an interface to cut and mark a CT scan",
    )

    parser.add_argument(
        "input_dir",
        type=Path,
        help="Path to directory containing .tif stack and optional .json cache file",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Path to the directory where outputs should be saved",
    )
    parser.add_argument(
        "--doi-output",
        type=str,
        default="doi_voxelisation",
        help="Name of the DOI voxelisation output file",
    )
    parser.add_argument(
        "--filament-center-lines-output",
        type=str,
        default="filament_center_lines",
        help="Name of the filament center lines output file",
    )
    parser.add_argument(
        "--mode",
        type=Mode,
        choices=list(Mode),
        default=Mode.RESUME,
        help=(
            "reset: start fresh in GUI; "
            "resume: load previous state in GUI; "
            "silent: apply state without opening GUI"
        ),
    )
    parser.add_argument(
        "--voxel-size",
        type=float,
        default=1.0,
        help="Voxel size for cubic voxels in [mm]",
    )
    parser.add_argument(
        "--minimum-cluster-size",
        type=float,
        default=0.0,
        help="Minimum voxel cluster size when exporting [mm]",
    )
    parser.add_argument(
        "--seed-override",
        type=int,
        default=None,
        help="Overrides the random doi selection seed (must be >= 0)",
    )

    return parser


def resolve_input_dir(path: Path) -> Path:
    path = path.resolve()
    if not path.exists() or not path.is_dir():
        raise UserError("input_dir must be an existing directory")
    return path


def resolve_output_dir(input_dir: Path, out: Path | None) -> Path:
    if out is None:
        out_dir = input_dir.parent / f"{input_dir.name}_CTidyStudio_out"
    else:
        out_dir = out.resolve()

    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def main() -> int:
    parser = build_parser()

    console.print("[bold]CTidyStudio[/bold]")

    args = parser.parse_args()

    try:
        input_dir = resolve_input_dir(args.input_dir)
        output_dir = resolve_output_dir(input_dir, args.output_dir)
        app_config = AppConfig(input_dir, output_dir, args.doi_output, args.filament_center_lines_output, args.mode)

        if args.seed_override is not None and args.seed_override < 0:
            parser.error("--seed-override must be >= 0")

        return run_ctidy_studio(app_config, args.voxel_size, args.minimum_cluster_size, args.seed_override)

    except UserError as e:
        console.print(f"[bold red]✖ Error:[/bold red] {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    sys.exit(main())
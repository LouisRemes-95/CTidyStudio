import sys
import argparse
from pathlib import Path

from rich.traceback import install

install(show_locals=True)

from ctidystudio.common import UserError, console
from ctidystudio.studio import run_ctidy_studio, Mode


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
        "--voxel-size",
        type=float,
        default=1.0,
        help="Voxel size for cubic voxels in [mm]",
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
        "-o",
        "--out",
        type=Path,
        default=None,
        help="Path to the directory where outputs should be saved",
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
        output_dir = resolve_output_dir(input_dir, args.out)

        return run_ctidy_studio(input_dir, output_dir, args.mode, args.voxel_size)

    except UserError as e:
        console.print(f"[bold red]✖ Error:[/bold red] {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    sys.exit(main())
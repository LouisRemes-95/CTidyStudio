import argparse
import logging
from enum import Enum
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.traceback import install

from ctidystudio.viewer import open_ctidy_studio
from ctidystudio.data_handling import load_tif_stack


class Mode(str, Enum):
    RESET = "reset"
    RESUME = "resume"
    SILENT = "silent"


class CLIError(Exception):
    pass


console = Console()
log = logging.getLogger(__name__)


def configure_logging() -> None:
    install(show_locals=True)

    logging.basicConfig(
        level=logging.WARNING,
        format="%(message)s",
        handlers=[RichHandler()],
    )


class RichArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        console.print(f"[bold red]Argument error:[/bold red] {message}\n")
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
        help="Voxel size for cubic voxels",
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
        raise CLIError("input_dir must be an existing directory")
    return path


def resolve_output_dir(input_dir: Path, out: Path | None) -> Path:
    if out is None:
        out_dir = input_dir.parent / f"{input_dir.name}_CTidyStudio_out"
    else:
        out_dir = out.resolve()

    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def run_mode(scan, mode: Mode) -> None:
    if mode is Mode.RESET:
        with console.status("[cyan]CTidy Studio interface open..."):
            open_ctidy_studio(scan)

    elif mode is Mode.RESUME:
        # TODO: load cached JSON state here
        with console.status("[cyan]CTidy Studio interface open..."):
            open_ctidy_studio(scan)

    elif mode is Mode.SILENT:
        # TODO: apply cached JSON state without opening GUI
        log.warning("Silent mode is not implemented yet.")

    else:
        raise CLIError(f"Unsupported mode: {mode}")


def main() -> None:
    configure_logging()
    parser = build_parser()

    console.print("[bold]CTidyStudio[/bold]")

    args = parser.parse_args()

    try:
        input_dir = resolve_input_dir(args.input_dir)
        out_dir = resolve_output_dir(input_dir, args.out)

        scan = load_tif_stack(input_dir, args.voxel_size)
        run_mode(scan, args.mode)

        console.print("[green]✔ Scan handling complete[/green]")

        try:
            rel = out_dir.relative_to(Path.cwd())
        except ValueError:
            rel = out_dir

        console.print(f"Wrote to: {rel}")

    except CLIError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
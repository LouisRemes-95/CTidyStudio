import argparse
from pathlib import Path
from rich.console import Console

def main():
    parser = argparse.ArgumentParser(
        prog = "CTidyStudio", 
        description = "Opens an interface to cut and mark an CT scan",
    )
    parser.add_argument(
        "input_path",
        type = Path,
        help = "Path to directory containing .tif stack (each .tif is a consecutive slice), .xml scan info file and optinal .json cache file",
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
    out_path = args.out if args.out else args.input_path.with_suffix(".ply")

    with console.status("[cyan]Converting to .ply..."):
        convert(args.input_path, out_path)

    console.print(f"[green]✔ Converting to .ply complete[/green]")
    console.print(f"Wrote: {out_path.relative_to(Path.cwd())}")

if __name__ == "__main__":
    main()
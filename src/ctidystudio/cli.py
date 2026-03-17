import argparse
from pathlib import Path
from rich.console import Console

def main():
    parser = argparse.ArgumentParser(
        prog = "CTidyStudio", 
        description = "Opens an interface to cut and mark an CT scan",
    )
    parser.add_argument(
        "input_dir",
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

    if not args.input_dir.exists() or not args.input_dir.is_dir():
        console.print("[red]Error: input_dir must be an existing directory[/red]")
        return

    input_dir = args.input_dir.resolve()
    out_dir = (args.out or input_dir / "CTidyStudio_out").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    with console.status("[cyan]CTidy Studio interface open..."):
        pass

    console.print(f"[green]✔ Scan handling complete[/green]")

    try:
        rel = out_dir.relative_to(Path.cwd())
    except ValueError:
        rel = out_dir  # fallback to absolute path
    console.print(f"Wrote to: {rel}")

if __name__ == "__main__":
    main()
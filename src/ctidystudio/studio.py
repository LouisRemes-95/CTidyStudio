import sys
from pathlib import Path
from enum import Enum

from PySide6.QtWidgets import QApplication, QMainWindow

from ctidystudio.common import UserError, console
from ctidystudio.data_handling import load_tif_stack


class Mode(str, Enum):
    RESET = "reset"
    RESUME = "resume"
    SILENT = "silent"


class CTidyStudio(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CTidyStudio")
        self.resize(1000, 700)


def run_ctidy_studio(input_dir: Path, output_dir: Path, mode: Mode, voxel_size: float) -> int:
    with console.status("[cyan]Loading tif stack..."):
        scan = load_tif_stack(input_dir, voxel_size)
    console.print("[green]✔ Tif stack loaded[/green]")

    match mode:
        case Mode.RESET:
            pass
        case Mode.RESUME:
            pass
        case Mode.SILENT:
            pass
        case _:
            raise ValueError(f"Unknown mode: {mode}")
        
    console.print("[cyan]Opening CTidy Studio...[/cyan]")

    app = QApplication(sys.argv)
    window = CTidyStudio()
    window.show()
    exit_code = app.exec()

    console.print("[green]✔ Scan handling complete[/green]")

    return exit_code


    # TO DO:
        # try:
        #     rel = output_dir.relative_to(Path.cwd())
        # except ValueError:
        #     rel = output_dir

        # console.print(f"Wrote to: {rel}")
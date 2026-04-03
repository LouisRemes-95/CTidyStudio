import sys
from enum import Enum
from PySide6.QtWidgets import QApplication, QMainWindow

from ctidystudio.data_handling import load_tif_stack
from ctidystudio.cli import console


class Mode(str, Enum):
    RESET = "reset"
    RESUME = "resume"
    SILENT = "silent"


class CTidyStudio(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CTidyStudio")
        self.resize(1000, 700)


def run_ctidy_studio(input_dir, output_dir, mode, voxel_size):
    with console.satus("[cyan]Loading tif stack..."):
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

    console.print("[green]✔ Scan handling complete[/green]")


    app = QApplication(sys.argv)
    window = CTidyStudio()
    window.show()
    return app.exec()
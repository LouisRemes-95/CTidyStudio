import sys
from PySide6.QtWidgets import QApplication, QMainWindow
from ctidystudio.data_handling import Scan

class CTidyStudio(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CTidyStudio")
        self.resize(1000, 700)

def open_ctidy_studio(scan: Scan):
    app = QApplication(sys.argv)
    window = CTidyStudio()
    window.show()
    return app.exec()
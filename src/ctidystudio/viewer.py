import sys
from PySide6.QtWidgets import QApplication, QMainWindow

class CTidyStudio(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CTidyStudio")
        self.resize(1000, 700)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CTidyStudio()
    window.show()
    sys.exit(app.exec())
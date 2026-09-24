__all__ = ['snake_case', 'true_property']

import sys

from PySide6.QtWidgets import QApplication, QMainWindow

from pyqt_roi_editor.ui_mainwindow import Ui_MainWindow

from __feature__ import snake_case, true_property


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

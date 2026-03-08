# -*- coding: utf-8 -*-
import logging
import sys

from PySide6.QtWidgets import QApplication

from src.ui.main_window import MainWindow
from src.utils.config import TranscriberConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main():
    config = TranscriberConfig()
    app = QApplication(sys.argv)
    app.setApplicationName("Transcriptor en Tiempo Real")
    app.setStyle("Fusion")
    window = MainWindow(config=config)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

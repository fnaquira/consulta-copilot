# -*- coding: utf-8 -*-
import logging
import sys

from PySide6.QtWidgets import QApplication

from src.db.manager import DBManager
from src.ui.home_window import HomeWindow
from src.utils.config import TranscriberConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main():
    config = TranscriberConfig()
    app = QApplication(sys.argv)
    app.setApplicationName("Copiloto Psicológico")
    app.setStyle("Fusion")

    db = DBManager(db_path=config.db_path or None)
    db.init_db()

    window = HomeWindow(db=db, config=config)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

"""Application entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.data.catalog import default_data_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Explore SearchLight spectral combinations.")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=default_data_root(),
        help="Folder containing fluorophores/, filters/, and light_sources/ CSV folders.",
    )
    parser.add_argument("--download-root", type=Path, dest="data_root", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        from PySide6.QtWidgets import QApplication
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "PySide6 is not installed. Run `pip install -r requirements.txt` first."
        ) from exc

    from app.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Dichroly")
    window = MainWindow(download_root=args.data_root)
    window.resize(1320, 900)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

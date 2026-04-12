"""Утилиты для работы с путями в упакованном и обычном режиме."""

import sys
import os
from pathlib import Path

def get_resource_path(relative_path: str) -> Path:
    """
    Получить абсолютный путь к ресурсу.
    Используется для файлов, которые зашиты ВНУТРИ EXE (UI, локали, движок).
    """
    try:
        # PyInstaller создает временную папку и сохраняет путь в _MEIPASS
        if hasattr(sys, '_MEIPASS'):
            base_path = Path(sys._MEIPASS)
        else:
            base_path = Path(__file__).parent.parent
    except Exception:
        base_path = Path(__file__).parent.parent

    return base_path / relative_path


def get_data_path(filename: str) -> Path:
    """
    Получить путь для изменяемых данных (база данных, конфиг).
    Эти файлы должны лежать РЯДОМ с EXE-файлом, а не внутри него.
    """
    if hasattr(sys, 'frozen'):
        # Если приложение запущено как скомпилированный EXE
        base_path = Path(sys.executable).parent
    else:
        # Если запущено как обычный python-скрипт
        base_path = Path(__file__).parent.parent
        
    return base_path / filename

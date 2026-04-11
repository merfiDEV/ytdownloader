import os
import py_compile
import pytest
from pathlib import Path

def get_python_files():
    """
    Находит все Python файлы в проекте для проверки синтаксиса.
    Исключает venv, .git и другие системные папки.
    """
    # Корень проекта на уровень выше папки tests
    root_path = Path(__file__).parent.parent.absolute()
    
    # Папки, которые нужно игнорировать
    exclude_dirs = {'.git', 'venv', '.pytest_cache', '__pycache__', '.assets', '.qwen', 'dist', 'build'}
    
    python_files = []
    # Рекурсивно ищем все .py файлы
    for path in root_path.rglob('*.py'):
        # Проверяем, не входит ли какая-либо часть пути в список исключений
        if any(part in exclude_dirs for part in path.parts):
            continue
        python_files.append(str(path))
    
    return python_files

# Параметризуем тест списком найденных файлов
@pytest.mark.parametrize("filepath", get_python_files())
def test_python_syntax(filepath):
    """
    Тест проверяет синтаксис конкретного Python файла с помощью py_compile.
    """
    # Получаем относительный путь для более читаемого вывода в отчетах
    try:
        project_root = Path(__file__).parent.parent.absolute()
        rel_path = os.path.relpath(filepath, start=project_root)
    except Exception:
        rel_path = filepath

    try:
        # py_compile.compile с doraise=True выбросит исключение, если есть синтаксическая ошибка
        py_compile.compile(filepath, doraise=True)
    except py_compile.PyCompileError as e:
        # Если ошибка синтаксиса, помечаем тест как проваленный с деталями ошибки
        pytest.fail(f"Ошибка синтаксиса в файле {rel_path}:\n{e}")
    except Exception as e:
        # Для прочих непредвиденных ошибок (например, проблемы с доступом к файлу)
        pytest.fail(f"Не удалось проверить файл {rel_path}: {e}")

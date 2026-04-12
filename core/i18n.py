"""Утилита перевода для Python-кода (backend)."""

import json
from pathlib import Path

_i18n_cache: dict[str, dict] = {}
LOCALES_DIR = Path(__file__).parent.parent / "locales"


def _load_locale_data(locale: str) -> dict | None:
    """Загрузить JSON-файл перевода для указанного языка."""
    if locale in _i18n_cache:
        return _i18n_cache[locale]
    locale_file = LOCALES_DIR / f"{locale}.json"
    if not locale_file.exists():
        return None
    with open(locale_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    _i18n_cache[locale] = data
    return data


def t(key: str, lang: str = "ru", params: dict | None = None) -> str:
    """Получить перевод для ключа.

    Args:
        key: Ключ в формате "section.key" (напр. "status.loading_metadata")
        lang: Код языка ("ru", "en", ...)
        params: Словарь для подстановки плейсхолдеров {name}

    Returns:
        Переведённая строка или ключ, если перевод не найден.
    """
    data = _load_locale_data(lang)
    if data is None:
        data = _load_locale_data("ru")
    if data is None:
        return key

    keys = key.split(".")
    val = data
    for k in keys:
        if isinstance(val, dict) and k in val:
            val = val[k]
        else:
            return key

    if not isinstance(val, str):
        return key

    if params:
        for name, value in params.items():
            val = val.replace(f"{{{name}}}", str(value))

    return val

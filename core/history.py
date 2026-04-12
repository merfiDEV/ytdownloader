"""Модуль для работы с историей загрузок."""

import sqlite3
import uuid
from pathlib import Path
from pydantic import BaseModel
from typing import List, Optional

from core.utils import get_data_path

# Файл БД будет там же, где config.json
DB_PATH = get_data_path("history.db")

class HistoryRecord(BaseModel):
    id: str
    url: str
    title: str
    thumbnail: str
    file_path: str
    file_size: int
    format: str
    quality: str
    status: str
    error_msg: str
    created_at: str

class HistoryManager:
    """Управляет историей загрузок через SQLite."""
    
    def __init__(self):
        self._init_db()

    def _get_conn(self):
        # Используем check_same_thread=False для работы из разных потоков
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Создать таблицу, если её нет."""
        with self._get_conn() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS downloads (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT,
                    thumbnail TEXT,
                    file_path TEXT,
                    file_size INTEGER,
                    format TEXT,
                    quality TEXT,
                    status TEXT,
                    error_msg TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()

    def add_record(
            self,
            url: str,
            title: str,
            thumbnail: str,
            file_path: str,
            file_size: int,
            format: str,
            quality: str,
            status: str,
            error_msg: str = ""
    ) -> HistoryRecord:
        """Добавить запись в историю (или обновить если есть дубликат ID, хотя генерируем новый)."""
        record_id = str(uuid.uuid4())
        with self._get_conn() as conn:
            conn.execute('''
                INSERT INTO downloads (
                    id, url, title, thumbnail, file_path, file_size, format, quality, status, error_msg
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (record_id, url, title, thumbnail, file_path, file_size, format, quality, status, error_msg))
            conn.commit()
            
            # Вернем только что созданную запись (включая сгенеренный created_at)
            cur = conn.execute("SELECT * FROM downloads WHERE id = ?", (record_id,))
            row = cur.fetchone()
            
        return HistoryRecord(**dict(row))

    def get_all(self) -> List[HistoryRecord]:
        """Получить все сохранённые записи, отсортированные по дате создания (новые сверху)."""
        with self._get_conn() as conn:
            cur = conn.execute("SELECT * FROM downloads ORDER BY created_at DESC")
            rows = cur.fetchall()
        return [HistoryRecord(**dict(row)) for row in rows]

    def delete_record(self, record_id: str) -> bool:
        """Удалить запись по ID."""
        with self._get_conn() as conn:
            cur = conn.execute("DELETE FROM downloads WHERE id = ?", (record_id,))
            conn.commit()
            return cur.rowcount > 0

    def clear_all(self):
        """Очистить всю историю."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM downloads")
            conn.commit()

# Глобальный экземпляр
history_manager = HistoryManager()

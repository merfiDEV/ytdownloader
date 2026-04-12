"""Главный файл приложения — FastAPI сервер + PyWebView."""

import asyncio
import json
import os
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.config import Settings, load_settings, save_settings, ensure_save_location
from core.downloader import download_manager, DownloadStatus
from core.history import history_manager, HistoryRecord
from core.utils import get_resource_path


# --- i18n (интернационализация) ---

_i18n_cache: dict[str, dict] = {}


def _load_locale(locale: str) -> dict | None:
    """Загрузить JSON-файл перевода для указанного языка."""
    if locale in _i18n_cache:
        return _i18n_cache[locale]
    locale_file = get_resource_path("locales") / f"{locale}.json"
    if not locale_file.exists():
        return None
    with open(locale_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    _i18n_cache[locale] = data
    return data


# --- Модели запросов/ответов ---

class DownloadRequest(BaseModel):
    url: str


class PlaylistDownloadRequest(BaseModel):
    url: str
    selected_indices: list[int]


class SettingsRequest(BaseModel):
    settings: Settings


class TaskResponse(BaseModel):
    id: str
    url: str
    title: str
    status: str
    downloaded_bytes: int
    total_bytes: int
    progress: float
    speed: str
    eta: str
    error_message: str
    thumbnail: str = ""
    resumed: bool = False


# --- WebSocket для real-time обновлений ---

class ConnectionManager:
    """Управляет WebSocket подключениями."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, data: dict):
        message = json.dumps(data)
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                pass


manager = ConnectionManager()

# Хранилище отправленных уведомлений (чтобы не спамить)
sent_notifications: set[str] = set()


async def broadcast_progress():
    """Периодически отправляет прогресс всех активных загрузок."""
    while True:
        tasks = download_manager.get_all_tasks()

        # Всегда отправляем обновление, даже если очередь пуста
        data = {
            "type": "progress_update",
            "tasks": [t.to_dict() for t in tasks],
            "active_count": download_manager.get_active_count(),
        }
        await manager.broadcast(data)

        # Отправляем уведомления о несовпадении формата
        for task in tasks:
            if task.format_warning and task.id not in sent_notifications:
                sent_notifications.add(task.id)
                notification = {
                    "type": "notification",
                    "task_id": task.id,
                    "message": task.format_warning,
                    "title": task.title,
                }
                await manager.broadcast(notification)
        await asyncio.sleep(0.5)


# --- Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Запуск фоновых задач при старте приложения."""
    ensure_save_location()
    task = asyncio.create_task(broadcast_progress())
    yield
    task.cancel()


# --- Приложение ---

app = FastAPI(title="StreamVault", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- i18n API ---

@app.get("/api/i18n/{lang}")
async def get_translations(lang: str):
    """Отдать переводы для указанного языка."""
    data = _load_locale(lang)
    if data is None:
        return JSONResponse(status_code=404, content={"error": "Locale not found"})
    return data


# --- API Endpoints ---

@app.post("/api/download", response_model=TaskResponse)
async def start_download(request: DownloadRequest):
    """Начать загрузку видео по URL."""
    task = await download_manager.add_download(request.url)
    return TaskResponse(**task.to_dict())


@app.post("/api/playlist/info")
async def get_playlist_info(request: DownloadRequest):
    """Получить информацию о плейлисте."""
    info = await download_manager.get_playlist_info(request.url)
    if "error" in info:
        return {"error": info["error"]}
    return info


@app.post("/api/playlist/download")
async def download_playlist(request: PlaylistDownloadRequest):
    """Скачать выбранные видео из плейлиста."""
    # Получаем информацию о плейлисте
    info = await download_manager.get_playlist_info(request.url)
    if "error" in info or "entries" not in info:
        return {"error": "Не удалось получить информацию о плейлисте"}

    # Создаём задачи для выбранных видео
    created_tasks = []
    for entry in info["entries"]:
        if entry["index"] in request.selected_indices:
            task = await download_manager.add_download(entry["url"])
            created_tasks.append(task.to_dict())

    return {"tasks": created_tasks, "count": len(created_tasks)}


@app.post("/api/download/{task_id}/pause")
async def pause_download(task_id: str):
    """Приостановить загрузку."""
    task = download_manager.pause_download(task_id)
    if task:
        return TaskResponse(**task.to_dict())
    return {"error": "Task not found or not downloading"}


@app.post("/api/download/{task_id}/resume")
async def resume_download(task_id: str):
    """Возобновить загрузку."""
    task = await download_manager.resume_download(task_id)
    if task:
        return TaskResponse(**task.to_dict())
    return {"error": "Task not found or not paused"}


@app.post("/api/download/{task_id}/cancel")
async def cancel_download(task_id: str):
    """Отменить загрузку."""
    task = download_manager.cancel_download(task_id)
    if task:
        return TaskResponse(**task.to_dict())
    return {"error": "Task not found"}


@app.delete("/api/download/{task_id}")
async def remove_download(task_id: str):
    """Удалить задачу из очереди."""
    success = download_manager.remove_task(task_id)
    if success:
        sent_notifications.discard(task_id)
        return {"status": "removed"}
    return {"error": "Task not found"}


@app.post("/api/open-folder/{task_id}")
@app.post("/api/open-folder")
async def open_folder(task_id: str = None, request: Request = None):
    """Открыть папку с загруженным файлом в проводнике."""
    settings = load_settings()
    
    # Пытаемся достать путь из json (если передан)
    target_path = None
    try:
        if request:
            body = await request.json()
            if "path" in body and body["path"]:
                tp = Path(body["path"])
                target_path = tp if tp.is_dir() else tp.parent
    except:
        pass
        
    save_path = target_path if target_path and target_path.exists() else Path(settings.save_location)

    if not save_path.exists():
        return {"error": "Папка сохранения не найдена"}

    # Открываем папку в проводнике Windows
    try:
        os.startfile(str(save_path))
        return {"status": "opened"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/downloads", response_model=list[TaskResponse])
async def get_downloads():
    """Получить все задачи загрузки."""
    return [TaskResponse(**t.to_dict()) for t in download_manager.get_all_tasks()]


@app.get("/api/settings", response_model=Settings)
async def get_settings():
    """Получить текущие настройки."""
    return load_settings()


@app.post("/api/settings")
async def update_settings(request: SettingsRequest):
    """Обновить настройки."""
    save_settings(request.settings)
    return request.settings


@app.get("/api/status")
async def get_status():
    """Получить статус приложения."""
    return {
        "active_downloads": download_manager.get_active_count(),
        "total_tasks": len(download_manager.tasks),
    }


@app.get("/api/storage")
async def get_storage_info():
    """Получить информацию об использовании хранилища."""
    settings = load_settings()
    save_path = Path(settings.save_location)
    
    # Считаем размер файлов в папке
    folder_size = 0
    file_count = 0
    
    if save_path.exists():
        for file_path in save_path.rglob("*"):
            if file_path.is_file():
                folder_size += file_path.stat().st_size
                file_count += 1
    
    # Получаем информацию о диске
    drive = save_path.anchor if save_path.exists() else str(save_path.drive) + "\\"
    if not drive:
        drive = "."
    
    try:
        total, used, free = shutil.disk_usage(drive)
    except Exception:
        total, used, free = 0, 0, 0
    
    def format_size(size_bytes):
        """Конвертировать байты в читаемый формат."""
        if size_bytes == 0: return 0, 'B'
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return round(size_bytes, 2), unit
            size_bytes /= 1024.0
        return round(size_bytes, 2), 'PB'
    
    folder_val, folder_unit = format_size(folder_size)
    free_val, free_unit = format_size(free)
    total_val, total_unit = format_size(total)
    
    return {
        "folder_size_bytes": folder_size,
        "folder_size_formatted": f"{folder_val} {folder_unit}",
        "file_count": file_count,
        "disk_free_bytes": free,
        "disk_free_formatted": f"{free_val} {free_unit}",
        "disk_total_bytes": total,
        "disk_total_formatted": f"{total_val} {total_unit}",
        "disk_used_percent": round((used / total * 100), 1) if total > 0 else 0,
        "save_location": str(save_path),
    }


# --- API History ---

@app.get("/api/history", response_model=list[HistoryRecord])
async def get_history():
    """Получить всю историю загрузок."""
    return history_manager.get_all()


@app.delete("/api/history/{record_id}")
async def remove_history_record(record_id: str):
    """Удалить запись из истории."""
    success = history_manager.delete_record(record_id)
    if success:
        return {"status": "removed"}
    return {"error": "Record not found"}


@app.delete("/api/history")
async def clear_history():
    """Очистить всю историю."""
    history_manager.clear_all()
    return {"status": "cleared"}


# --- WebSocket ---

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint для real-time обновлений."""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# --- Статика и UI ---

UI_DIR = get_resource_path("ui")


@app.get("/")
async def index():
    """Главная страница."""
    return FileResponse(UI_DIR / "index.html")


@app.get("/settings")
async def settings_page():
    """Страница настроек."""
    return FileResponse(UI_DIR / "settings.html")


@app.get("/history")
async def history_page():
    """Страница истории."""
    return FileResponse(UI_DIR / "history.html")


app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")


# --- Запуск ---

def run_server():
    """Запустить uvicorn сервер."""
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


def run_desktop():
    """Запустить приложение в десктопном окне через pywebview."""
    import threading
    import webview

    class WebViewAPI:
        """API для взаимодействия JavaScript с Python."""
        
        def close(self):
            """Закрыть приложение."""
            for window in webview.windows:
                window.destroy()

    # Запускаем сервер в отдельном потоке
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Ждём пока сервер запустится
    import time
    time.sleep(1)

    # Создаём окно в полноэкранном режиме без рамок
    window = webview.create_window(
        'StreamVault',
        'http://127.0.0.1:8765',
        fullscreen=True,
        frameless=True,
        js_api=WebViewAPI(),
    )

    # Запускаем pywebview
    webview.start(debug=False)


if __name__ == "__main__":
    import sys
    if '--web' in sys.argv:
        # Запуск только сервера (для доступа через браузер)
        run_server()
    else:
        # Запуск в десктопном окне
        run_desktop()

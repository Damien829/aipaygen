"""Agent file storage — upload, retrieve, and manage files with SQLite metadata."""
import re
import sqlite3
import uuid
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "file_storage.db")
FILES_DIR = os.path.join(os.path.dirname(__file__), "uploads")
MAX_FILE_SIZE = 10 * 1024 * 1024   # 10 MB per file
MAX_TOTAL_MB = 500                  # 500 MB total storage


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_files_db():
    os.makedirs(FILES_DIR, exist_ok=True)
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS files (
                file_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                content_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                path TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_files_agent ON files(agent_id)")


def save_file(agent_id: str, filename: str, content_type: str,
              data: bytes) -> dict:
    """Save file bytes to disk, record metadata. Returns file_id and URL."""
    if len(data) > MAX_FILE_SIZE:
        raise ValueError(f"File too large (max {MAX_FILE_SIZE // 1024 // 1024}MB)")
    file_id = str(uuid.uuid4())
    # Sanitize filename to prevent path traversal
    filename = re.sub(r'[/\\:\r\n\x00-\x1f]', '_', os.path.basename(filename))
    ext = os.path.splitext(filename)[1] or ""
    ext = re.sub(r'[^a-zA-Z0-9.]', '', ext)[:10]
    disk_name = f"{file_id}{ext}"
    path = os.path.join(FILES_DIR, disk_name)
    # Verify path stays within uploads dir
    if not os.path.realpath(path).startswith(os.path.realpath(FILES_DIR)):
        raise ValueError("Invalid filename")
    with open(path, "wb") as f:
        f.write(data)
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO files (file_id, agent_id, filename, content_type, size_bytes, path, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (file_id, agent_id, filename, content_type, len(data), path, now),
        )
    return {
        "file_id": file_id,
        "filename": filename,
        "size_bytes": len(data),
        "url": f"https://api.aipaygen.com/files/{file_id}",
        "created_at": now,
    }


def get_file(file_id: str) -> tuple[dict, bytes] | tuple[None, None]:
    """Returns (metadata_dict, bytes) or (None, None) if not found."""
    with _conn() as c:
        row = c.execute("SELECT * FROM files WHERE file_id=?", (file_id,)).fetchone()
    if not row:
        return None, None
    meta = dict(row)
    with open(meta["path"], "rb") as f:
        data = f.read()
    return meta, data


def delete_file(file_id: str, agent_id: str) -> bool:
    """Delete file if owned by agent_id."""
    with _conn() as c:
        row = c.execute("SELECT * FROM files WHERE file_id=? AND agent_id=?",
                        (file_id, agent_id)).fetchone()
    if not row:
        return False
    try:
        os.remove(row["path"])
    except FileNotFoundError:
        pass
    with _conn() as c:
        c.execute("DELETE FROM files WHERE file_id=?", (file_id,))
    return True


def list_files(agent_id: str) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT file_id, filename, content_type, size_bytes, created_at "
            "FROM files WHERE agent_id=? ORDER BY created_at DESC LIMIT 100",
            (agent_id,)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["url"] = f"https://api.aipaygen.com/files/{d['file_id']}"
        result.append(d)
    return result


def storage_stats() -> dict:
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) as total_files, SUM(size_bytes) as total_bytes FROM files"
        ).fetchone()
    total_bytes = row["total_bytes"] or 0
    return {
        "total_files": row["total_files"],
        "total_mb": round(total_bytes / 1024 / 1024, 2),
        "max_mb": MAX_TOTAL_MB,
    }

"""SQLite 连接管理:单文件 data/app.db,WAL 模式。

线程模型:每个函数调用独立连接(用完即关),天然线程安全——
后台摄取线程与 HTTP 请求线程并发写库,互不阻塞、无连接竞争。
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from backend.core import config
from backend.db.schema import SCHEMA_SQL


def db_path() -> Path:
    """动态读 config.DATA_DIR:测试 monkeypatch 路径时自动跟随。"""
    return config.DATA_DIR / "app.db"


def get_conn() -> sqlite3.Connection:
    """打开连接(自动建表)。调用方必须关闭;一般用 connect() 上下文。"""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # 读写不互斥,适合后台写 + 前端读
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_schema(conn)
    return conn


@contextmanager
def connect() -> sqlite3.Connection:
    """事务性连接上下文:退出时提交、异常时回滚、总是关闭连接。

    注意:同一 with 块内不要再用 get_conn() 开第二条连接读刚写的数据
    (事务未提交,别的连接看不到)——要读就在 with 退出后再读。
    """
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_schema(conn: sqlite3.Connection) -> None:
    """建表(幂等,CREATE TABLE IF NOT EXISTS)。"""
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def init_db() -> None:
    """应用启动时调用:确保 data/app.db 存在。"""
    conn = get_conn()
    conn.close()


def reset_db() -> None:
    """清空全部业务表(仅测试用)。"""
    with connect() as conn:
        conn.executescript(
            """
            DELETE FROM messages;
            DELETE FROM sessions;
            DELETE FROM document_acl;
            DELETE FROM documents;
            DELETE FROM ingestion_tasks;
            DELETE FROM users;
            """
        )

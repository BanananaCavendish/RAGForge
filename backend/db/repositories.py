"""数据访问层:所有 SQLite 读写都收敛在这里,路由/服务层不直接拼 SQL。

约定:用 with connect() 打开「事务性连接上下文」,退出时自动提交/回滚/关闭;
读刚写入的数据必须在 with 块退出后再开连接(事务未提交时别的连接看不到)。
"""

from datetime import datetime

from backend.db.database import connect

_ISO = lambda: datetime.now().isoformat(timespec="seconds")  # noqa: E731


# ─── 用户 ────────────────────────────────────────────────────────


def create_user(username: str, password_hash: str, role: str = "user") -> dict:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO users(username, password_hash, role, created_at) VALUES (?,?,?,?)",
            (username, password_hash, role, _ISO()),
        )
        user_id = cur.lastrowid
    return get_user_by_id(user_id)  # 事务已提交,新连接可读到


def get_user_by_username(username: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def count_users() -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


# ─── 会话 / 消息 ─────────────────────────────────────────────────


def create_session(user_id: int, title: str = "新会话", session_id: str | None = None) -> str:
    import uuid

    sid = session_id or uuid.uuid4().hex
    now = _ISO()
    with connect() as conn:
        conn.execute(
            "INSERT INTO sessions(id, user_id, title, created_at, updated_at) VALUES (?,?,?,?,?)",
            (sid, user_id, title, now, now),
        )
    return sid


def get_session(session_id: str, user_id: int | None = None) -> dict | None:
    """按用户取会话;传 user_id 时强制校验归属(别人的会话返回 None)。"""
    with connect() as conn:
        if user_id is None:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
        return dict(row) if row else None


def session_exists(session_id: str) -> bool:
    with connect() as conn:
        return conn.execute(
            "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
        ).fetchone() is not None


def list_sessions(user_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.title, s.updated_at, COUNT(m.id) AS message_count
            FROM sessions s LEFT JOIN messages m ON m.session_id = s.id
            WHERE s.user_id = ?
            GROUP BY s.id ORDER BY s.updated_at DESC
            """,
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_session(session_id: str, user_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        )
        return cur.rowcount > 0


def list_messages(session_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT role, content, created_at FROM messages "
            "WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def append_message(session_id: str, role: str, content: str) -> None:
    """写一条消息,并刷新会话的 updated_at;首条用户消息作为会话标题。"""
    now = _ISO()
    with connect() as conn:
        conn.execute(
            "INSERT INTO messages(session_id, role, content, created_at) VALUES (?,?,?,?)",
            (session_id, role, content, now),
        )
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        cnt = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
        if cnt == 1 and role == "user":
            conn.execute("UPDATE sessions SET title = ? WHERE id = ?", (content[:30], session_id))


# ─── 文档元数据 / ACL ────────────────────────────────────────────


def upsert_document(doc_id: str, filename: str, fmt: str, num_chunks: int, uploaded_by: int | None) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO documents(doc_id, filename, fmt, num_chunks, uploaded_by, created_at)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(doc_id) DO UPDATE SET
                filename=excluded.filename, fmt=excluded.fmt,
                num_chunks=excluded.num_chunks
            """,
            (doc_id, filename, fmt, num_chunks, uploaded_by, _ISO()),
        )


def get_document_meta(doc_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
        return dict(row) if row else None


def delete_document_meta(doc_id: str) -> None:
    """删文档元数据(ACL 级联删除,SQLite ON DELETE CASCADE)。"""
    with connect() as conn:
        conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))


def add_acl(doc_id: str, user_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO document_acl(doc_id, user_id) VALUES (?,?)",
            (doc_id, user_id),
        )


def remove_acl(doc_id: str, user_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM document_acl WHERE doc_id = ? AND user_id = ?", (doc_id, user_id))


def list_acl_users(doc_id: str) -> list[int]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT user_id FROM document_acl WHERE doc_id = ?", (doc_id,)
        ).fetchall()
        return [r["user_id"] for r in rows]


def allowed_doc_ids(user: dict) -> set[str] | None:
    """当前用户可访问的文档 id 集合;admin 返回 None(不过滤)。

    普通用户可见:
      - 语料库文档(uploaded_by IS NULL,脚本导入,全员共享)
      - 自己上传的(uploaded_by = user)
      - 被分享给自己的(document_acl)
    """
    if user["role"] == "admin":
        return None
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT doc_id FROM documents
            WHERE uploaded_by IS NULL OR uploaded_by = ?
               OR doc_id IN (SELECT doc_id FROM document_acl WHERE user_id = ?)
            """,
            (user["id"], user["id"]),
        ).fetchall()
        return {r["doc_id"] for r in rows}


# ─── 摄取任务(异步上传进度) ─────────────────────────────────────


def create_task(filename: str, created_by: int | None = None, status: str = "pending") -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO ingestion_tasks(filename, status, created_by, created_at) VALUES (?,?,?,?)",
            (filename, status, created_by, _ISO()),
        )
        return cur.lastrowid


def get_task(task_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM ingestion_tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None


def update_task(task_id: int, **fields) -> None:
    """动态更新任务字段,如 update_task(id, status='done', progress=100, doc_id='x')。"""
    allowed = {"status", "progress", "error", "doc_id"}
    cols = [k for k in fields if k in allowed]
    if not cols:
        return
    assignments = ", ".join(f"{c} = ?" for c in cols)
    vals = [fields[c] for c in cols] + [task_id]
    with connect() as conn:
        conn.execute(f"UPDATE ingestion_tasks SET {assignments} WHERE id = ?", vals)


def list_tasks(limit: int = 20) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM ingestion_tasks ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def sync_documents_from_manifest(manifest: dict) -> None:
    """把 manifest 里已存在但 DB 没记录的文档补为「语料库文档」(uploaded_by NULL)。

    场景:CLI 建库(scripts/build_index.py)导入的文档没有 DB 元数据;
    不同步的话普通用户 allowed_doc_ids 查不到这些文档 → 检索权限过滤会
    把他们屏蔽掉。同步后与「脚本导入 = 全员可见」的模型一致。
    """
    with connect() as conn:
        for doc_id, info in manifest.items():
            conn.execute(
                """
                INSERT OR IGNORE INTO documents(doc_id, filename, fmt, num_chunks, uploaded_by, created_at)
                VALUES (?,?,?,?,NULL,?)
                """,
                (
                    doc_id,
                    info.get("filename", doc_id),
                    info.get("fmt", ""),
                    info.get("num_chunks", 0),
                    _ISO(),
                ),
            )

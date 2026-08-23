"""建表 DDL:集中一处,数据库初始化与测试 reset 共用。

权限模型(多用户):
  documents.uploaded_by = NULL  → 语料库文档(脚本导入),所有人可见
  documents.uploaded_by = 用户  → 该用户上传的私有文档,仅上传者/admin 可见
  document_acl(doc_id, user_id) → 额外「分享」给其他用户

摄取任务:
  上传 → 落 pending 行 → 后台线程置 running/done/failed,前端轮询进度。
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,                 -- scrypt:  n$r$salt$digest
    role          TEXT NOT NULL DEFAULT 'user',  -- admin | user
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,                 -- 服务端生成 uuid
    user_id    INTEGER NOT NULL,
    title      TEXT NOT NULL DEFAULT '新会话',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);

CREATE TABLE IF NOT EXISTS documents (
    doc_id      TEXT PRIMARY KEY,                -- 与 manifest 的 doc_id 一致
    filename    TEXT NOT NULL,
    fmt         TEXT NOT NULL,
    num_chunks  INTEGER NOT NULL DEFAULT 0,
    uploaded_by INTEGER,                         -- NULL = 语料库文档,全员可见
    created_at  TEXT NOT NULL,
    FOREIGN KEY(uploaded_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS document_acl (
    doc_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    PRIMARY KEY (doc_id, user_id),
    FOREIGN KEY(doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ingestion_tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id     TEXT,
    filename   TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',  -- pending|running|done|failed
    progress   INTEGER NOT NULL DEFAULT 0,
    error      TEXT,
    created_by INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON ingestion_tasks(status);
"""

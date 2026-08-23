"""会话记忆:SQLite 持久化(重启不丢)+ 最近 N 条截断。

从内存 dict 升级到 SQLite(阶段 D/Tier1 会话持久化):
- 消息落库 data/app.db,重启后历史仍在,前端可切换会话看历史。
- 每个会话归属 user_id:同一用户的多轮上下文隔离,互不可见。

接口保持与旧版一致(history_for / append),只是 append 增加 user_id 参数。
"""

from langchain_core.messages import AIMessage, HumanMessage

from backend.core import config
from backend.db import repositories


class SessionStore:
    """SQLite 会话仓库:创建 / 读历史 / 追加 / 列表 / 删除。"""

    def create_session(self, user_id: int, title: str = "新会话") -> str:
        return repositories.create_session(user_id, title=title)

    def history_for(self, session_id: str, user_id: int | None = None) -> list:
        """返回该会话最近 N 条消息(BaseMessage),供检索链做多轮改写。

        user_id 传 None(如 CLI/评估)时不校验归属;传了就强制校验,
        别人的会话返回空历史,绝不把别人上下文喂给当前用户。
        """
        if user_id is not None and not repositories.get_session(session_id, user_id):
            return []
        rows = repositories.list_messages(session_id)[-config.HISTORY_WINDOW * 2 :]
        out = []
        for r in rows:
            out.append(
                HumanMessage(content=r["content"])
                if r["role"] == "user"
                else AIMessage(content=r["content"])
            )
        return out

    def append(self, session_id: str, user_id: int | None, user_text: str, ai_text: str) -> None:
        """追加一轮问答到该会话(自动刷新标题与 updated_at)。"""
        repositories.append_message(session_id, "user", user_text)
        repositories.append_message(session_id, "assistant", ai_text)

    def list_sessions(self, user_id: int) -> list[dict]:
        return repositories.list_sessions(user_id)

    def delete_session(self, session_id: str, user_id: int) -> bool:
        return repositories.delete_session(session_id, user_id)

    def get_session(self, session_id: str, user_id: int) -> dict | None:
        return repositories.get_session(session_id, user_id)


# 全局单例:API 与脚本共用同一个存储(内部读写 SQLite)
store = SessionStore()

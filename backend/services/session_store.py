"""会话记忆:内存 dict + 最近 N 条截断。

刻意不用 RunnableWithMessageHistory:它把记忆注入隐藏进
config={"configurable": {"session_id": ...}},不利于调试、不利于把
history 显式传给检索链、也不方便前端展示。这里自己管,可打印可讲清。

若要持久化(重启不丢),把 InMemoryChatMessageHistory 换成
langchain_community.chat_message_histories.SQLChatMessageHistory 即可。
"""

import threading
from collections import OrderedDict
from datetime import datetime

from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.messages import AIMessage, HumanMessage

from backend.core import config


class SessionStore:
    """按 session_id 存取多轮对话历史,自动截断到最近 HISTORY_WINDOW 条。"""

    def __init__(self, max_sessions: int = 128) -> None:
        self._histories: OrderedDict[str, InMemoryChatMessageHistory] = OrderedDict()
        self._max_sessions = max_sessions
        self._lock = threading.Lock()

    def history_for(self, session_id: str) -> list:
        """返回该会话最近 N 条消息(BaseMessage 列表),供检索链使用。"""
        with self._lock:
            h = self._histories.get(session_id)
            if h is None:
                return []
            messages = h.messages
            return messages[-config.HISTORY_WINDOW * 2 :]

    def append(self, session_id: str, user_text: str, ai_text: str) -> None:
        with self._lock:
            h = self._histories.get(session_id)
            if h is None:
                h = InMemoryChatMessageHistory()
                self._histories[session_id] = h
            h.add_user_message(user_text)
            h.add_ai_message(ai_text)
            self._histories.move_to_end(session_id)
            # 简单 LRU:超出的会话整体丢弃
            while len(self._histories) > self._max_sessions:
                self._histories.popitem(last=False)

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._histories.pop(session_id, None)

    def list_sessions(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "session_id": sid,
                    "messages": len(h.messages),
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                }
                for sid, h in self._histories.items()
            ]


# 全局单例:API 与脚本共用同一个记忆
store = SessionStore()

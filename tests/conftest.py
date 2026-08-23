"""pytest 全局夹具:路径隔离 + 假模型(零外网) + 测试客户端。

原则:
- 所有测试跑在临时目录,永不触碰真实 data/ 与真实 API key。
- 外部依赖全部用假实现:LLM 用 FakeListChatModel、嵌入用 FakeEmbeddings、
  DashScope 网络调用用 monkeypatch urlopen(见 test_reranker.py)。
"""

import sys
from pathlib import Path

import pytest

# 让 pytest 从任意目录运行都能 import backend
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.embeddings.fake import FakeEmbeddings
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from backend.core import config


@pytest.fixture()
def isolated_paths(tmp_path, monkeypatch):
    """把所有数据路径重定向到临时目录,测试永不触碰真实 data/。

    config 的路径常量是模块级计算值,monkeypatch 逐个覆盖;
    IndexManager 在 __init__ 里读这些常量,所以在创建 manager 前打补丁即可。
    """
    data_dir = tmp_path / "data"
    paths = {
        "DATA_DIR": data_dir,
        "CORPUS_DIR": data_dir / "corpus",
        "GOLDEN_DIR": data_dir / "golden",
        "FAISS_DIR": data_dir / "faiss",
        "REGISTRY_DIR": data_dir / "registry",
        "SESSION_DIR": data_dir / "sessions",
        "EVAL_DIR": data_dir / "eval",
        "TEXT_DIR": data_dir / "texts",
    }
    for name, path in paths.items():
        monkeypatch.setattr(config, name, path)
    monkeypatch.setattr(config, "MANIFEST_PATH", data_dir / "registry" / "manifest.json")
    return data_dir


@pytest.fixture()
def fake_embeddings(monkeypatch):
    """确定性假嵌入(FakeEmbeddings),零网络。patch 掉 IndexManager 依赖的 get_embedding。"""
    embeddings = FakeEmbeddings(size=16)
    monkeypatch.setattr(
        "backend.services.index_manager.get_embedding", lambda: embeddings
    )
    return embeddings


@pytest.fixture(autouse=True)
def _reset_settings(isolated_paths):
    """每个测试前后重置运行时设置缓存(设置是模块级单例,必须隔离)。

    依赖 isolated_paths:确保缓存基于临时目录重建,绝不读到真实 data/。
    尾部的 invalidate_singletons 清掉嵌入/LLM/重排单例,防跨测试污染。
    """
    from backend.core import settings as core_settings

    core_settings.reload_settings()
    yield
    core_settings.reload_settings()
    core_settings.invalidate_singletons()
    # 清掉限流计数,防上一个测试的请求数污染下一个
    from backend.services.rate_limit import chat_limiter

    chat_limiter.reset()


@pytest.fixture()
def test_user(isolated_paths):
    """测试用户(管理员),供 client 夹具的依赖覆盖用。"""
    from backend.db import repositories

    return repositories.create_user("tester", "hash-placeholder", role="admin")


@pytest.fixture()
def fake_env(isolated_paths, monkeypatch):
    """把 .env 默认值替换为假 key(测试断言掩码时不依赖真实密钥)。"""
    from backend.core import config as core_config
    from backend.core import settings as core_settings

    monkeypatch.setattr(core_config, "DEEPSEEK_API_KEY", "sk-deepseek-test-1234567890")
    monkeypatch.setattr(core_config, "DASHSCOPE_API_KEY", "sk-dashscope-test-1234567890")
    monkeypatch.setattr(core_config, "EMBEDDING_PROVIDER", "api")
    monkeypatch.setattr(core_config, "EMBEDDING_MODEL", "qwen3.7-text-embedding")
    monkeypatch.setattr(core_config, "RERANK_PROVIDER", "api")
    monkeypatch.setattr(core_config, "USE_RERANK", True)
    core_settings.reload_settings()
    return core_settings.load_settings()


@pytest.fixture()
def make_fake_llm():
    """工厂:按需造 FakeListChatModel(按序返回预设回答),不碰 DeepSeek。"""

    def _make(responses: list[str]) -> FakeListChatModel:
        return FakeListChatModel(responses=responses)

    return _make


@pytest.fixture()
def manager(isolated_paths, fake_embeddings):
    """基于临时目录 + 假嵌入的空 IndexManager。"""
    from backend.services.index_manager import IndexManager

    return IndexManager()


@pytest.fixture()
def wait_ingest():
    """轮询 /api/documents/tasks 直到摄取完成(上传是后台线程,必须等)。"""

    def _wait(client, headers=None, max_waits=100):
        import time

        for _ in range(max_waits):
            tasks = client.get("/api/documents/tasks", headers=headers or {}).json()["tasks"]
            if tasks and all(t["status"] in ("done", "failed") for t in tasks):
                assert tasks[0]["status"] == "done", tasks[0].get("error")
                return tasks[0]
            time.sleep(0.05)
        raise AssertionError("上传摄取超时")

    return _wait


@pytest.fixture()
def empty_service(manager, make_fake_llm):
    """空知识库的 RAGService(假 LLM,空库路径下 LLM 不会被调用)。"""
    from backend.services.rag_service import RAGService

    return RAGService(manager, llm=make_fake_llm(responses=[]))


class StubService:
    """固定回答的假 RAG 服务:验证路由接线与响应模型,不依赖真实链路。"""

    def answer(self, session_id, question, user_id=None, allowed_doc_ids=None) -> dict:
        # 复刻真实 RAGService.answer 的落库契约:回答写进会话历史
        from backend.services import session_store

        session_store.store.append(session_id, user_id, question, "测试回答[1]")
        return {
            "answer": "测试回答[1]",
            "context": "[1] (来源:test.md, 片段 0)\n内容",
            "sources": [
                {
                    "source": "test.md",
                    "chunk_index": 0,
                    "doc_id": "abcdef123456",
                    "retrieved_by": ["vector", "bm25"],
                    "rrf_score": 0.0164,
                    "text": "内容",
                }
            ],
        }

    def answer_stream(self, session_id, question, user_id=None, allowed_doc_ids=None):
        # 复刻真实 RAGService.answer_stream 的落库契约:流式回答同样写进历史
        from backend.services import session_store

        session_store.store.append(session_id, user_id, question, "测试回答[1]")
        yield {"type": "token", "text": "测试"}
        yield {
            "type": "done",
            "answer": "测试回答[1]",
            "context": "",
            "sources": [
                {
                    "source": "test.md",
                    "chunk_index": 0,
                    "doc_id": "abcdef123456",
                    "retrieved_by": ["vector", "bm25"],
                    "rrf_score": 0.0164,
                    "text": "内容",
                }
            ],
        }


@pytest.fixture()
def client(isolated_paths, manager, make_fake_llm, test_user):
    """FastAPI TestClient,依赖全部替换为假实现(空库 + Stub 服务)。

    认证:直接覆盖 get_current_user / get_admin_user 依赖,绕过 JWT——
    API 测试聚焦路由逻辑;JWT 本身在 test_auth_api 里单测。
    """
    from fastapi.testclient import TestClient

    from backend.api.deps import get_admin_user, get_current_user
    from backend.main import app
    from backend.services.rag_service import (
        get_manager as real_get_manager,
        get_service as real_get_service,
    )

    app.dependency_overrides[real_get_manager] = lambda: manager
    app.dependency_overrides[real_get_service] = lambda: StubService()
    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_admin_user] = lambda: test_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

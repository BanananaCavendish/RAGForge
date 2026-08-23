"""运行时设置层单测:env 默认 / settings.json 覆盖 / 掩码 / 索引联动。"""

import pytest

from backend.core import config, settings


def test_env_defaults(fake_env):
    s = fake_env
    assert s.llm.provider == "deepseek"
    assert s.llm.api_key == "sk-deepseek-test-1234567890"
    assert s.llm.model == "deepseek-chat"
    assert s.embedding.provider == "api"
    assert s.embedding.model == "qwen3.7-text-embedding"
    assert s.rerank.enabled is True
    assert s.rerank.provider == "api"


def test_update_is_partial_and_persists(fake_env):
    """只改提交的字段;未提交字段保持;重启后(重新加载)仍生效。"""
    settings.update_settings({"embedding": {"model": "text-embedding-v3"}})
    s = settings.load_settings()
    assert s.embedding.model == "text-embedding-v3"
    assert s.llm.model == "deepseek-chat"  # 未提交字段保留

    settings.reload_settings()  # 模拟重启
    assert settings.load_settings().embedding.model == "text-embedding-v3"


def test_api_key_empty_clears(fake_env):
    settings.update_settings({"embedding": {"api_key": ""}})
    assert settings.load_settings().embedding.api_key == ""


def test_invalid_provider_rejected(fake_env):
    with pytest.raises(ValueError):
        settings.update_settings({"embedding": {"provider": "nonsense"}})
    with pytest.raises(ValueError):
        settings.update_settings({"rerank": {"provider": "nonsense"}})


def test_mask_key():
    assert settings.mask_key("") == ""
    assert settings.mask_key("sk-abcdefghijkl") == "sk-a****ijkl"
    assert settings.mask_key("short") == "*****"


def test_to_public_never_leaks_full_key(fake_env):
    pub = settings.to_public()
    assert pub["llm"]["api_key"] == "sk-d****7890"
    assert pub["llm"]["has_key"] is True
    assert "1234567890" not in pub["llm"]["api_key"]
    # 附前端要用的选项清单
    assert pub["options"]["llm_providers"]
    assert pub["options"]["embedding_models"]["local"]


def test_needs_reindex_toggles_on_embedding_change(fake_env):
    # 无 manifest → 知识库为空,不要求重建
    assert settings.needs_reindex() is False

    # 有 manifest 但从未记录索引指纹 → 首次加载 seed 为当前配置 → 不需重建
    config.MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.MANIFEST_PATH.write_text("{}", encoding="utf-8")
    settings.reload_settings()
    assert settings.needs_reindex() is False

    # 切嵌入模型 → 指纹变 → 必须重建
    settings.update_settings({"embedding": {"model": "text-embedding-v3"}})
    assert settings.needs_reindex() is True

    # 重建完成 → 记录新指纹 → 不再要求
    settings.finish_rebuild()
    assert settings.needs_reindex() is False


def test_rebuilding_flag_and_progress(fake_env):
    assert settings.load_settings().index.rebuilding is False
    settings.begin_rebuild()
    assert settings.load_settings().index.rebuilding is True
    with pytest.raises(RuntimeError):
        settings.begin_rebuild()  # 重复触发被拒
    settings.report_rebuild_progress(8, 16)
    assert settings.load_settings().index.progress == 50
    settings.finish_rebuild()
    assert settings.load_settings().index.rebuilding is False
    assert settings.load_settings().index.progress == 100


def test_finish_rebuild_error_records(fake_env):
    config.MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.MANIFEST_PATH.write_text("{}", encoding="utf-8")
    settings.update_settings({"embedding": {"model": "text-embedding-v3"}})
    settings.finish_rebuild(error="RuntimeError: 连接超时")
    assert settings.load_settings().index.last_rebuild_error == "RuntimeError: 连接超时"
    assert settings.needs_reindex() is True  # 失败则指纹未更新,仍需重建

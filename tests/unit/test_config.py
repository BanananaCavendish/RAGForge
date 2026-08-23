"""配置加载与校验单测。"""

import pytest

from backend.core import config


def test_paths_are_absolute_paths():
    assert config.DATA_DIR.is_absolute()
    assert config.MANIFEST_PATH.is_absolute()


def test_validate_config_missing_key_raises(monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "")
    with pytest.raises(ValueError):
        config.validate_config()


def test_validate_config_placeholder_key_raises(monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "sk-your-key")
    with pytest.raises(ValueError):
        config.validate_config()


def test_validate_config_ok(monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "sk-test-real-key")
    config.validate_config()  # 不应抛异常


def test_rerank_switch_parsing():
    # USE_RERANK 是 import 时从环境读取的布尔开关
    assert isinstance(config.USE_RERANK, bool)

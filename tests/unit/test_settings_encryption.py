"""settings.json 落盘加密:磁盘无明文,内存是明文,兼容旧版明文文件。"""

import json

from backend.core import settings


def test_api_key_encrypted_at_rest(fake_env):
    settings.update_settings({"llm": {"api_key": "sk-secret-abc-12345"}})
    raw = settings.settings_file().read_text(encoding="utf-8")
    assert "enc:" in raw            # 落盘是密文
    assert "sk-secret-abc-12345" not in raw  # 磁盘绝无明文
    assert settings.load_settings().llm.api_key == "sk-secret-abc-12345"  # 内存是明文


def test_encrypted_key_survives_reload(fake_env):
    settings.update_settings({"embedding": {"api_key": "sk-hello-world-99"}})
    settings.reload_settings()  # 模拟重启 → 从磁盘解密
    assert settings.load_settings().embedding.api_key == "sk-hello-world-99"


def test_to_public_masks_after_encryption(fake_env):
    settings.update_settings({"llm": {"api_key": "sk-abcdefgh123456"}})
    pub = settings.to_public()
    assert "abcdefgh" not in pub["llm"]["api_key"]  # 掩码后绝不含明文片段


def test_legacy_plaintext_file_still_reads(fake_env):
    """兼容加密上线前写出的明文 settings.json(无 enc: 前缀)→ 原值读取。"""
    settings.settings_file().parent.mkdir(parents=True, exist_ok=True)
    settings.settings_file().write_text(
        json.dumps({"llm": {"api_key": "sk-legacy-plain-key"}}), encoding="utf-8"
    )
    settings.reload_settings()
    assert settings.load_settings().llm.api_key == "sk-legacy-plain-key"


def test_empty_key_not_encrypted(fake_env):
    settings.update_settings({"llm": {"api_key": ""}})
    data = json.loads(settings.settings_file().read_text(encoding="utf-8"))
    # 空的 key 不做无意义加密:落盘就是空串(而不是把空串包成密文)
    assert data["llm"]["api_key"] == ""

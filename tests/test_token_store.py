import json
import time
from pathlib import Path

import pytest

from api import token_store


@pytest.fixture(autouse=True)
def isolated_token_path(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(token_store, "TOKEN_PATH", tmp_path / "token.json")


class TestLoadToken:
    def test_missing_file_returns_none(self):
        assert token_store.load_token() is None

    def test_returns_token_when_expiry_well_in_future(self):
        token_store.TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        token_store.TOKEN_PATH.write_text(json.dumps({
            "access_token": "abc123",
            "expires_at": time.time() + 3600,
        }))
        assert token_store.load_token() == "abc123"

    def test_returns_none_when_within_safety_margin(self):
        # SAFETY_MARGIN=60. 만료까지 30초 남음 -> 재발급 유도.
        token_store.TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        token_store.TOKEN_PATH.write_text(json.dumps({
            "access_token": "abc123",
            "expires_at": time.time() + 30,
        }))
        assert token_store.load_token() is None

    def test_corrupted_json_returns_none(self):
        token_store.TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        token_store.TOKEN_PATH.write_text("{not valid json")
        assert token_store.load_token() is None

    def test_missing_keys_returns_none(self):
        token_store.TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        token_store.TOKEN_PATH.write_text(json.dumps({"access_token": "abc123"}))
        assert token_store.load_token() is None

    @pytest.mark.parametrize("payload", ["[]", "null", '"just a string"', "42"])
    def test_non_dict_top_level_returns_none(self, payload):
        # C-4 회귀: 최상위가 dict가 아니면 크래시하지 않고 None.
        token_store.TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        token_store.TOKEN_PATH.write_text(payload)
        assert token_store.load_token() is None

    def test_expires_at_as_non_numeric_string_returns_none(self):
        token_store.TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        token_store.TOKEN_PATH.write_text(json.dumps({
            "access_token": "abc123",
            "expires_at": "not-a-number",
        }))
        assert token_store.load_token() is None

    @pytest.mark.parametrize("bad_token", [12345, {"nested": "token"}, ["a", "list"], None, ""])
    def test_non_string_access_token_returns_none(self, bad_token):
        # access_token 값 타입이 뒤틀리면 그대로 반환하지 않고 None (호출부가
        # "Bearer {dict}" 같은 헤더를 만들지 않도록).
        token_store.TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        token_store.TOKEN_PATH.write_text(json.dumps({
            "access_token": bad_token,
            "expires_at": time.time() + 3600,
        }))
        assert token_store.load_token() is None


class TestSaveToken:
    def test_save_then_load_roundtrip(self):
        token_store.save_token("newtoken", expires_in=3600)
        assert token_store.load_token() == "newtoken"

    def test_creates_parent_directory(self, tmp_path: Path, monkeypatch):
        nested = tmp_path / "cache" / "nested"
        monkeypatch.setattr(token_store, "TOKEN_PATH", nested / "token.json")
        assert not nested.exists()
        token_store.save_token("newtoken", expires_in=3600)
        assert token_store.TOKEN_PATH.exists()

    def test_save_succeeds_even_when_chmod_fails(self, monkeypatch):
        # Windows: chmod(0o600)이 NotImplementedError/OSError를 던져도
        # 저장 자체는 성공해야 한다 (API_DESIGN §2.3 샘플, NFR-306).
        def _raise_chmod(self, mode):
            raise OSError("chmod not supported")

        monkeypatch.setattr(Path, "chmod", _raise_chmod)
        token_store.save_token("newtoken", expires_in=3600)
        assert token_store.load_token() == "newtoken"

    def test_save_does_not_raise_when_replace_fails(self, monkeypatch):
        # Windows: 다른 프로세스가 대상 파일 핸들을 열고 있으면 os.replace가
        # PermissionError를 던질 수 있다. 캐시 저장 실패가 앱을 죽이면 안 된다.
        def _raise_replace(src, dst):
            raise PermissionError("simulated: destination file in use")

        monkeypatch.setattr(token_store.os, "replace", _raise_replace)
        token_store.save_token("newtoken", expires_in=3600)  # must not raise

    def test_tmp_file_cleaned_up_after_replace_failure(self, monkeypatch):
        def _raise_replace(src, dst):
            raise PermissionError("simulated: destination file in use")

        monkeypatch.setattr(token_store.os, "replace", _raise_replace)
        token_store.save_token("newtoken", expires_in=3600)
        leftover = list(token_store.TOKEN_PATH.parent.glob("*.tmp*"))
        assert leftover == []

"""토큰 디스크 캐시 (API_DESIGN.md §2.3).

client당 유효 토큰이 1개뿐이므로(재발급 시 이전 토큰 즉시 무효화), 만료
임박 전에는 절대 재발급하지 않는다. 이 파일은 그 캐시의 읽기/쓰기만
담당한다 — 언제 재발급할지 판단하는 것은 호출자(api/toss_client.py)의
책임이다.
"""

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# streamlit run을 프로젝트 루트가 아닌 다른 CWD에서 실행해도 캐시를 찾도록
# 상대경로 대신 이 파일 위치 기준 절대경로를 쓴다.
TOKEN_PATH = Path(__file__).resolve().parent.parent / "data" / "cache" / "token.json"
SAFETY_MARGIN = 60


def load_token() -> str | None:
    """캐시된 토큰을 읽는다. 파일 없음·손상·만료 임박은 전부 None (예외 아님)."""
    try:
        d = json.loads(TOKEN_PATH.read_text())
        if not isinstance(d, dict):
            return None
        token = d.get("access_token")
        if not isinstance(token, str) or not token:
            return None
        if time.time() < float(d["expires_at"]) - SAFETY_MARGIN:
            return token
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        pass
    return None


def save_token(access_token: str, expires_in: float) -> None:
    """토큰을 디스크에 영속화한다 (A1). 임시파일+os.replace로 원자적 교체.

    Streamlit은 위젯 조작마다 스크립트를 재실행하므로 여러 프로세스가
    거의 동시에 저장을 시도할 수 있다. 직접 write_text하면 다른 프로세스가
    쓰기 도중(빈 파일)을 읽어 불필요한 재발급을 유발할 수 있다.

    저장 자체가 실패해도(Windows에서 다른 프로세스가 대상 파일을 열고
    있으면 os.replace가 PermissionError를 던질 수 있다) 예외를 밖으로
    던지지 않는다 — 캐시는 최적화이지 필수 경로가 아니며, 실패하면 다음
    호출에서 토큰이 다시 발급될 뿐이다 (NFR-201).
    """
    tmp_path = TOKEN_PATH.with_name(f"{TOKEN_PATH.name}.tmp{os.getpid()}")
    try:
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({
            "access_token": access_token,
            "expires_at": time.time() + float(expires_in),
        })
        tmp_path.write_text(payload)
        try:
            tmp_path.chmod(0o600)
        except (NotImplementedError, OSError):
            pass  # Windows: POSIX 권한 미지원. .gitignore + 단일 사용자 PC 전제로 대체
        os.replace(tmp_path, TOKEN_PATH)
    except OSError as e:
        logger.warning("토큰 캐시 저장 실패, 다음 호출에서 재발급됨: %s", type(e).__name__)
    finally:
        tmp_path.unlink(missing_ok=True)

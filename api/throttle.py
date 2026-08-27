"""헤더 기반 적응형 스로틀 (API_DESIGN.md §11.2).

토스증권 스펙은 구체적 한도 수치를 명시하지 않고 응답 헤더로만 통지한다.
하드코딩된 sleep 대신, 엔드포인트 그룹별로 응답 헤더가 알려주는 잔여
토큰을 추적해 소진 직전에 선제적으로 쉰다.
"""

import logging
import time

import httpx

logger = logging.getLogger(__name__)

# X-RateLimit-Reset은 서버가 주는 무검증 입력이다. 음수·비정상적으로 큰 값을
# 그대로 time.sleep에 넘기면 각각 ValueError·사실상 영구 정지로 이어진다.
MAX_THROTTLE_WAIT = 10.0


class AdaptiveThrottle:
    """그룹별 잔여 토큰을 추적해 소진 직전에 선제적으로 쉰다."""

    def __init__(self, min_interval: float = 0.12):
        self._remaining: dict[str, int] = {}
        self._reset: dict[str, float] = {}
        self._min_interval = min_interval
        self._last: dict[str, float] = {}

    def before(self, group: str) -> None:
        if self._remaining.get(group, 99) <= 1:
            wait = max(0.0, min(self._reset.get(group, 1.0), MAX_THROTTLE_WAIT))
            time.sleep(wait)
            # 대기했으니 이 판단을 유발한 오래된 잔여값은 무효화한다.
            # after()가 다시 갱신하기 전까지 매 호출마다 재대기하지 않도록.
            self._remaining.pop(group, None)

        now = time.monotonic()
        gap = now - self._last.get(group, 0)
        if gap < self._min_interval:
            time.sleep(self._min_interval - gap)
        self._last[group] = now

    def after(self, group: str, resp: httpx.Response) -> None:
        try:
            remaining = int(resp.headers["X-RateLimit-Remaining"])
            reset = float(resp.headers.get("X-RateLimit-Reset", 1))
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            logger.debug("스로틀 헤더 파싱 실패, 무시: %s", type(e).__name__)
            return
        self._remaining[group] = remaining
        self._reset[group] = reset

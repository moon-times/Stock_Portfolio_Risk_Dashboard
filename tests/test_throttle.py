import httpx

from api.throttle import MAX_THROTTLE_WAIT, AdaptiveThrottle


def _response(headers: dict) -> httpx.Response:
    return httpx.Response(200, headers=headers, request=httpx.Request("GET", "https://example.com"))


class TestAfterHeaderParsing:
    def test_parses_remaining_and_reset_headers(self):
        t = AdaptiveThrottle()
        t.after("STOCK", _response({"X-RateLimit-Remaining": "5", "X-RateLimit-Reset": "2.5"}))
        assert t._remaining["STOCK"] == 5
        assert t._reset["STOCK"] == 2.5

    def test_missing_headers_does_not_raise(self):
        t = AdaptiveThrottle()
        t.after("STOCK", _response({}))  # 예외 없이 무시

    def test_non_numeric_remaining_does_not_raise(self):
        t = AdaptiveThrottle()
        t.after("STOCK", _response({"X-RateLimit-Remaining": "not-a-number"}))
        assert "STOCK" not in t._remaining

    def test_partial_failure_does_not_commit_only_one_field(self):
        # remaining은 파싱되지만 reset이 깨진 경우, 상태가 반반 갱신되면
        # before()가 새 remaining 값으로 잘못 판단할 수 있다 (둘 다 커밋 또는
        # 둘 다 무시).
        t = AdaptiveThrottle()
        t.after("STOCK", _response({"X-RateLimit-Remaining": "1", "X-RateLimit-Reset": "not-a-number"}))
        assert "STOCK" not in t._remaining
        assert "STOCK" not in t._reset


class TestBeforeWaits:
    def test_waits_when_remaining_at_or_below_one(self, monkeypatch):
        t = AdaptiveThrottle()
        t.after("STOCK", _response({"X-RateLimit-Remaining": "1", "X-RateLimit-Reset": "3"}))

        slept = []
        monkeypatch.setattr("api.throttle.time.sleep", lambda s: slept.append(s))

        t.before("STOCK")
        assert 3 in slept

    def test_does_not_wait_for_reset_when_remaining_is_healthy(self, monkeypatch):
        t = AdaptiveThrottle(min_interval=0.0)
        t.after("STOCK", _response({"X-RateLimit-Remaining": "50", "X-RateLimit-Reset": "3"}))

        slept = []
        monkeypatch.setattr("api.throttle.time.sleep", lambda s: slept.append(s))

        t.before("STOCK")
        assert 3 not in slept

    def test_unknown_group_does_not_wait(self, monkeypatch):
        t = AdaptiveThrottle(min_interval=0.0)

        slept = []
        monkeypatch.setattr("api.throttle.time.sleep", lambda s: slept.append(s))

        t.before("NEVER_SEEN")
        assert slept == []

    def test_negative_reset_header_does_not_crash_and_is_clamped(self, monkeypatch):
        # 서버가 음수 X-RateLimit-Reset을 보내면 time.sleep(-5)는 ValueError다.
        t = AdaptiveThrottle(min_interval=0.0)
        t.after("STOCK", _response({"X-RateLimit-Remaining": "1", "X-RateLimit-Reset": "-5"}))

        slept = []
        monkeypatch.setattr("api.throttle.time.sleep", lambda s: slept.append(s))

        t.before("STOCK")  # must not raise
        assert all(s >= 0 for s in slept)

    def test_huge_reset_header_is_clamped_to_max_wait(self, monkeypatch):
        # 에포크 타임스탬프 같은 값이 오면 클램프 없이는 사실상 영구 정지된다.
        t = AdaptiveThrottle(min_interval=0.0)
        t.after("STOCK", _response({"X-RateLimit-Remaining": "1", "X-RateLimit-Reset": "1787654321"}))

        slept = []
        monkeypatch.setattr("api.throttle.time.sleep", lambda s: slept.append(s))

        t.before("STOCK")
        assert max(slept) <= MAX_THROTTLE_WAIT

    def test_remaining_invalidated_after_waiting_so_it_does_not_wait_every_call(self, monkeypatch):
        t = AdaptiveThrottle(min_interval=0.0)
        t.after("STOCK", _response({"X-RateLimit-Remaining": "1", "X-RateLimit-Reset": "3"}))

        slept = []
        monkeypatch.setattr("api.throttle.time.sleep", lambda s: slept.append(s))

        t.before("STOCK")
        t.before("STOCK")  # after()가 다시 호출되지 않았음

        assert slept.count(3) == 1

    def test_min_interval_enforced_between_consecutive_calls(self, monkeypatch):
        t = AdaptiveThrottle(min_interval=0.12)
        clock = {"t": 100.0}
        monkeypatch.setattr("api.throttle.time.monotonic", lambda: clock["t"])

        slept = []
        monkeypatch.setattr("api.throttle.time.sleep", lambda s: slept.append(s))

        t.before("STOCK")
        clock["t"] = 100.05  # 0.05초만 경과 (min_interval=0.12보다 작음)
        t.before("STOCK")

        assert slept and abs(slept[-1] - 0.07) < 1e-9

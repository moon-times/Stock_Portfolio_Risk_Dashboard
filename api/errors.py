"""예외 계층 + 에러코드 매핑 (TRD.md §7.1, API_DESIGN.md §12.2)."""


class DashboardError(Exception):
    """앱 전역 예외 최상위."""


class BrokerAPIError(DashboardError):
    """증권사 API 실패.

    `message`가 위치 인자인 이유: API_DESIGN.md §11.3·§12.3의 raise 예시가
    전부 `RateLimitError("메시지")`처럼 위치 인자로 메시지를 넘긴다.
    `code`는 §12.3 `_request`가 로깅·재시도 판단에 쓰는 원본 문자열이므로
    사람이 읽는 메시지와 섞이지 않도록 키워드 전용으로 분리한다.
    """

    def __init__(self, message: str = "", *, code: str | None = None):
        self.code = code
        super().__init__(message or code or "증권사 API 오류")


class AuthenticationError(BrokerAPIError):
    """토큰 발급/검증 실패."""


class AccountNotFoundError(BrokerAPIError):
    """사용 가능 계좌 없음."""


class RateLimitError(BrokerAPIError):
    """429 호출 한도 초과."""


class MaintenanceError(BrokerAPIError):
    """500 maintenance (재시도 금지)."""


class ExchangeRateError(DashboardError):
    """환율 조회 실패."""


class PriceDataError(DashboardError):
    """가격 히스토리 조회 실패."""


class InsufficientDataError(DashboardError):
    """계산에 필요한 데이터 부족."""


class AICommentaryError(DashboardError):
    """LLM 호출 실패."""


# API_DESIGN §12.2. 여기 없는 코드는 전부 일반 BrokerAPIError로 처리한다
# (스펙 명시: 클라이언트는 unknown code를 허용해야 한다).
_CODE_TO_EXCEPTION: dict[str, type[BrokerAPIError]] = {
    "invalid-token": AuthenticationError,
    "expired-token": AuthenticationError,
    "login-user-not-found": AuthenticationError,
    "account-not-found": AccountNotFoundError,
    "rate-limit-exceeded": RateLimitError,
    "maintenance": MaintenanceError,
}


def error_for_code(code: str | None, message: str = "") -> BrokerAPIError:
    """에러코드 문자열을 해당 예외 인스턴스로 변환한다. 미지의 코드도 예외 없이 처리한다.

    `code`가 문자열이 아닌 값(서버가 보낸 JSON이 뒤틀린 경우 dict/list 등)
    이어도 dict 조회에서 TypeError로 죽지 않도록 str 여부를 먼저 확인한다.
    """
    key = code if isinstance(code, str) else ""
    exc_cls = _CODE_TO_EXCEPTION.get(key, BrokerAPIError)
    return exc_cls(message, code=code)

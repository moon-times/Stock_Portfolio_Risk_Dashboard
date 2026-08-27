# 세션 상태 — 2026-08-27 (Phase 0 / Phase S / Phase 1 / Phase 2 완료, phase-inspector 검토·보정 반영)

## 이번 세션에서 한 일
- **Phase 0 (골격)**: `models/ api/ analytics/ ai/ services/ ui/ config/ data/ tests/` 디렉토리 생성, `requirements.txt`·`.gitignore`·`.env.example`·`pytest.ini` 작성. `.venv` 가상환경 생성 후 의존성 설치. 관문 0 통과
- **Phase S (실계좌 스모크, 일회성)**: 4개 엔드포인트 순차 호출. 최초 IP 화이트리스트 미등록으로 403 실패 → 사용자가 콘솔에 재등록 후 재시도하여 관문 S 통과
- **Phase 1 (`models/`, 엄격 TDD)**: `tests/test_models.py` 작성(Red 확인) → `models/holding.py` `portfolio.py` `metrics.py` `stock_meta.py` `commentary.py` 구현(Green)
- **phase-inspector 검토 1회 실행** → 발견된 이슈 중 아래 4건을 확인·수정 완료 (Red→Green 재확인). 관문 1 최종: `pytest tests/test_models.py` **17/17 통과**
- **Phase 2 (`config.py`)**: `tests/test_config.py` 작성 → `config.py`(TRD §5.3 기반, 시크릿 필드는 아래 결정에 따라 `SecretStr`로 격상) 구현. phase-inspector 검토 후 3건 수정 완료(아래 표). 관문 2 최종: `pytest tests/test_config.py` **5/5 통과**, 전체 스위트 **22/22 통과**

## phase-inspector 발견 → 수정 완료 항목
| # | 문제 | 조치 |
|---|---|---|
| C-1 | `pytest.ini`에 `pythonpath` 누락으로 문서에 적힌 그대로의 `pytest tests/test_models.py` 명령이 `ModuleNotFoundError`로 실패 (`python -m pytest`로만 우연히 통과) | `pytest.ini`에 `pythonpath = .` 추가 |
| W-3 | `Portfolio.account_no` 마스킹이 멱등하지 않음 — 이미 마스킹된 값을 캐시 등에서 재역직렬화하면 뒤 4자리까지 삭제됨(`"*******8901"` → `"****"`) | `_mask` validator에 `"*" in v` 가드 추가, 라운드트립 테스트 추가 |
| W-1 (사용자 확인) | FR-703(2~4문장, MUST) vs DATA_DESIGN 샘플코드(`min_length=1`) 충돌 → **사용자가 REQUIREMENTS 우선으로 결정** | `Commentary.sentences`를 `min_length=2`로 수정, 1문장 ValidationError 테스트 추가 |
| W-2 (사용자 확인) | `CorrelationMatrix`가 정방행렬만 검사, 대각=1.0·값범위 -1~1 미검증(DATA_DESIGN §6) → **사용자가 검증 강화로 결정** | 대각선=1.0(±1e-9), 값 범위 [-1,1] 검증 추가. 위반 테스트 2건 + 정상 케이스 테스트 1건 추가 |

### Phase 2 검토 (2회차)
| # | 문제 | 조치 |
|---|---|---|
| C-1 | `Settings(_env_file=None)`은 dotenv 파일만 막고 OS 환경변수는 그대로 읽음 → 테스트가 비결정적이고, 어서션 실패 시 `Settings(...)` repr에 시크릿 평문이 찍힐 위험 (실측: `TOSS_CLIENT_SECRET=leaked_secret pytest ...` 시 결과 뒤집힘) | `tests/test_config.py`에 `no_settings_env` fixture 추가, 관련 9개 환경변수를 `monkeypatch.delenv`로 명시 삭제. 동일 주입 시나리오로 격리 확인 완료 |
| W-1 (사용자 확인) | `toss_client_secret`/`anthropic_api_key`가 평문 `str` — TRD §5.3 샘플코드 vs 보안규칙 S4(예외 메시지에 토큰 노출 금지) 충돌 → **사용자가 SecretStr 격상으로 결정** | 두 필드를 `pydantic.SecretStr`로 변경, `has_broker_credentials`는 `.get_secret_value()`로 명시 비교. 테스트도 `.get_secret_value()` 기준으로 수정 |
| W-2 | `config/`에 `__init__.py`가 생기면 `config.py`보다 우선순위가 뒤집혀 임포트가 깨짐(지뢰). 실측 결과 현재도 `--cov=config.py`가 "No data collected" 경고만 내고 커버리지를 전혀 못 잼(코드는 정상 동작, 측정 도구만 깨짐) | `config/README.md` 신설 — `__init__.py` 추가 금지 경고 문서화. 커버리지 측정 불능 사실은 이 표에 기록(Phase 3 관문은 `--cov=analytics`라 직접 영향 없음을 확인) |
| W-4 | `has_broker_credentials`가 `False` 케이스만 검증되고 `True`·부분 자격증명(id만 있음) 경로 미검증 | `True`/부분 자격증명 테스트 2건 추가 |
| W-5 | `test_loads_without_env_file`에 어서션이 전혀 없어 "기본값 사용" 요구사항이 실질적으로 미검증 | 자격증명 기본값 어서션 추가 |

## 확정된 사실 / 결정
| 항목 | 내용 |
|---|---|
| Python 실행환경 | `python` 명령이 Windows Store 스텁이라 깨져 있음. `py -3` 사용. 프로젝트는 `.venv`(Python 3.13.3)로 격리 설치함 |
| 개발 PC 공인 IP | `211.238.109.167` (2026-08-27 콘솔 화이트리스트 등록 완료) |
| 토큰 캐시 | Phase S에서 발급한 실토큰이 `data/cache/token.json`에 저장됨 (`expires_in=86399`). Phase 6에서 재사용 가능, `.gitignore` 대상 |
| 실계좌 확인 결과 | `accountSeq=2`, `BROKERAGE` 계좌 1개, 계좌번호 마스킹 `*******5597`. `cashBuyingPower` KRW 10원(배당금 추정)/USD 0. `marketValue.amount.usd`는 `null`이 아니라 실제 문자열값(`"221.627494"`)으로 옴 — 위험 3(널 가드)은 이 계좌에서는 트리거되지 않았으나 코드에는 여전히 가드 유지 |
| `models/` 파일 범위 | 이번 Phase 1에서는 TRD.md §3 디렉토리 구조(5개 파일: `holding.py` `portfolio.py` `metrics.py` `stock_meta.py` `commentary.py`)를 따랐다. **정정**: TDD_PLAN.md T-1.2 원문은 `dashboard.py`(`DashboardData`)까지 6개를 명시하여 TRD와 충돌한다 — "범위 밖"이 아니라 **의도적 연기**다. `DashboardData`가 아직 미구현인 `AllocationBreakdown`(DATA_DESIGN §2.5)에 의존하므로, `AllocationBreakdown`이 만들어지는 Phase 3(T-3.3) 이후, 늦어도 소비처인 Phase 7(T-7.1, `services/dashboard_service.py`) 착수 전에는 반드시 생성해야 한다 |
| `CorrelationMatrix` 정방행렬 검증 | DATA_DESIGN 원문은 `assert` 사용, 구현은 `raise ValueError`로 대체 (assert는 `-O` 최적화 시 비활성화될 수 있어 견고성을 위해 변경. pydantic v2에서 둘 다 동일하게 ValidationError로 감싸짐을 phase-inspector가 확인). 대각=1.0·범위 검증도 이번에 추가됨 |
| CLAUDE.md | 사용자가 "티켓 순서" 규칙과 "3줄 요약" 규칙 2줄을 직접 지움 (커밋 안 된 로컬 수정, 이번 세션에서 손대지 않음) |
| git 커밋/푸시 | 사용자가 Phase 1부터 매 phase 종료 시 state.md 갱신 → phase-inspector 실행 → git commit & push를 명시적으로 요청함 (2026-08-27). Phase 1 커밋 후 `git push`가 auto mode 분류기에 막혀 사용자가 직접 push함. 이후 사용자가 `.claude/settings.local.json`에 `Bash(git push*)` 허용 규칙을 직접 추가(내가 그 파일을 쓰는 것조차 분류기가 막아서 사용자가 직접 처리) → **Phase 2 커밋에서 자동 push 최초 테스트 예정** |
| Phase 2 관문 명령과 실제 `.env` 상태 불일치 | TDD_PLAN 관문 2는 "`.env`가 없는 상태"를 전제로 `settings.has_broker_credentials` → `False`를 기대하지만, Phase S에서 만든 진짜 `.env`(실계좌 키)가 프로젝트에 이미 존재해 문자 그대로 실행하면 `True`가 나온다(정상 — 실 자격증명이 올바르게 인식된다는 뜻). 실제 `.env`는 건드리지 않고, 테스트와 관문 검증 모두 `Settings(_env_file=None)`으로 "env 없음" 상태를 명시적으로 재현해 검증함 |
| `config.py` / `config/` 이름 충돌 | 프로젝트 루트에 설정 모듈 `config.py`와 자산군 매핑 폴더 `config/`가 동시에 존재(TRD §3 명시). `config.py`가 없는 상태에서는 `config/`가 네임스페이스 패키지로 잡혀 `from config import Settings`가 실패했다. `config.py` 생성 후에는 CPython이 동일 디렉토리에서 일반 모듈을 네임스페이스 패키지보다 우선하므로 정상 해결됨. **위험 조건은 "Phase 3 일반"이 아니라 정확히 "`config/__init__.py` 생성" 단일 조건**(phase-inspector가 실측 검증) — `config/README.md`에 금지 경고 문서화함. `asset_class_map.yaml`만 추가하는 것은 안전 확인됨 |
| `config.py` 시크릿 타입 | `toss_client_secret`/`anthropic_api_key`를 `pydantic.SecretStr`로 격상 (TRD §5.3 샘플코드는 평문 `str`이지만 사용자가 보안 우선으로 결정, 2026-08-27). Phase 4(API 클라이언트) 구현 시 `.get_secret_value()` 호출 필요함을 유의 |

## 아직 열려있는 것 (다음 세션/Phase에서 판단)
phase-inspector가 발견했으나 이번엔 손대지 않은 항목 — 차단 사유는 아니고, 사용자 승인 후 처리 권장:
- **W-4**: `Portfolio.account_no`에 필드 대입(assignment)으로 마스킹을 우회할 수 있음 (`validate_assignment=True` 검토 필요)
- **W-5**: T-1.1의 필수 12개 테스트가 전부 "가드/예외 분기"만 검증하고 정상 성공 경로(USD 환산, 정상 손익률 계산 등)는 커버리지가 비어 있음. 회귀 방어 목적의 추가 테스트는 사용자 승인 후 진행
- **S-1**: `Portfolio.account_no`에 숫자가 0개면 빈 문자열이 조용히 통과 (`Field(min_length=1)` 검토)
- **S-5**: `RiskMetrics.risk_free_rate` 범위(`0~0.2`) 가드가 모델에 없음 — 어느 레이어가 책임질지 Phase 5 전 명확화 필요
- **(Phase 2) Red 커밋 부재**: Phase 1·2 모두 Red 시점 커밋 없이 테스트+구현을 한 커밋으로 묶어, git 이력만으로 Red→Green 순서를 검증할 수 없음(mtime 정황만 가능). **Phase 3(엄격 TDD 핵심)부터는 Red 커밋과 Green 커밋을 분리하기로 함**
- **(Phase 2) TDD_PLAN.md 관문 2 문구**: "`.env`가 없는 상태에서"라는 전제가 Phase S 실행 이후로는 이 저장소에서 영구히 성립하지 않음. 문서 자체를 고칠지는 사용자 판단 필요(코드 변경 아님)
- **(Phase 2) `.env`의 `ANTHROPIC_API_KEY`**: 아직 `sk-ant-xxxxx` 플레이스홀더 그대로. Phase 6(AI 코멘트) 착수 전 실제 키로 교체 필요

## 알려진 이슈
- 스모크 테스트 스크립트 콘솔 출력에서 한글 요약 문구가 인코딩 문제로 깨짐 (Windows 콘솔 코드페이지 이슈로 추정). 기능 결과(JSON)에는 영향 없음. 스크립트는 스크래치패드에만 존재하며 커밋 대상 아님

## 다음 시작 지점
`docs/TDD_PLAN.md` **Phase 3 (`analytics/`, ★핵심, 엄격 TDD)**부터 진행. 커버리지 ≥80% 관문.

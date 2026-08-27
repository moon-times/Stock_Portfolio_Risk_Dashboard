# config/ (자산군 매핑, Phase 3)

`asset_class_map.yaml` — 자동 분류(`analytics/classifier.py`)가 참고하는 오버라이드·ETF 하위분류 키워드 매핑 (DATA_DESIGN.md §5.2).

**이 디렉토리에 `__init__.py`를 추가하지 마세요.**

프로젝트 루트의 `config.py`(pydantic-settings 설정 로더)와 이름이 겹친다.
`__init__.py`가 없는 지금은 CPython이 동일 디렉토리에서 일반 모듈(`config.py`)을
네임스페이스 패키지(`config/`)보다 우선 해석해 정상 동작하지만, `__init__.py`를
추가하는 순간 `config/`가 정식 패키지로 승격되어 우선순위가 뒤집히고
`from config import settings`가 `ImportError`로 깨진다.

Phase 2 phase-inspector 감사에서 확인됨 (2026-08-27, `docs/state.md` 참고).

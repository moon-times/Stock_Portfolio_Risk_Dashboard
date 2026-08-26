# COMPONENT DESIGN — 모듈 및 컴포넌트 설계

| 항목 | 내용 |
|---|---|
| 문서 버전 | 2.0 (실제 API 스펙 반영) |
| 선행 문서 | `docs/TRD.md`, `docs/design/DATA_DESIGN.md`, `docs/design/API_DESIGN.md` |
| 대응 요구사항 | FR-800, NFR-400 |

---

## 1. 모듈 책임 표

| 모듈 | 책임 | 하지 않는 것 |
|---|---|---|
| `app.py` | 레이아웃 배치, 서비스 호출 1회 | 계산, API 직접 호출 |
| `config.py` | 환경변수 로드 및 검증 | 그 외 전부 |
| `models/` | 도메인 데이터 구조 정의, 검증 | 계산, I/O |
| `api/` | 외부 데이터 조회, 응답 → 모델 매핑, **문자열 숫자 → Decimal 변환**, 토큰·스로틀 관리 | 지표 계산, 화면 |
| `analytics/` | 순수 계산 | 네트워크, 파일, 전역상태 |
| `ai/` | 프롬프트 생성, LLM 호출, 폴백 | 지표 계산 |
| `services/` | 조회→계산→진단 오케스트레이션 | 화면 |
| `ui/` | 받은 모델 렌더링, 포맷팅 | 계산, I/O |

### 의존 방향 (단방향)

```
app.py → services → { api, analytics, ai } → models
  │                                             ▲
  └──────────────→ ui ─────────────────────────┘
```

**역방향 import는 금지한다.** `analytics`가 `api`를 import하거나, `ui`가 `services`를 import하면 설계 위반이다.

---

## 2. 서비스 레이어

### 2.1 `services/dashboard_service.py`

앱 전체에서 유일하게 "일을 시키는" 곳이다.

```python
class DashboardService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.broker = create_broker_client(settings)
        self.classifier = AssetClassifier.from_yaml("config/asset_class_map.yaml")

    def load(self) -> DashboardData:
        """조회 → 계산 → 진단. 어떤 단계가 실패해도 부분 결과를 반환한다.
        호출 순서는 API_DESIGN §14 시퀀스를 따른다."""
        warnings: list[str] = []

        # 1. 환율 (가장 먼저 — 이후 모든 원화 환산의 전제)
        fx_rate = self._load_fx_rate(warnings)

        # 2. 포트폴리오 (holdings + buying-power KRW/USD)
        portfolio = self._load_portfolio(fx_rate, warnings)

        # 3. 종목 메타 (1회 호출) → 자산군 분류
        meta = self._load_stock_meta(portfolio, warnings)
        portfolio = self._classify(portfolio, meta)

        # 4. 자산배분 (가격 데이터 없이도 가능 — 항상 성공)
        allocation = build_allocation(portfolio, fx_rate)

        # 5. 무위험수익률 (KR_BOND_3Y)
        rf, rf_source = self._load_risk_free_rate()

        # 6. 가격 히스토리 (스로틀 루프, 실패 가능)
        prices, excluded = self._load_prices(portfolio, fx_rate, warnings)

        # 7. 지표 (prices가 None이면 전부 None)
        metrics = self._compute_metrics(portfolio, allocation, prices,
                                        rf, rf_source, excluded, warnings)

        # 8. 상관관계 (P1)
        correlation = self._compute_correlation(portfolio, prices)

        # 9. 벤치마크 (P1)
        bench = self._load_benchmark(prices, warnings)

        # 10. AI 코멘트
        commentary = self._generate_commentary(allocation, metrics, correlation)

        return DashboardData(
            portfolio=portfolio, allocation=allocation, metrics=metrics,
            correlation=correlation, benchmark_series=bench,
            commentary=commentary,
            daily_pnl_pct=portfolio.daily_pnl_rate,
            warnings=warnings,
        )
```

> `daily_pnl_pct`는 직접 계산하지 않는다. `holdings` 응답의 `dailyProfitLoss.rate`가 이미 원화 환산 기준 일간 손익률이다 (API_DESIGN §4.2).

### 2.2 단계별 실패 격리 원칙

| 단계 | 실패 시 | 이후 단계 |
|---|---|---|
| 1 환율 | `fx_rate = None` | USD 자산을 원화 환산에서 제외 + 경고 |
| 2 포트폴리오 | 목업 폴백 | 전부 정상 진행 |
| 3 종목 메타 | `meta = {}` | `marketCountry` 축약 분류로 대체 |
| 4 자산배분 | 실패 불가 (순수 집계) | — |
| 5 무위험수익률 | 설정 기본값 + `source="fallback"` | 샤프지수에 `(기본금리)` 표기 |
| 6 가격 히스토리 | `prices = None` | 7·8·9 스킵, 지표 `N/A` |
| 7 지표 | 개별 지표만 `None` | 정상 진행 |
| 8 상관관계 | `None` | 히트맵 미표시 |
| 9 벤치마크 | `None` | 비교차트 미표시, 베타 `N/A` |
| 10 코멘트 | 규칙 기반 폴백 | 정상 표시 |

각 `_load_*` / `_compute_*` 메서드는 **자체 try/except를 갖고 `None` 또는 부분값을 반환한다.** 예외를 상위로 전파하지 않는다 (NFR-201).

### 2.3 캐싱 적용 지점

```python
@st.cache_data(ttl=300, show_spinner="계좌 정보를 불러오는 중...")
def load_dashboard(_settings: Settings, cache_key: str) -> DashboardData:
    return DashboardService(_settings).load()

# app.py 호출부
cache_key = st.session_state.get("refresh_token", "init")
data = load_dashboard(settings, cache_key)
```

- `_settings` 언더스코어 접두어: Streamlit이 해시 대상에서 제외한다 (`Settings`는 해시 불가)
- `cache_key`: 새로고침 버튼이 이 값을 바꿔 캐시를 무효화한다 (FR-804)

---

## 3. UI 컴포넌트

### 3.1 공통 규약

```python
def render_<name>(data: <Model>) -> None:
    """
    - 모델을 받아 Streamlit 위젯을 그린다
    - 반환값 없음
    - 계산 금지, I/O 금지
    - None 입력 시 안내 문구를 그리거나 조용히 반환
    """
```

### 3.2 컴포넌트 목록

목업(`docs/assets/dashboard_mockup.png`) 위에서 아래 순서로 대응한다.

| 순서 | 컴포넌트 | 파일 | 입력 | 요구사항 |
|---|---|---|---|---|
| 0 | 헤더 + 상태 배지 | `app.py` | `DashboardData` | FR-802, FR-803 |
| 1 | 메트릭 카드 4개 | `ui/metric_cards.py` | `Portfolio`, `RiskMetrics`, `float` | FR-408 |
| 2 | 자산배분 도넛 | `ui/allocation_chart.py` | `AllocationBreakdown` | FR-305, FR-306 |
| 3 | 리스크 지표 테이블 | `ui/risk_table.py` | `RiskMetrics` | FR-409, FR-407 |
| 4 | 상관관계 히트맵 | `ui/correlation_heatmap.py` | `CorrelationMatrix \| None` | FR-502~504 |
| 5 | 벤치마크 라인 차트 | `ui/benchmark_chart.py` | 시계열 dict `\| None` | FR-601~603 |
| 6 | AI 코멘트 배너 | `ui/ai_banner.py` | `Commentary \| None` | FR-706, FR-708 |

### 3.3 `ui/metric_cards.py`

```python
def render_metric_cards(
    portfolio: Portfolio,
    metrics: RiskMetrics,
    daily_pnl_pct: float | None,
) -> None:
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.metric("총 자산가치", fmt_krw(portfolio.total_value),
                  help="현금은 매수가능금액 기준입니다.")     # FR-103b
    with c2:
        st.metric("일간 손익", fmt_pct(daily_pnl_pct),
                  delta=fmt_pct(daily_pnl_pct), delta_color="inverse")
    with c3:
        suffix = "" if metrics.risk_free_source == "KR_BOND_3Y" else " (기본금리)"
        st.metric("샤프지수", fmt_num(metrics.sharpe_ratio, 2) + suffix,
                  help=f"무위험수익률 {fmt_pct(metrics.risk_free_rate, 2)}")
    with c4:
        st.metric("최대낙폭 (MDD)", fmt_pct(metrics.max_drawdown))
```

> `delta_color="inverse"`: Streamlit 기본은 상승=초록이다. 한국 시장 관행(상승=빨강)과 다르지만, 목업은 손실=빨강 규칙을 따르므로 손익 부호에 맞춰 색을 뒤집는다 (FR-805).

### 3.4 `ui/allocation_chart.py`

```python
def render_allocation_chart(allocation: AllocationBreakdown) -> None:
    if not allocation.items:
        st.info("보유 자산이 없습니다.")
        return

    fig = go.Figure(go.Pie(
        labels=[i.asset_class.value for i in allocation.items],
        values=[float(i.market_value) for i in allocation.items],
        hole=0.65,
        marker=dict(colors=SERIES_COLORS[:len(allocation.items)],
                    line=dict(color=SURFACE, width=2)),
        textinfo="none",                       # 범례로 대체
        hovertemplate="%{label}<br>%{percent}<extra></extra>",
        sort=False,                            # 이미 정렬된 순서 유지
    ))
    fig.update_layout(**DONUT_LAYOUT)
    st.plotly_chart(fig, use_container_width=True)
    _render_legend(allocation)                 # 색상칩 + 이름 + %
```

`sort=False`가 중요하다. Plotly 기본 정렬이 작동하면 `AllocationBreakdown.items`의 순서와 범례가 어긋난다.

### 3.5 `ui/risk_table.py`

```python
ROWS = [
    ("연변동성",        lambda m: fmt_pct(m.annualized_volatility)),
    ("샤프지수",        lambda m: fmt_num(m.sharpe_ratio, 2)),
    ("무위험수익률",    lambda m: fmt_pct(m.risk_free_rate, 2)),
    ("베타 (vs KOSPI)", lambda m: fmt_num(m.beta, 2)),
    ("VaR (95%, 1일)",  lambda m: fmt_pct(m.var_95)),
    ("최대낙폭 (MDD)",  lambda m: fmt_pct(m.max_drawdown)),
    ("자산군 집중도",   lambda m: fmt_num(m.hhi, 2)),
]

def render_risk_table(metrics: RiskMetrics) -> None:
    for label, getter in ROWS:
        left, right = st.columns([3, 2])
        left.markdown(f"<span class='rt-label'>{label}</span>",
                      unsafe_allow_html=True)
        right.markdown(f"<span class='rt-value'>{getter(metrics)}</span>",
                       unsafe_allow_html=True)
        st.divider()
```

`getter`가 `None`을 받으면 포맷터가 `N/A`를 반환한다 (FR-407). 지표별 조건 분기를 UI에 두지 않는다.

### 3.6 `ui/correlation_heatmap.py`

```python
def render_correlation_heatmap(corr: CorrelationMatrix | None) -> None:
    if corr is None:
        st.info("자산군이 하나뿐이라 상관관계를 계산할 수 없습니다.")  # FR-504
        return

    fig = go.Figure(go.Heatmap(
        z=corr.values, x=corr.labels, y=corr.labels,
        zmin=-1, zmax=1,
        colorscale=[[0, CORR_NEG], [0.5, CORR_MID], [1, CORR_POS]],
        text=[[f"{v:.2f}" for v in row] for row in corr.values],
        texttemplate="%{text}",                # FR-503
        showscale=False,
        xgap=3, ygap=3,
    ))
    fig.update_layout(**HEATMAP_LAYOUT)
    fig.update_yaxes(autorange="reversed")     # 좌상단이 첫 자산군
    st.plotly_chart(fig, use_container_width=True)
```

`zmin=-1, zmax=1` 고정이 중요하다. 자동 스케일이면 데이터 범위에 따라 색이 달라져서 서로 다른 포트폴리오를 비교할 수 없다.

### 3.7 `ui/benchmark_chart.py`

```python
def render_benchmark_chart(dates, series: dict | None) -> None:
    if not series:
        return                                  # P1 미완이면 조용히 스킵

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates, y=series["portfolio"], name="내 포트폴리오",
        line=dict(color=SERIES_COLORS[0], width=2),  # 실선
        fill="tozeroy", fillcolor=SERIES_FILL,
    ))
    fig.add_trace(go.Scatter(
        x=dates, y=series["benchmark"], name="KOSPI",
        line=dict(color=NEUTRAL, width=1.8, dash="dash"),  # 점선 — FR-603
    ))
    fig.update_layout(**LINE_LAYOUT)
    st.plotly_chart(fig, use_container_width=True)
```

색상만이 아니라 **실선/점선으로도 구분한다** (FR-603, NFR-503).

### 3.8 `ui/ai_banner.py`

```python
DISCLAIMER = ("이 대시보드는 학습·분석 목적의 참고 자료이며 투자 자문이 아닙니다. "
              "투자 판단과 그 결과에 대한 책임은 본인에게 있습니다.")

def render_ai_banner(commentary: Commentary | None) -> None:
    if commentary is None:
        return

    badge = "" if commentary.source == "llm" else " · 규칙 기반"   # FR-706
    body = "".join(f"<p class='ai-line'>{s}</p>"
                   for s in commentary.sentences)
    st.markdown(
        f"""<div class="ai-banner">
              <div class="ai-title">AI 진단 코멘트{badge}</div>
              {body}
              <div class="ai-disclaimer">{DISCLAIMER}</div>
            </div>""",
        unsafe_allow_html=True,
    )
```

### 3.9 `ui/theme.py`

```python
# 목업과 동일한 색상 (docs/assets/dashboard_mockup.png)
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
NEUTRAL   = "#898781"
DANGER    = "#d03b3b"
SURFACE   = "#fcfcfb"
BORDER    = "#e1e0d9"
CORR_POS  = "#2a78d6"
CORR_MID  = "#f0efec"
CORR_NEG  = "#e34948"

BASE_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Pretendard, -apple-system, sans-serif", size=12),
    margin=dict(l=8, r=8, t=8, b=8),
    showlegend=False,
)
DONUT_LAYOUT   = {**BASE_LAYOUT, "height": 220}
HEATMAP_LAYOUT = {**BASE_LAYOUT, "height": 260}
LINE_LAYOUT    = {**BASE_LAYOUT, "height": 260, "showlegend": True,
                  "legend": dict(orientation="h", y=1.1, x=0)}
```

### 3.10 포맷터 (`ui/format.py`) — FR-806

```python
def fmt_krw(v: Decimal | None) -> str:
    return "N/A" if v is None else f"₩{int(round(v)):,}"

def fmt_pct(v: float | None, digits: int = 1) -> str:
    return "N/A" if v is None else f"{v * 100:.{digits}f}%"

def fmt_num(v: float | None, digits: int = 2) -> str:
    return "N/A" if v is None else f"{v:.{digits}f}"
```

**모든 숫자는 이 세 함수를 거쳐야 화면에 나간다.** f-string 직접 포맷팅을 금지한다. 부동소수점 잔여값(`0.30000000000000004`)이 화면에 노출되는 것을 구조적으로 막는다.

---

## 4. `app.py` 골격

```python
import streamlit as st
from config import settings
from services.dashboard_service import load_dashboard
from ui import (metric_cards, allocation_chart, risk_table,
                correlation_heatmap, benchmark_chart, ai_banner)

st.set_page_config(page_title="포트폴리오 리스크 대시보드",
                   page_icon="📊", layout="wide")
st.markdown(open("ui/styles.css").read(), unsafe_allow_html=True)

# ── 헤더 ──────────────────────────────────────────
head_l, head_r = st.columns([5, 1])
head_l.title("포트폴리오 리스크 대시보드")
if head_r.button("새로고침", use_container_width=True):        # FR-804
    st.session_state["refresh_token"] = str(time.time())
    st.cache_data.clear()
    st.rerun()

# ── 데이터 로드 ───────────────────────────────────
try:
    data = load_dashboard(settings,
                          st.session_state.get("refresh_token", "init"))
except Exception:                                              # NFR-201
    st.error("대시보드를 불러오지 못했습니다. 터미널 로그를 확인해 주세요.")
    st.stop()

st.caption(f"{data.portfolio.account_no} · "
           f"{data.portfolio.as_of:%Y-%m-%d %H:%M} 기준")      # FR-802

# ── 상태 배지 ─────────────────────────────────────
if data.portfolio.is_fallback:                                 # FR-803
    st.warning(f"샘플 데이터로 표시 중입니다 "
               f"({data.portfolio.fallback_reason})")
for w in data.warnings:
    st.caption(f"⚠ {w}")

# ── 1. 메트릭 카드 ────────────────────────────────
metric_cards.render_metric_cards(data.portfolio, data.metrics,
                                 data.daily_pnl_pct)

# ── 2·3. 자산배분 + 리스크 지표 ───────────────────
left, right = st.columns(2)
with left:
    st.subheader("자산배분")
    allocation_chart.render_allocation_chart(data.allocation)
with right:
    st.subheader("리스크 지표")
    risk_table.render_risk_table(data.metrics)

# ── 4. 상관관계 ───────────────────────────────────
st.subheader("자산군 간 상관관계")
correlation_heatmap.render_correlation_heatmap(data.correlation)

# ── 5. 벤치마크 비교 ──────────────────────────────
if data.benchmark_series:
    st.subheader("포트폴리오 vs KOSPI (최근 6개월, 지수화)")
    benchmark_chart.render_benchmark_chart(data.benchmark_dates,
                                           data.benchmark_series)

# ── 6. AI 코멘트 ──────────────────────────────────
ai_banner.render_ai_banner(data.commentary)
```

`app.py`는 **80줄 내외**여야 한다. 이보다 길어지면 로직이 새어 들어온 것이므로 `services/` 또는 `ui/`로 옮긴다.

---

## 5. 자산 분류기 (`analytics/classifier.py`)

```python
class AssetClassifier:
    def __init__(self, overrides: dict[str, AssetClass],
                 etf_keywords: dict[AssetClass, list[str]],
                 default: AssetClass = AssetClass.OTHER):
        ...

    @classmethod
    def from_yaml(cls, path: str) -> "AssetClassifier":
        """파일이 없거나 손상되어도 기본 분류기를 반환한다."""
        try:
            raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            logger.warning("자산군 매핑 파일 로드 실패, 기본값 사용")
            return cls.default_instance()
        return cls(...)

    def classify(self, symbol: str, name: str,
                 market_country: str,
                 meta: StockMeta | None) -> AssetClass:
        """DATA_DESIGN §5.3의 7단계 알고리즘.

        meta가 None이어도(=stocks 호출 실패) market_country로 축약 분류한다.
        절대 예외를 던지지 않는다.
        """
```

`meta`가 선택 인자인 것이 핵심이다. 종목 메타 조회는 실패할 수 있고, 그때도 자산배분 차트는 떠야 한다 (FR-301c).

---

## 6. 테스트 대상 매핑

| 모듈 | 테스트 파일 | 방식 |
|---|---|---|
| `analytics/risk_metrics.py` | `tests/test_risk_metrics.py` | **TDD.** 테스트 먼저 |
| `analytics/allocation.py` | `tests/test_allocation.py` | **TDD** |
| `analytics/correlation.py` | `tests/test_correlation.py` | **TDD** |
| `analytics/classifier.py` | `tests/test_classifier.py` | **TDD.** ETF 하위분류·meta=None 축약경로·unknown enum 케이스 필수 |
| `models/` | `tests/test_models.py` | 검증 규칙 |
| `api/toss_client.py` | `tests/test_toss_mapping.py` | `_to_holding` 매핑, `Price.usd == null` 가드, 문자열 Decimal 파싱 |
| `api/token_store.py` | `tests/test_token_store.py` | 만료 판정, 손상 파일 복원 |
| `api/throttle.py` | `tests/test_throttle.py` | 헤더 파싱, 잔여 소진 시 대기 |
| `api/errors.py` | `tests/test_errors.py` | 에러코드 → 예외 매핑, unknown code 허용 |
| `ai/prompts.py` | `tests/test_prompts.py` | 페이로드 생성만 |
| `ui/format.py` | `tests/test_format.py` | 포맷터 |
| `ui/` 나머지 | — | 테스트 안 함 |

---

## 7. 구현 체크리스트

```
[ ] models/       Pydantic 모델 7종 (+ StockMeta)
[ ] config.py     Settings + .env.example (TOSS_CLIENT_ID/SECRET)
[ ] tests/        analytics 테스트 (구현보다 먼저)
[ ] analytics/    returns, risk_metrics, allocation, correlation, classifier
[ ] api/          base, errors, token_store, throttle, mock_client,
                  toss_client, cached_client
[ ] services/     dashboard_service
[ ] ui/           theme, format, 컴포넌트 6종, styles.css
[ ] ai/           prompts, commentary, fallback
[ ] app.py        레이아웃 조립
[ ] README.md     실행법 + 단순화 가정 명시
                  (환율 단일값 / buy-and-hold / cashBuyingPower≠예수금)
[ ] .gitignore    .env, data/cache/, __pycache__, .venv
```

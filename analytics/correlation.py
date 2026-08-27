import pandas as pd

from models.holding import AssetClass
from models.metrics import CorrelationMatrix


def asset_class_correlation(
    prices: pd.DataFrame,
    ticker_to_class: dict[str, AssetClass],
    weights: dict[str, float],
) -> CorrelationMatrix | None:
    """자산군별 비중가중 수익률 시계열의 피어슨 상관계수 행렬 (FR-501).

    자산군이 1개뿐이면 상관관계가 무의미하므로 None을 반환한다 (FR-504).
    가격이 고정돼 분산이 0인 자산군(현금, 거래정지 종목 등)은 상관계수가
    정의되지 않으므로(0으로 나눔 -> NaN) 제외한다.
    """
    rets = prices.pct_change().dropna(how="all")
    by_class: dict[str, pd.Series] = {}
    # AssetClass(StrEnum) set의 순회 순서는 프로세스마다 달라질 수 있어
    # (Enum 해시가 PYTHONHASHSEED 영향을 받음) 값 기준으로 정렬해 축 순서를 고정한다.
    for cls in sorted(set(ticker_to_class.values()), key=lambda c: c.value):
        cols = [t for t, c in ticker_to_class.items() if c == cls and t in rets.columns]
        if not cols:
            continue
        w = pd.Series({t: weights.get(t, 0) for t in cols})
        if w.sum() == 0:
            continue
        series = (rets[cols] * (w / w.sum())).sum(axis=1)
        if series.std(ddof=0) == 0:
            continue  # 분산 0 -> 상관계수 정의 불가
        by_class[str(cls)] = series

    if len(by_class) < 2:
        return None  # FR-504

    df = pd.DataFrame(by_class).dropna()
    corr = df.corr(method="pearson").round(2)
    if corr.isna().to_numpy().any():
        return None
    return CorrelationMatrix(
        labels=list(corr.columns),
        values=corr.values.tolist(),
    )

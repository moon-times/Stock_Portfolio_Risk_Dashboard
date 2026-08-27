import pandas as pd


def portfolio_returns(
    prices: pd.DataFrame,
    weights: dict[str, float],
) -> pd.Series:
    """
    prices: index=날짜, columns=ticker, values=종가
    weights: ticker -> 비중 (합 1.0. 아니면 재정규화)
    """
    rets = prices.pct_change().dropna(how="all")
    common = [t for t in rets.columns if t in weights]
    if not common:
        return pd.Series(dtype=float)
    w = pd.Series({t: weights[t] for t in common})
    w = w / w.sum()  # 재정규화
    return (rets[common] * w).sum(axis=1)

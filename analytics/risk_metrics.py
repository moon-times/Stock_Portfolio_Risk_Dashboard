import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def annualized_volatility(returns: pd.Series) -> float | None:
    r = returns.dropna()
    if len(r) < 2:
        return None
    return float(r.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))


def sharpe_ratio(
    returns: pd.Series, risk_free_rate: float, fallback_rate: float = 0.03
) -> float | None:
    # FR-402a / AT-11 / 위험 2: risk_free_rate는 소수비율(예: 0.0325)이어야
    # 한다. api/ 레이어가 /100 변환을 누락하는 등 범위(0~0.2)를 벗어난 값이
    # 들어오면 단위 오류로 간주해 폴백값을 쓴다 (DATA_DESIGN §6).
    if not (0 <= risk_free_rate <= 0.2):
        risk_free_rate = fallback_rate

    r = returns.dropna()
    if len(r) < 2:
        return None
    vol = annualized_volatility(r)
    if vol is None or vol == 0:
        return None
    annual_return = float(r.mean() * TRADING_DAYS_PER_YEAR)
    return (annual_return - risk_free_rate) / vol


def max_drawdown(returns: pd.Series) -> float | None:
    r = returns.dropna()
    if len(r) < 2:
        return None
    cum = (1 + r).cumprod()
    peak = cum.cummax()
    return float(((cum - peak) / peak).min())


def historical_var(returns: pd.Series, confidence: float = 0.95) -> float | None:
    r = returns.dropna()
    if len(r) < 20:
        return None
    return float(r.quantile(1 - confidence))


def beta(returns: pd.Series, benchmark_returns: pd.Series) -> float | None:
    df = pd.concat([returns, benchmark_returns], axis=1).dropna()
    if len(df) < 20:
        return None
    p, b = df.iloc[:, 0], df.iloc[:, 1]
    var_b = b.var(ddof=1)
    if var_b == 0:
        return None
    return float(p.cov(b) / var_b)


def herfindahl_index(weights: list[float]) -> float | None:
    w = [x for x in weights if x is not None]
    if not w:
        return None
    return float(sum(x**2 for x in w))

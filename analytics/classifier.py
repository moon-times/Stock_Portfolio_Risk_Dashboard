import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from models.holding import AssetClass
from models.stock_meta import StockMeta

logger = logging.getLogger(__name__)

KR_MARKETS = {"KOSPI", "KOSDAQ", "KR_ETC"}
US_MARKETS = {"NYSE", "NASDAQ", "AMEX", "US_ETC"}
ETF_TYPES = {"ETF", "FOREIGN_ETF", "ETN"}

_ASSET_CLASS_BY_LABEL = {ac.value: ac for ac in AssetClass}


@dataclass
class ClassifierConfig:
    overrides: dict[str, AssetClass] = field(default_factory=dict)
    etf_keywords: dict[AssetClass, list[str]] = field(default_factory=dict)
    default: AssetClass = AssetClass.OTHER

    @classmethod
    def default_instance(cls) -> "ClassifierConfig":
        return cls()


def load_classifier_config(path: str) -> ClassifierConfig:
    """`config/asset_class_map.yaml`을 읽는다.

    파일이 없거나 문법이 손상되어도 예외를 던지지 않고 기본 설정으로
    폴백한다 (FR-303, UC-06 흐름 C).
    """
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        logger.warning("자산군 매핑 파일 로드 실패(%s), 기본값 사용", path)
        return ClassifierConfig.default_instance()

    if not isinstance(raw, dict):
        logger.warning("자산군 매핑 파일 형식이 올바르지 않음(%s), 기본값 사용", path)
        return ClassifierConfig.default_instance()

    raw_overrides = raw.get("overrides") or {}
    overrides = {
        symbol: _ASSET_CLASS_BY_LABEL[label]
        for symbol, label in raw_overrides.items()
        if label in _ASSET_CLASS_BY_LABEL
    }
    for symbol, label in raw_overrides.items():
        if label not in _ASSET_CLASS_BY_LABEL:
            logger.warning("overrides의 미지의 자산군 라벨 무시: %s -> %s", symbol, label)

    raw_etf_keywords = raw.get("etf_keywords") or {}
    etf_keywords = {
        _ASSET_CLASS_BY_LABEL[label]: keywords
        for label, keywords in raw_etf_keywords.items()
        if label in _ASSET_CLASS_BY_LABEL
    }
    for label in raw_etf_keywords:
        if label not in _ASSET_CLASS_BY_LABEL:
            logger.warning("etf_keywords의 미지의 자산군 라벨 무시: %s", label)

    default_label = raw.get("default")
    default = _ASSET_CLASS_BY_LABEL.get(default_label, AssetClass.OTHER)
    if default_label is not None and default_label not in _ASSET_CLASS_BY_LABEL:
        logger.warning("default의 미지의 자산군 라벨 무시, 기타로 대체: %s", default_label)

    return ClassifierConfig(overrides=overrides, etf_keywords=etf_keywords, default=default)


def classify(
    holding_row: dict, meta: StockMeta | None, cfg: ClassifierConfig
) -> AssetClass:
    """DATA_DESIGN §5.3의 7단계 알고리즘. 절대 예외를 던지지 않는다 (FR-303)."""
    symbol = holding_row["symbol"]
    name = holding_row.get("name", "")

    # 1. 수동 오버라이드
    if symbol in cfg.overrides:
        return cfg.overrides[symbol]

    # 2. 메타 조회 실패 -> marketCountry 축약 분류
    if meta is None:
        return (
            AssetClass.DOMESTIC_EQUITY
            if holding_row.get("marketCountry") == "KR"
            else AssetClass.FOREIGN_EQUITY
        )

    st, mk = meta.security_type, meta.market

    # 3. 리츠 / 인프라펀드
    if st in ("REIT", "INFRASTRUCTURE_FUND"):
        return AssetClass.REIT

    # 4. ETF 계열 -> 종목명 키워드 하위 분류
    if st in ETF_TYPES:
        for asset_class, keywords in cfg.etf_keywords.items():
            if any(k.upper() in name.upper() for k in keywords):
                return asset_class
        return AssetClass.DOMESTIC_EQUITY if mk in KR_MARKETS else AssetClass.FOREIGN_EQUITY

    # 5. 해외 주식
    if st in ("FOREIGN_STOCK", "DEPOSITARY_RECEIPT") or mk in US_MARKETS:
        return AssetClass.FOREIGN_EQUITY

    # 6. 국내 주식
    if mk in KR_MARKETS:
        return AssetClass.DOMESTIC_EQUITY

    # 7. 미지의 enum 값 등
    return cfg.default

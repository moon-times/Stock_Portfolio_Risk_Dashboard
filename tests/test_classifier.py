from models.holding import AssetClass
from models.stock_meta import StockMeta

from analytics.classifier import ClassifierConfig, classify, load_classifier_config


def make_meta(**overrides):
    defaults = dict(symbol="005930", market="KOSPI", security_type="STOCK")
    defaults.update(overrides)
    return StockMeta(**defaults)


class TestClassifyOverride:
    def test_symbol_in_overrides_wins_regardless_of_meta(self):
        cfg = ClassifierConfig(overrides={"005930": AssetClass.BOND})
        row = {"symbol": "005930", "marketCountry": "KR"}
        meta = make_meta(security_type="FOREIGN_STOCK")  # 무시되어야 함
        assert classify(row, meta, cfg) == AssetClass.BOND


class TestClassifyMissingMeta:
    def test_meta_none_kr_country_is_domestic_equity(self):
        cfg = ClassifierConfig()
        row = {"symbol": "005930", "marketCountry": "KR"}
        assert classify(row, None, cfg) == AssetClass.DOMESTIC_EQUITY

    def test_meta_none_us_country_is_foreign_equity(self):
        cfg = ClassifierConfig()
        row = {"symbol": "AAPL", "marketCountry": "US"}
        assert classify(row, None, cfg) == AssetClass.FOREIGN_EQUITY


class TestClassifyReit:
    def test_reit_security_type(self):
        cfg = ClassifierConfig()
        row = {"symbol": "123456"}
        meta = make_meta(security_type="REIT")
        assert classify(row, meta, cfg) == AssetClass.REIT

    def test_infrastructure_fund_security_type(self):
        cfg = ClassifierConfig()
        row = {"symbol": "123456"}
        meta = make_meta(security_type="INFRASTRUCTURE_FUND")
        assert classify(row, meta, cfg) == AssetClass.REIT


class TestClassifyEtfKeywords:
    def _cfg(self):
        return ClassifierConfig(
            etf_keywords={
                AssetClass.BOND: ["국고채", "회사채", "단기채", "종합채권", "크레딧", "TREASURY", "BOND"],
                AssetClass.COMMODITY: ["골드", "금현물", "은선물", "원유", "구리", "농산물", "GOLD", "OIL"],
            }
        )

    def test_bond_keyword_match(self):
        row = {"symbol": "148070", "name": "KOSEF 국고채10년"}
        meta = make_meta(symbol="148070", market="KOSPI", security_type="ETF")
        assert classify(row, meta, self._cfg()) == AssetClass.BOND

    def test_commodity_keyword_match(self):
        row = {"symbol": "132030", "name": "KODEX 골드선물"}
        meta = make_meta(symbol="132030", market="KOSPI", security_type="ETF")
        assert classify(row, meta, self._cfg()) == AssetClass.COMMODITY

    def test_no_keyword_match_falls_back_to_market_country(self):
        row = {"symbol": "069500", "name": "KODEX 200"}
        meta = make_meta(symbol="069500", market="KOSPI", security_type="ETF")
        assert classify(row, meta, self._cfg()) == AssetClass.DOMESTIC_EQUITY


class TestClassifyForeignStock:
    def test_foreign_stock_security_type(self):
        cfg = ClassifierConfig()
        row = {"symbol": "AAPL"}
        meta = make_meta(symbol="AAPL", market="NASDAQ", security_type="FOREIGN_STOCK")
        assert classify(row, meta, cfg) == AssetClass.FOREIGN_EQUITY


class TestClassifyDomesticStock:
    def test_kospi_stock(self):
        cfg = ClassifierConfig()
        row = {"symbol": "005930"}
        meta = make_meta(market="KOSPI", security_type="STOCK")
        assert classify(row, meta, cfg) == AssetClass.DOMESTIC_EQUITY


class TestClassifyUnknownEnum:
    def test_unknown_security_type_and_market_falls_back_to_cfg_default(self):
        # market도 KR/US 카탈로그에 없어야 6단계(국내주식 폴백)를 거치지 않고
        # 진짜 7단계(cfg.default)에 도달한다. default를 OTHER가 아닌 값으로
        # 지정해, 7단계가 하드코딩된 OTHER가 아니라 cfg.default를 실제로
        # 반환하는지 구별해서 검증한다.
        cfg = ClassifierConfig(default=AssetClass.FOREIGN_EQUITY)
        row = {"symbol": "999999"}
        meta = make_meta(market="CRYPTO_EXCHANGE", security_type="CRYPTO_ETP")
        assert classify(row, meta, cfg) == AssetClass.FOREIGN_EQUITY

    def test_default_config_falls_back_to_other(self):
        cfg = ClassifierConfig()  # default=AssetClass.OTHER
        row = {"symbol": "999999"}
        meta = make_meta(market="CRYPTO_EXCHANGE", security_type="CRYPTO_ETP")
        assert classify(row, meta, cfg) == AssetClass.OTHER


class TestLoadClassifierConfig:
    def test_missing_file_returns_default_config_without_raising(self, tmp_path):
        missing = tmp_path / "does_not_exist.yaml"
        cfg = load_classifier_config(str(missing))
        assert isinstance(cfg, ClassifierConfig)
        assert cfg.overrides == {}

    def test_malformed_yaml_returns_default_config_without_raising(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("overrides: [unterminated\n  - broken: :::", encoding="utf-8")
        cfg = load_classifier_config(str(bad))
        assert isinstance(cfg, ClassifierConfig)
        assert cfg.overrides == {}

    def test_yaml_that_is_not_a_mapping_returns_default_config(self, tmp_path):
        not_a_dict = tmp_path / "not_a_dict.yaml"
        not_a_dict.write_text("- just\n- a\n- list\n", encoding="utf-8")
        cfg = load_classifier_config(str(not_a_dict))
        assert isinstance(cfg, ClassifierConfig)
        assert cfg.overrides == {}

    def test_real_shipped_config_file_loads_and_classifies_etfs(self):
        # tmp_path 픽스처가 아니라 실제로 배포되는 config/asset_class_map.yaml을
        # 로드해서, 파일이 실제로 존재하고 발표 시나리오(ETF 하위분류)가
        # 작동하는지 확인한다.
        cfg = load_classifier_config("config/asset_class_map.yaml")
        assert cfg.overrides == {"132030": AssetClass.COMMODITY}
        assert AssetClass.BOND in cfg.etf_keywords
        assert AssetClass.COMMODITY in cfg.etf_keywords
        assert AssetClass.FOREIGN_EQUITY in cfg.etf_keywords

        bond_row = {"symbol": "148070", "name": "KOSEF 국고채10년"}
        bond_meta = make_meta(symbol="148070", market="KOSPI", security_type="ETF")
        assert classify(bond_row, bond_meta, cfg) == AssetClass.BOND

        commodity_row = {"symbol": "132030", "name": "KODEX 골드선물"}
        commodity_meta = make_meta(symbol="132030", market="KOSPI", security_type="ETF")
        assert classify(commodity_row, commodity_meta, cfg) == AssetClass.COMMODITY

    def test_valid_yaml_parses_overrides_and_etf_keywords(self, tmp_path):
        yaml_file = tmp_path / "asset_class_map.yaml"
        yaml_file.write_text(
            """
overrides:
  "132030": 원자재
etf_keywords:
  채권:
    - 국고채
    - BOND
default: 기타
""",
            encoding="utf-8",
        )
        cfg = load_classifier_config(str(yaml_file))
        assert cfg.overrides == {"132030": AssetClass.COMMODITY}
        assert cfg.etf_keywords == {AssetClass.BOND: ["국고채", "BOND"]}
        assert cfg.default == AssetClass.OTHER

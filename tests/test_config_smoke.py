from recovery import config


def test_cpv_in_scope():
    assert config.cpv_in_scope("45233140-2") is True   # roadworks
    assert config.cpv_in_scope("71322000-1") is True    # engineering
    assert config.cpv_in_scope("15800000-6") is False   # food
    assert config.cpv_in_scope(None) is False
    assert config.cpv_in_scope("") is False


def test_paths_exist_as_config():
    assert config.CPV_DIVISIONS == ("45", "71", "09", "31", "34")
    assert config.OUT_DIR.name == "out"


def test_ingest_bounds_present():
    assert config.PROZORRO_TARGET == 500
    assert config.PROZORRO_SCAN_CAP == 1500
    assert config.SPENDING_BATCH == 10
    assert config.SPENDING_WINDOW_DAYS == 90

from recovery.normalize_fields import normalize_edrpou, normalize_company_name, cpv_division


def test_normalize_edrpou_pads_and_strips():
    assert normalize_edrpou("31725604") == "31725604"
    assert normalize_edrpou(" 31725604 ") == "31725604"
    assert normalize_edrpou("1234567") == "01234567"     # pad to 8
    assert normalize_edrpou("UA-31725604") == "31725604" # strip non-digits
    assert normalize_edrpou(None) is None
    assert normalize_edrpou("") is None
    assert normalize_edrpou("not-a-code") is None


def test_normalize_company_name():
    # lowercase, strip legal forms and quotes/punctuation, collapse whitespace
    assert normalize_company_name('ТОВ "ІТ СПЕЦІАЛІСТ"') == "іт спеціаліст"
    assert normalize_company_name("LLC  Build  Co.") == "build co"
    assert normalize_company_name('Приватне підприємство «Шлях»') == "шлях"
    assert normalize_company_name(None) == ""
    assert normalize_company_name("  A   B  ") == "a b"


def test_cpv_division():
    assert cpv_division("45233140-2") == "45"
    assert cpv_division("09310000") == "09"
    assert cpv_division(None) is None
    assert cpv_division("4") is None

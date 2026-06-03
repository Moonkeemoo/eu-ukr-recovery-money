import json
from pathlib import Path

import httpx
import respx

from recovery.stage1_ingest import pull_prozorro, pull_spending, pull_ted

FIX = Path(__file__).parent / "fixtures"


@respx.mock
def test_pull_prozorro_returns_records(tmp_path):
    page = json.loads((FIX / "prozorro_page.json").read_text(encoding="utf-8"))
    respx.get(url__startswith="https://public-api.prozorro.gov.ua").mock(
        return_value=httpx.Response(200, json=page)
    )
    records = pull_prozorro(cache_dir=tmp_path, max_pages=1)
    assert len(records) == 1
    assert records[0]["contractID"] == "UA-2025-09-01-000001"


@respx.mock
def test_pull_spending_returns_records(tmp_path):
    page = json.loads((FIX / "spending_page.json").read_text(encoding="utf-8"))
    respx.get(url__startswith="https://api.spending.gov.ua").mock(
        return_value=httpx.Response(200, json=page)
    )
    records = pull_spending(cache_dir=tmp_path, edrpous=["31725604"], max_pages=1)
    assert len(records) == 1
    assert records[0]["recipt_edrpou"] == "31725604"


@respx.mock
def test_pull_ted_returns_records(tmp_path):
    page = json.loads((FIX / "ted_page.json").read_text(encoding="utf-8"))
    respx.post(url__startswith="https://api.ted.europa.eu").mock(
        return_value=httpx.Response(200, json=page)
    )
    records = pull_ted(cache_dir=tmp_path, max_pages=1)
    assert records[0]["publication-number"] == "00654321-2025"

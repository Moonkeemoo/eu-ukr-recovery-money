import json
from pathlib import Path

import httpx
import respx

from recovery.stage1_ingest import pull_prozorro, pull_spending, pull_ted

FIX = Path(__file__).parent / "fixtures"


@respx.mock
def test_pull_prozorro_walks_feed_and_filters_cpv(tmp_path):
    feed_p1 = {"data": [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}],
               "next_page": {"offset": "OFF2"}}
    feed_p2 = {"data": [], "next_page": {"offset": "OFF2"}}
    contracts = {
        "c1": {"data": {"contractID": "UA-1",
            "items": [{"classification": {"scheme": "ДК021", "id": "45233140-2"}}],
            "suppliers": [{"name": "A", "identifier": {"scheme": "UA-EDR", "id": "111"}}],
            "value": {"amount": 100}}},
        "c2": {"data": {"contractID": "UA-2",
            "items": [{"classification": {"scheme": "ДК021", "id": "15800000-6"}}],
            "suppliers": [{"name": "B", "identifier": {"id": "222"}}],
            "value": {"amount": 50}}},
        "c3": {"data": {"contractID": "UA-3",
            "items": [{"classification": {"scheme": "ДК021", "id": "71320000-7"}}],
            "suppliers": [{"name": "C", "identifier": {"id": "333"}}],
            "value": {"amount": 200}}},
    }

    def handler(request):
        path = request.url.path
        if path.endswith("/contracts"):
            offset = request.url.params.get("offset")
            return httpx.Response(200, json=(feed_p2 if offset else feed_p1))
        cid = path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=contracts[cid])

    respx.route(host="public-api.prozorro.gov.ua").mock(side_effect=handler)

    out = pull_prozorro(cache_dir=tmp_path, target=10, scan_cap=10)
    assert [c["contractID"] for c in out] == ["UA-1", "UA-3"]  # c2 (CPV 15) filtered out


@respx.mock
def test_pull_prozorro_stops_at_target(tmp_path):
    feed = {"data": [{"id": "c1"}, {"id": "c3"}], "next_page": {"offset": "OFF2"}}
    contracts = {
        "c1": {"data": {"contractID": "UA-1",
            "items": [{"classification": {"id": "45233140-2"}}],
            "suppliers": [{"name": "A", "identifier": {"id": "111"}}],
            "value": {"amount": 100}}},
        "c3": {"data": {"contractID": "UA-3",
            "items": [{"classification": {"id": "71320000-7"}}],
            "suppliers": [{"name": "C", "identifier": {"id": "333"}}],
            "value": {"amount": 200}}},
    }

    def handler(request):
        if request.url.path.endswith("/contracts"):
            return httpx.Response(200, json=feed)
        return httpx.Response(200, json=contracts[request.url.path.rsplit("/", 1)[-1]])

    respx.route(host="public-api.prozorro.gov.ua").mock(side_effect=handler)
    out = pull_prozorro(cache_dir=tmp_path, target=1, scan_cap=10)
    assert [c["contractID"] for c in out] == ["UA-1"]


@respx.mock
def test_pull_prozorro_respects_scan_cap(tmp_path):
    feed = {"data": [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}],
            "next_page": {"offset": "OFF2"}}

    def contract(cid):
        return {"data": {"contractID": cid,
            "items": [{"classification": {"id": "45000000-7"}}],
            "suppliers": [{"name": "X", "identifier": {"id": "1"}}],
            "value": {"amount": 1}}}
    contracts = {"c1": contract("UA-1"), "c2": contract("UA-2"), "c3": contract("UA-3")}

    def handler(request):
        if request.url.path.endswith("/contracts"):
            return httpx.Response(200, json=feed)
        return httpx.Response(200, json=contracts[request.url.path.rsplit("/", 1)[-1]])

    respx.route(host="public-api.prozorro.gov.ua").mock(side_effect=handler)
    out = pull_prozorro(cache_dir=tmp_path, target=100, scan_cap=2)
    assert len(out) == 2  # scanned only 2 of 3 stubs before hitting scan_cap


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

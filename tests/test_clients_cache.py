import httpx
import respx
from recovery.clients import CachedClient


@respx.mock
def test_get_json_caches_to_disk(tmp_path):
    route = respx.get("https://example.test/data").mock(
        return_value=httpx.Response(200, json={"ok": 1})
    )
    client = CachedClient(cache_dir=tmp_path)

    first = client.get_json("https://example.test/data", params={"a": "1"})
    second = client.get_json("https://example.test/data", params={"a": "1"})

    assert first == {"ok": 1}
    assert second == {"ok": 1}
    # second call served from disk cache, network hit only once
    assert route.call_count == 1
    assert any(tmp_path.iterdir())

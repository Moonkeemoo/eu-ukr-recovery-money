import hashlib
import json
import time
from pathlib import Path

import httpx


class CachedClient:
    """Thin httpx wrapper: GET/POST JSON with on-disk caching and retry/backoff."""

    def __init__(self, cache_dir: Path, max_retries: int = 3):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries
        self._client = httpx.Client(timeout=30.0)

    def _key(self, method: str, url: str, params, body) -> Path:
        raw = json.dumps([method, url, params, body], sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
        return self.cache_dir / f"{digest}.json"

    def _request(self, method: str, url: str, params=None, json_body=None) -> dict:
        path = self._key(method, url, params, json_body)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        last_exc = None
        for attempt in range(self.max_retries):
            try:
                resp = self._client.request(method, url, params=params, json=json_body)
                resp.raise_for_status()
                data = resp.json()
                path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                return data
            except httpx.HTTPError as exc:
                last_exc = exc
                time.sleep(0.5 * (2 ** attempt))
        raise last_exc

    def get_json(self, url: str, params=None) -> dict:
        return self._request("GET", url, params=params)

    def post_json(self, url: str, json_body: dict) -> dict:
        return self._request("POST", url, json_body=json_body)

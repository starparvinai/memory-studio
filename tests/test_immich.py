import json

import httpx

from memory_studio.immich import Immich


def test_search_uses_all_selected_albums_in_one_request():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"assets": {"items": [{"id": "photo-1", "type": "IMAGE"}], "nextPage": None}})

    immich = Immich("https://photos.example", "test-key")
    immich.client.close()
    immich.client = httpx.Client(base_url="https://photos.example/api/", transport=httpx.MockTransport(handle))
    try:
        assets = immich.search_year("2025-01-01", "2026-01-01", None, ["album-1", "album-2"])
    finally:
        immich.close()

    assert [asset["id"] for asset in assets] == ["photo-1"]
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/api/search/metadata"
    assert json.loads(requests[0].content)["albumIds"] == ["album-1", "album-2"]

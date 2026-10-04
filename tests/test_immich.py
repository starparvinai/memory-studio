import json

import httpx

from memory_studio.immich import Immich


def test_search_combines_selected_albums_without_repeating_shared_photos():
    requests = []

    def handle(request):
        requests.append(request)
        album_id = json.loads(request.content)["albumIds"][0]
        return httpx.Response(200, json={"assets": {"items": [{"id": "shared", "type": "IMAGE"}, {"id": album_id, "type": "IMAGE"}], "nextPage": None}})

    immich = Immich("https://photos.example", "test-key")
    immich.client.close()
    immich.client = httpx.Client(base_url="https://photos.example/api/", transport=httpx.MockTransport(handle))
    try:
        assets = immich.search_year("2025-01-01", "2026-01-01", None, ["album-1", "album-2"])
    finally:
        immich.close()

    assert [asset["id"] for asset in assets] == ["shared", "album-1", "album-2"]
    assert len(requests) == 2
    assert all(request.method == "POST" and request.url.path == "/api/search/metadata" for request in requests)
    assert [json.loads(request.content)["albumIds"] for request in requests] == [["album-1"], ["album-2"]]

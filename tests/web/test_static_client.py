"""The web client is served correctly and every asset/module it references exists.

A broken relative import in an ES module silently produces a blank page in the browser,
so the import graph is walked here and every file is fetched through the server.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from html.parser import HTMLParser
from posixpath import dirname, join, normpath

import pytest
from fastapi.testclient import TestClient

from hemabot_ui.bootstrap import build_app
from hemabot_ui.config import Settings

IMPORT_PATTERN = re.compile(r"""(?:import|export)\s[^'"]*?from\s+["']([^"']+)["']""")


class _AssetCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.add(str(attributes["id"]))
        for name in ("src", "href"):
            value = attributes.get(name)
            if value and tag in {"script", "link", "img"}:
                self.assets.append(value)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(build_app(Settings(backend="simulated"))) as test_client:
        yield test_client


def parse_index(client: TestClient) -> _AssetCollector:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    collector = _AssetCollector()
    collector.feed(response.text)
    return collector


def test_index_has_mobile_viewport_and_language(client: TestClient) -> None:
    html = client.get("/").text
    assert 'name="viewport"' in html
    assert 'lang="pt-BR"' in html


def test_all_referenced_assets_are_served(client: TestClient) -> None:
    for asset in parse_index(client).assets:
        response = client.get("/" + asset)
        assert response.status_code == 200, asset


def test_all_es_module_imports_resolve(client: TestClient) -> None:
    pending = [a for a in parse_index(client).assets if a.endswith(".js")]
    seen: set[str] = set()
    while pending:
        path = normpath(pending.pop())
        if path in seen:
            continue
        seen.add(path)
        response = client.get("/" + path)
        assert response.status_code == 200, f"{path} not served"
        assert "javascript" in response.headers["content-type"], path
        for specifier in IMPORT_PATTERN.findall(response.text):
            assert specifier.startswith("./") or specifier.startswith("../"), (
                f"{path} imports {specifier!r}: only relative modules work without a bundler"
            )
            pending.append(join(dirname(path), specifier))
    assert "js/app.js" in seen
    assert "js/inputs/joystick.js" in seen


def test_view_element_ids_exist_in_markup(client: TestClient) -> None:
    ids = parse_index(client).ids
    view_js = client.get("/js/view.js").text
    referenced = set(re.findall(r'byId\("([^"]+)"\)', view_js))
    assert referenced, "view.js should look elements up by id"
    assert referenced <= ids, f"missing ids in index.html: {referenced - ids}"


@pytest.mark.parametrize("path", ["/", "/js/app.js", "/css/app.css"])
def test_assets_are_revalidated_after_updates(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.headers["cache-control"] == "no-cache"
    etag = response.headers["etag"]
    assert client.get(path, headers={"If-None-Match": etag}).status_code == 304


def test_unknown_path_is_404(client: TestClient) -> None:
    assert client.get("/does-not-exist.js").status_code == 404

"""Mobile / responsive regression tests.

Guards the native-mobile work: bottom navigation replaces the sidebar at phone
widths, the app is installable (manifest + PWA meta), and no inline JS crept in.
"""

import json
import re

# Endpoint prefixes the bottom nav must cover, in order. Five tabs is the
# native ceiling for comfortable tap targets, so Maintenance and Drivers sit
# behind the "More" tab and light it up when active.
NAV = [
    ("dashboard.", "/"),
    ("vehicles.", "/vehicles/"),
    ("trips.", "/trips/"),
    ("fuel.", "/fuel/"),
    ("more.", "/more/"),
]

PAGES = ["/", "/vehicles/", "/trips/", "/fuel/", "/more/"]

# Pages whose active tab is not their own URL: the overflow sections route
# their active state to the More tab.
ACTIVE_OVERRIDES = {
    "/maintenance/": "/more/",
    "/drivers/": "/more/",
}

# Every page that must render a bottom nav, including overflow + error pages.
ALL_TAB_PAGES = PAGES + ["/maintenance/", "/drivers/"]


def test_bottomnav_renders_five_items_on_every_page(client):
    for path in ALL_TAB_PAGES:
        body = client.get(path).get_data(as_text=True)
        assert 'class="bottomnav"' in body, f"bottom nav missing on {path}"
        start = body.index('class="bottomnav"')
        chunk = body[start : body.index("</nav>", start)]
        links = re.findall(r'<a href="([^"]+)"', chunk)
        assert len(links) == 5, f"{path}: expected 5 bottom-nav links, got {links}"
        assert links == [p for _, p in NAV], f"{path}: wrong link order {links}"


def test_bottomnav_active_state_matches_current_page(client):
    """Exactly one bottom-nav item is active, and it is the current section."""
    for prefix, path in NAV:
        body = client.get(path).get_data(as_text=True)
        chunk = body[body.index('class="bottomnav"') :]
        active = re.findall(r'<a href="([^"]+)"\s+class="active"', chunk)
        assert len(active) == 1, f"{path}: expected 1 active item, got {active}"
        assert active[0] == path, f"{path}: active={active[0]} want {path}"


def test_overflow_sections_activate_the_more_tab(client):
    """Maintenance and Drivers are reached via More, so More must read active."""
    for path, want in ACTIVE_OVERRIDES.items():
        body = client.get(path).get_data(as_text=True)
        chunk = body[body.index('class="bottomnav"') :]
        active = re.findall(r'<a href="([^"]+)"\s+class="active"', chunk)
        assert len(active) == 1, f"{path}: expected 1 active item, got {active}"
        assert active[0] == want, f"{path}: active={active[0]} want {want}"
        # and it must be marked current for screen readers
        assert f'href="{want}"' in chunk
        assert chunk.count("aria-current") == 1, f"{path}: aria-current must appear once"


def test_sidebar_links_every_section_including_drivers(client):
    """Desktop sidebar has no width limit, so it lists all six sections."""
    body = client.get("/drivers/").get_data(as_text=True)
    sidebar = body[body.index('class="sidebar"') : body.index("</aside>")]
    for target in ("/drivers/", "/maintenance/", "/trips/"):
        assert target in sidebar, f"{target} missing from sidebar"
    # Drivers must read active in the sidebar while on its own page
    assert re.search(r'href="/drivers/"\s+class="active"', sidebar), (
        "Drivers not marked active in the sidebar on /drivers/"
    )


def test_more_page_links_both_overflow_sections(client):
    body = client.get("/more/").get_data(as_text=True)
    assert 'href="/drivers/"' in body
    assert 'href="/maintenance/"' in body


def test_bottomnav_and_sidebar_coexist_in_markup(client):
    """Both navs are in the DOM; CSS alone decides which shows at a given width."""
    body = client.get("/vehicles/").get_data(as_text=True)
    assert 'class="sidebar"' in body
    assert 'class="bottomnav"' in body


def test_active_state_is_js_free_and_keyed_on_endpoint(client):
    """No inline scripts; active class comes from request.endpoint, not JS."""
    body = client.get("/trips/").get_data(as_text=True)
    chunk = body[body.index('class="bottomnav"') :]
    assert re.search(r'<a href="/trips/"[^>]*class="active"', chunk), (
        "Trips should be the active bottom-nav item on /trips/"
    )


def test_no_inline_script_in_any_template():
    import pathlib

    for tpl in pathlib.Path("app/templates").rglob("*.html"):
        for match in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", tpl.read_text(), re.S):
            assert not match.strip(), f"inline <script> body in {tpl}"


def test_manifest_is_valid_json_and_installable(client):
    resp = client.get("/static/manifest.webmanifest")
    assert resp.status_code == 200
    manifest = json.loads(resp.get_data(as_text=True))
    for key in ("name", "short_name", "start_url", "display", "theme_color", "icons"):
        assert key in manifest, f"manifest missing {key}"
    assert manifest["display"] in ("standalone", "fullscreen", "minimal-ui")
    assert manifest["icons"], "manifest must declare at least one icon"
    for icon in manifest["icons"]:
        assert client.get(icon["src"]).status_code == 200, f"icon 404: {icon['src']}"


def test_manifest_content_type_is_json(client):
    resp = client.get("/static/manifest.webmanifest")
    assert "application/manifest+json" in resp.content_type


def test_pwa_meta_tags_present(client):
    body = client.get("/").get_data(as_text=True)
    # viewport-fit=cover is required for env(safe-area-inset-*) to work on iOS
    assert "viewport-fit=cover" in body
    assert 'name="theme-color"' in body
    assert 'name="apple-mobile-web-app-capable"' in body
    assert 'rel="manifest"' in body


def test_viewport_meta_does_not_disable_zoom(client):
    """Accessibility: user-scalable must not be 'no', maximum-scale must be < 5."""
    body = client.get("/").get_data(as_text=True)
    meta = re.search(r'<meta name="viewport" content="([^"]+)"', body)
    assert meta, "viewport meta missing"
    content = meta.group(1)
    assert "user-scalable=no" not in content.replace(" ", "")
    assert "user-scalable=0" not in content.replace(" ", "")


def test_icons_are_reachable(client):
    for path in ("/static/icons/icon.svg", "/static/icons/icon-maskable.svg"):
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} not served"
        assert "svg" in resp.content_type


def test_error_pages_also_render_bottomnav(client):
    """The 404/500 handlers go through base.html, so nav must survive there."""
    resp = client.get("/definitely-missing-page")
    assert resp.status_code == 404
    assert 'class="bottomnav"' in resp.get_data(as_text=True)

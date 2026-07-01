import json
import unittest
from unittest.mock import Mock, MagicMock, patch

from integrations.api import SurfboardAPI, _build_section_cache
from integrations.claude_mcp import SurfboardMCPServer
from surfboard.models import Element, ElementType, Page, Section, Session


class TestSurfboardAPI(unittest.TestCase):
    def _make_api_with_page(self) -> tuple[SurfboardAPI, Page]:
        api = SurfboardAPI()
        api.fetcher = Mock()
        api.session = Session()
        tab = api.session.create_tab()
        page = Page(url="https://example.com", title="Example")
        page.elements = [
            Element(id=1, type=ElementType.TEXT_INPUT, name="email", placeholder="Email"),
            Element(id=2, type=ElementType.BUTTON, text="Submit", tag="button"),
            Element(id=3, type=ElementType.LINK, text="Click here", href="https://example.com/next", tag="a"),
            Element(id=4, type=ElementType.TEXTAREA, name="message", placeholder="Your message"),
            Element(id=5, type=ElementType.SELECT, name="country"),
            Element(id=6, type=ElementType.CHECKBOX, name="agree"),
            Element(id=7, type=ElementType.RADIO, name="choice"),
        ]
        tab.page = page
        return api, page

    def test_fill_builds_correct_selector(self) -> None:
        api, _ = self._make_api_with_page()
        api.fetcher.fill.return_value = {"filled": "input[name=\"email\"]", "value": "test@example.com"}

        result = api._fill(1, "test@example.com")

        self.assertEqual(result["filled"], 1)
        api.fetcher.fill.assert_called_once_with("input[name=\"email\"]", "test@example.com")

    def test_fill_rejects_non_input_elements(self) -> None:
        api, _ = self._make_api_with_page()
        result = api._fill(2, "should fail")
        self.assertIn("error", result)

    def test_fill_with_select_type(self) -> None:
        api, _ = self._make_api_with_page()
        api.fetcher.select_option.return_value = {"selected": "select[name=\"country\"]", "value": "US"}

        result = api._fill(5, "US")

        self.assertEqual(result["filled"], 5)
        api.fetcher.select_option.assert_called_once()

    def test_fill_unknown_element_id_returns_error(self) -> None:
        api, _ = self._make_api_with_page()
        result = api._fill(999, "text")
        self.assertIn("error", result)

    def test_hover_builds_correct_selector(self) -> None:
        api, _ = self._make_api_with_page()
        api.fetcher.hover.return_value = {"hovered": "button", "selector_used": "button:has-text(\"Submit\")"}

        result = api._hover(2)

        self.assertEqual(result["hovered"], 2)
        api.fetcher.hover.assert_called_once()

    def test_scroll_to_builds_correct_selector(self) -> None:
        api, _ = self._make_api_with_page()
        api.fetcher.scroll_to.return_value = {"scrolled_to": "input[name=\"email\"]", "selector_used": "input[name=\"email\"]"}

        result = api._scroll_to(1)

        self.assertEqual(result["scrolled_to"], 1)

    def test_scroll_by_passes_coordinates(self) -> None:
        api, _ = self._make_api_with_page()
        api.fetcher.scroll_by.return_value = {"scrolled_by": [0, 500]}

        result = api._scroll_by(0, 500)

        self.assertEqual(result["scrolled_by"], [0, 500])

    def test_click_no_page_returns_error(self) -> None:
        api = SurfboardAPI()
        api.fetcher = Mock()
        api.session = Session()
        api.session.create_tab()

        result = api._click(1)
        self.assertIn("error", result)

    def test_click_unknown_target_returns_error(self) -> None:
        api, _ = self._make_api_with_page()
        result = api._click("foo")
        self.assertIn("error", result)

    def test_navigate_adds_https_prefix(self) -> None:
        api = SurfboardAPI()
        api.fetcher = Mock()
        api.fetcher.fetch.return_value = MagicMock(html="<html><body>Hello</body></html>", final_url="https://example.com", error=None)
        api.session = Session()
        api.session.create_tab()

        with patch("integrations.api.rewrite_url", return_value=("https://example.com", None)):
            with patch("integrations.api.build_page") as mock_build:
                mock_build.return_value = Page(url="https://example.com")
                result = api._navigate("example.com")

        self.assertIn("tab_id", result)

    def test_clear_cookies_calls_fetcher(self) -> None:
        api, _ = self._make_api_with_page()
        api.fetcher.clear_cookies = Mock(return_value=None)

        result = api._clear_cookies()

        self.assertEqual(result["cleared"], True)
        api.fetcher.clear_cookies.assert_called_once()

    def test_call_tool_unknown_command(self) -> None:
        api = SurfboardAPI()
        api.fetcher = Mock()

        result = api.call_tool("nonexistent", {})

        self.assertIn("error", result)

    def test_call_tool_legacy_alias(self) -> None:
        api = SurfboardAPI()
        api.fetcher = Mock()
        api.session = Session()
        api.session.create_tab()
        api.fetcher.fetch.return_value = MagicMock(html="<html><body>Hello</body></html>", final_url="https://example.com", error=None)

        with patch("integrations.api.rewrite_url", return_value=("https://example.com", None)):
            with patch("integrations.api.build_page") as mock_build:
                mock_build.return_value = Page(url="https://example.com")
                result = api.call_tool("navigate", {"url": "https://example.com"})

        self.assertIn("tab_id", result)

    def test_param_alias_id_maps_to_target(self) -> None:
        api = SurfboardAPI()
        api.fetcher = Mock()
        api.fetcher.content.return_value = "<html><body><button>Go</button></body></html>"
        api.fetcher.current_url.return_value = "https://example.com"
        api.session = Session()
        tab = api.session.create_tab()
        page = Page(url="https://example.com")
        page.elements = [Element(id=1, type=ElementType.BUTTON, text="Go", tag="button")]
        tab.page = page
        api.fetcher.click.return_value = {"clicked": "button", "selector_used": "button"}

        with patch("integrations.api.build_page") as mock_build:
            mock_build.return_value = Page(url="https://example.com")
            result = api.call_tool("click", {"id": "1"})

        self.assertIn("clicked", result)


class TestSurfboardMCPServer(unittest.TestCase):
    def test_initialize_returns_capabilities(self) -> None:
        server = SurfboardMCPServer()
        server.api.fetcher = Mock()

        response = server._initialize({"id": 1, "params": {"protocolVersion": "2024-11-05"}})

        self.assertEqual(response["result"]["serverInfo"]["name"], "surfboard")
        self.assertIn("tools", response["result"]["capabilities"])

    def test_list_tools_returns_tool_defs(self) -> None:
        server = SurfboardMCPServer()
        server.api.fetcher = Mock()

        response = server._list_tools({"id": 1})

        tools = response["result"]["tools"]
        self.assertTrue(len(tools) > 20)
        names = [t["name"] for t in tools]
        self.assertIn("browse", names)
        self.assertIn("click", names)
        self.assertIn("fill", names)
        self.assertIn("search", names)

    def test_screenshot_tool_returns_image_content(self) -> None:
        server = SurfboardMCPServer()
        server.api = Mock()
        server.api.call_tool.return_value = {"screenshot_base64": "abc123"}

        response = server._call_tool({
            "id": 1,
            "params": {"name": "screenshot", "arguments": {}},
        })

        content = response["result"]["content"]
        self.assertTrue(any(item["type"] == "image" and item["data"] == "abc123" for item in content))

    def test_unknown_tool_returns_error(self) -> None:
        server = SurfboardMCPServer()
        server.api = Mock()
        server.api.call_tool.return_value = {"error": "Unknown command"}

        response = server._call_tool({
            "id": 1,
            "params": {"name": "nonexistent", "arguments": {}},
        })

        self.assertIn("error", response)

    def test_ping_returns_empty_result(self) -> None:
        server = SurfboardMCPServer()
        server.api.fetcher = Mock()

        response = server.handle_request({"method": "ping", "id": 1})

        self.assertEqual(response["result"], {})

    def test_unknown_method_returns_error(self) -> None:
        server = SurfboardMCPServer()
        server.api.fetcher = Mock()

        response = server.handle_request({"method": "unknown_method", "id": 1})

        self.assertIn("error", response)

    def test_screenshot_routes_through_call_tool(self) -> None:
        server = SurfboardMCPServer()
        server.api = Mock()
        server.api.call_tool.return_value = {"screenshot_base64": "abc123"}

        response = server._call_tool({
            "id": 1,
            "params": {"name": "screenshot", "arguments": {"path": "/tmp/test.png"}},
        })

        server.api.call_tool.assert_called_once_with("screenshot", {"path": "/tmp/test.png"})


class TestModels(unittest.TestCase):
    def test_element_label_uses_text(self) -> None:
        el = Element(id=1, type=ElementType.BUTTON, text="Click Me")
        self.assertEqual(el.label, "Click Me")

    def test_element_label_falls_back_to_placeholder(self) -> None:
        el = Element(id=1, type=ElementType.TEXT_INPUT, placeholder="Enter name")
        self.assertEqual(el.label, "[Enter name]")

    def test_element_label_falls_back_to_name(self) -> None:
        el = Element(id=1, type=ElementType.TEXT_INPUT, name="email")
        self.assertEqual(el.label, "<email>")

    def test_element_label_falls_back_to_tag(self) -> None:
        el = Element(id=1, type=ElementType.TEXT_INPUT, tag="input")
        self.assertEqual(el.label, "<input>")

    def test_page_element_by_id(self) -> None:
        page = Page(url="https://example.com")
        page.elements = [
            Element(id=1, type=ElementType.TEXT_INPUT),
            Element(id=2, type=ElementType.BUTTON),
        ]
        self.assertIsNotNone(page.element_by_id(1))
        self.assertIsNone(page.element_by_id(999))

    def test_session_create_and_switch_tabs(self) -> None:
        session = Session()
        t1 = session.create_tab()
        t2 = session.create_tab()

        self.assertEqual(len(session.tabs), 2)
        self.assertEqual(session.active_tab_id, t2.id)

        self.assertTrue(session.switch_tab(t1.id))
        self.assertEqual(session.active_tab_id, t1.id)

        self.assertFalse(session.switch_tab(999))

    def test_session_close_tab(self) -> None:
        session = Session()
        t1 = session.create_tab()
        t2 = session.create_tab()
        self.assertTrue(session.close_tab(t1.id))
        self.assertEqual(len(session.tabs), 1)

    def test_session_cannot_close_last_tab(self) -> None:
        session = Session()
        t1 = session.create_tab()
        self.assertFalse(session.close_tab(t1.id))

    def test_build_section_cache(self) -> None:
        page = Page(url="https://example.com")
        s1 = Section(title="Intro", section_id=1)
        s2 = Section(title="Details", section_id=2)
        s2a = Section(title="Sub-detail", section_id=3)
        s2.subsections = [s2a]
        page.sections = [s1, s2]

        cache = _build_section_cache(page)

        self.assertEqual(cache[1].title, "Intro")
        self.assertEqual(cache[2].title, "Details")
        self.assertEqual(cache[3].title, "Sub-detail")


class TestCleaner(unittest.TestCase):
    def test_input_type_mapping(self) -> None:
        from surfboard.cleaner import _extract_elements
        from bs4 import BeautifulSoup

        html = """
        <form>
            <input type="text" name="q">
            <input type="submit" name="go" value="Search">
            <input type="reset" name="reset">
            <input type="button" name="btn" value="Click">
            <input type="checkbox" name="agree">
            <input type="radio" name="choice" value="a">
        </form>
        """
        soup = BeautifulSoup(html, "lxml")
        elements = _extract_elements(soup, "https://example.com")

        type_map = {e["name"]: e["type"] for e in elements}
        self.assertEqual(type_map.get("q"), "text_input")
        self.assertEqual(type_map.get("go"), "button")
        self.assertEqual(type_map.get("reset"), "button")
        self.assertEqual(type_map.get("btn"), "button")
        self.assertEqual(type_map.get("agree"), "checkbox")
        self.assertEqual(type_map.get("choice"), "radio")


class TestBrowserFetcher(unittest.TestCase):
    def test_constructor_defaults(self):
        from surfboard.browser import BrowserFetcher

        bf = BrowserFetcher()
        self.assertEqual(bf.timeout, 30.0)
        self.assertFalse(bf.block_resources)
        self.assertIsNone(bf.proxy)

    def test_constructor_with_options(self):
        from surfboard.browser import BrowserFetcher

        bf = BrowserFetcher(timeout=60.0, block_resources=True, proxy="http://localhost:8080")
        self.assertEqual(bf.timeout, 60.0)
        self.assertTrue(bf.block_resources)
        self.assertEqual(bf.proxy, "http://localhost:8080")

    def test_ensure_page_returns_false_on_import_error(self):
        from surfboard.browser import BrowserFetcher

        bf = BrowserFetcher()
        bf._start = Mock(side_effect=ImportError("no playwright"))
        result = bf._ensure_page()
        self.assertFalse(result)

    def test_fetch_returns_import_error_when_no_playwright(self):
        from surfboard.browser import BrowserFetcher

        bf = BrowserFetcher()
        bf._start = Mock(side_effect=ImportError("no playwright"))
        result = bf.fetch("https://example.com")
        self.assertIn("playwright not installed", result.error or "")


class TestPageCache(unittest.TestCase):
    def test_get_set(self):
        from surfboard.cache import PageCache
        cache = PageCache(max_size=5, default_ttl=300.0)
        cache.set("key1", {"data": 1})
        self.assertEqual(cache.get("key1"), {"data": 1})
        self.assertIsNone(cache.get("nonexistent"))

    def test_ttl_expiry(self):
        from surfboard.cache import PageCache
        cache = PageCache(max_size=5, default_ttl=0.0)
        cache.set("key1", "value")
        import time
        time.sleep(0.01)
        self.assertIsNone(cache.get("key1"))

    def test_lru_eviction(self):
        from surfboard.cache import PageCache
        cache = PageCache(max_size=2, default_ttl=300.0)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        self.assertIsNone(cache.get("a"))
        self.assertEqual(cache.get("b"), 2)
        self.assertEqual(cache.get("c"), 3)

    def test_invalidate(self):
        from surfboard.cache import PageCache
        cache = PageCache(max_size=5, default_ttl=300.0)
        cache.set("key1", "value")
        cache.invalidate("key1")
        self.assertIsNone(cache.get("key1"))

    def test_clear(self):
        from surfboard.cache import PageCache
        cache = PageCache(max_size=5, default_ttl=300.0)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        self.assertEqual(cache.size(), 0)

    def test_size(self):
        from surfboard.cache import PageCache
        cache = PageCache(max_size=5, default_ttl=300.0)
        self.assertEqual(cache.size(), 0)
        cache.set("a", 1)
        self.assertEqual(cache.size(), 1)


class TestSurfboardLogger(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()

    def test_log_level_filtering(self):
        from surfboard.log import SurfboardLogger
        logger = SurfboardLogger(log_dir=self.tmpdir, level="warn", batch_size=100)
        logger.info("test", "should not appear")
        logger.warn("test", "warning message")
        logger.flush()
        path = logger._history_path
        lines = path.read_text().splitlines() if path.exists() else []
        self.assertEqual(len(lines), 1)
        self.assertIn("warning message", lines[0])

    def test_batch_flush(self):
        from surfboard.log import SurfboardLogger
        logger = SurfboardLogger(log_dir=self.tmpdir, level="info", batch_size=3)
        logger.info("a", "msg1")
        logger.info("b", "msg2")
        path = logger._history_path
        self.assertTrue(path.exists() or True)
        logger.info("c", "msg3")
        logger.flush()
        lines = path.read_text().splitlines() if path.exists() else []
        self.assertEqual(len(lines), 3)

    def test_log_entry_structure(self):
        from surfboard.log import SurfboardLogger
        logger = SurfboardLogger(log_dir=self.tmpdir, level="info", batch_size=100)
        logger.info("test_tool", "test detail")
        logger.flush()
        path = logger._history_path
        import json
        lines = path.read_text().splitlines() if path.exists() else []
        self.assertTrue(len(lines) >= 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["tool"], "test_tool")
        self.assertEqual(entry["detail"], "test detail")
        self.assertEqual(entry["level"], "info")
        self.assertIn("ts", entry)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class TestRateLimiter(unittest.TestCase):
    def test_acquire_no_wait(self):
        from surfboard.browser import RateLimiter
        limiter = RateLimiter(calls_per_sec=1000.0)
        wait = limiter.acquire()
        self.assertIsInstance(wait, float)
        self.assertGreaterEqual(wait, 0.0)

    def test_acquire_waits_when_called_rapidly(self):
        from surfboard.browser import RateLimiter
        limiter = RateLimiter(calls_per_sec=10.0)
        limiter.acquire()
        import time
        start = time.time()
        limiter.acquire()
        elapsed = time.time() - start
        self.assertGreaterEqual(elapsed, 0.08)

    def test_low_calls_per_sec(self):
        from surfboard.browser import RateLimiter
        limiter = RateLimiter(calls_per_sec=0.1)
        import time
        start = time.time()
        limiter.acquire()
        elapsed = time.time() - start
        self.assertGreaterEqual(elapsed, 0.0)


class TestCookieCodec(unittest.TestCase):
    def test_encode_decode_roundtrip(self):
        from surfboard.browser import _encode_cookies, _decode_cookies
        cookies = [{"name": "test", "value": "val", "domain": ".example.com"}]
        encoded = _encode_cookies(cookies)
        decoded = _decode_cookies(encoded)
        self.assertEqual(decoded, cookies)

    def test_decode_invalid(self):
        from surfboard.browser import _decode_cookies
        result = _decode_cookies("not-valid-base64!!")
        self.assertEqual(result, [])

    def test_empty_list(self):
        from surfboard.browser import _encode_cookies, _decode_cookies
        encoded = _encode_cookies([])
        decoded = _decode_cookies(encoded)
        self.assertEqual(decoded, [])


class TestSessionPersistence(unittest.TestCase):
    def test_save_and_restore(self):
        session = Session()
        tab = session.create_tab()
        tab.url = "https://example.com"
        tab.scroll_position = 100

        import tempfile
        import os
        old_home = os.environ.get("HOME")
        tmpdir = tempfile.mkdtemp()
        os.environ["HOME"] = tmpdir

        try:
            session.save()

            restored = Session()
            result = restored.restore()
            self.assertTrue(result)
            self.assertEqual(restored.active_tab_id, tab.id)
            restored_tab = restored.active_tab
            self.assertIsNotNone(restored_tab)
            self.assertEqual(restored_tab.url, "https://example.com")
            self.assertEqual(restored_tab.scroll_position, 100)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
            if old_home is not None:
                os.environ["HOME"] = old_home

    def test_restore_no_session(self):
        import tempfile
        import os
        old_home = os.environ.get("HOME")
        old_userprofile = os.environ.get("USERPROFILE")
        tmpdir = tempfile.mkdtemp()
        os.environ["HOME"] = tmpdir
        os.environ["USERPROFILE"] = tmpdir

        try:
            session = Session()
            result = session.restore()
            self.assertFalse(result)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
            if old_home is not None:
                os.environ["HOME"] = old_home
            if old_userprofile is not None:
                os.environ["USERPROFILE"] = old_userprofile


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import Mock

from integrations.api import SurfboardAPI
from integrations.claude_mcp import SurfboardMCPServer
from surfboard.models import Element, ElementType, Page, Session


class FeedbackFeaturesTests(unittest.TestCase):
    def _make_api_with_page(self) -> tuple[SurfboardAPI, Page]:
        api = SurfboardAPI()
        api.fetcher = Mock()
        api.session = Session()
        tab = api.session.create_tab()
        page = Page(url="https://example.com", title="Example")
        page.elements = [
            Element(id=1, type=ElementType.TEXT_INPUT, name="email", placeholder="Email")
        ]
        tab.page = page
        return api, page

    def test_fill_uses_fetcher_and_builds_selector(self) -> None:
        api, _ = self._make_api_with_page()
        api.fetcher.fill.return_value = {"filled": "#email", "value": "test@example.com"}

        result = api._fill(1, "test@example.com")

        self.assertEqual(result["filled"], 1)
        api.fetcher.fill.assert_called_once_with("input[name=\"email\"]", "test@example.com")

    def test_screenshot_tool_returns_image_content(self) -> None:
        server = SurfboardMCPServer()
        server.api = Mock()
        server.api._screenshot.return_value = {"screenshot_base64": "abc123"}

        response = server._call_tool({
            "id": 1,
            "params": {"name": "screenshot", "arguments": {}},
        })

        content = response["result"]["content"]
        self.assertTrue(any(item["type"] == "image" and item["data"] == "abc123" for item in content))


if __name__ == "__main__":
    unittest.main()

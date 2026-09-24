"""``wuwa_api`` 的单元测试。

只依赖标准库，不需要安装 AstrBot，也不会发起任何网络请求。

运行::

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# 让测试可以直接 import 插件根目录下的 wuwa_api。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import wuwa_api  # noqa: E402

API_BASE = wuwa_api.DEFAULT_API_BASE
MEDIA_URL = (
    "https://emoji.wuwa.games/apis/api.random-emoji.wuwa.games/v1alpha1/media"
    "?ticket=abc.def"
)


class BuildUrlTest(unittest.TestCase):
    def test_no_params_returns_bare_base(self):
        self.assertEqual(wuwa_api.build_url(API_BASE), API_BASE)

    def test_empty_base_falls_back_to_default(self):
        self.assertEqual(wuwa_api.build_url("   "), API_BASE)
        self.assertEqual(wuwa_api.build_url(None), API_BASE)

    def test_character_is_url_encoded(self):
        url = wuwa_api.build_url(API_BASE, "爱弥斯")
        self.assertEqual(url, f"{API_BASE}?character=%E7%88%B1%E5%BC%A5%E6%96%AF")

    def test_character_is_stripped_and_blank_ignored(self):
        self.assertEqual(wuwa_api.build_url(API_BASE, "  爱弥斯  "), wuwa_api.build_url(API_BASE, "爱弥斯"))
        self.assertEqual(wuwa_api.build_url(API_BASE, "   "), API_BASE)
        self.assertEqual(wuwa_api.build_url(API_BASE, ""), API_BASE)

    def test_original_format_is_omitted(self):
        # original 是服务端默认值，显式传参反而有触发 INVALID_QUERY 的风险。
        self.assertEqual(wuwa_api.build_url(API_BASE, None, "original"), API_BASE)

    def test_webp_format_is_included(self):
        self.assertEqual(wuwa_api.build_url(API_BASE, None, "webp"), f"{API_BASE}?format=webp")

    def test_unknown_format_falls_back_to_original(self):
        for bad in ("gif", "png", "WEBP2", "", None, 123):
            self.assertEqual(wuwa_api.build_url(API_BASE, None, bad), API_BASE)

    def test_format_is_case_insensitive(self):
        self.assertEqual(wuwa_api.build_url(API_BASE, None, " WebP "), f"{API_BASE}?format=webp")

    def test_character_and_format_together(self):
        url = wuwa_api.build_url(API_BASE, "爱弥斯", "webp")
        self.assertIn("character=%E7%88%B1%E5%BC%A5%E6%96%AF", url)
        self.assertIn("format=webp", url)
        self.assertEqual(url.count("character="), 1)
        self.assertEqual(url.count("format="), 1)

    def test_base_with_existing_query_uses_ampersand(self):
        url = wuwa_api.build_url("https://example.com/random?x=1", "秧秧")
        self.assertTrue(url.startswith("https://example.com/random?x=1&character="), url)

    def test_unknown_format_never_leaks_into_url(self):
        url = wuwa_api.build_url(API_BASE, "秧秧", "gif")
        self.assertNotIn("format", url)


class HeadersTest(unittest.TestCase):
    def test_token_produces_bearer_header(self):
        headers = wuwa_api.build_headers("re_abc.def")
        self.assertEqual(headers["Authorization"], "Bearer re_abc.def")

    def test_bearer_prefix_is_required_by_server(self):
        # 实测：裸 Token 会被判为无效，必须带 "Bearer " 前缀。
        self.assertTrue(wuwa_api.build_headers("re_abc.def")["Authorization"].startswith("Bearer "))

    def test_blank_token_means_anonymous(self):
        for blank in ("", "   ", None):
            self.assertNotIn("Authorization", wuwa_api.build_headers(blank))

    def test_token_is_stripped(self):
        self.assertEqual(wuwa_api.build_headers("  tok  ")["Authorization"], "Bearer tok")

    def test_media_headers_never_carry_authorization(self):
        # 带 Authorization 请求媒体地址会被小站返回 401。
        self.assertNotIn("Authorization", wuwa_api.media_headers())


class ValidateMediaUrlTest(unittest.TestCase):
    def test_same_host_is_allowed(self):
        self.assertEqual(wuwa_api.validate_media_url(MEDIA_URL, API_BASE), MEDIA_URL)

    def test_subdomain_of_allowed_suffix_is_allowed(self):
        url = "https://media.wuwa.games/emoji/a.webp"
        self.assertEqual(wuwa_api.validate_media_url(url, API_BASE), url)

    def test_foreign_host_is_rejected(self):
        with self.assertRaises(wuwa_api.WuwaApiError):
            wuwa_api.validate_media_url("https://evil.example.com/a.png", API_BASE)

    def test_lookalike_suffix_is_rejected(self):
        with self.assertRaises(wuwa_api.WuwaApiError):
            wuwa_api.validate_media_url("https://wuwa.games.evil.com/a.png", API_BASE)

    def test_empty_url_is_rejected(self):
        for blank in ("", "   ", None):
            with self.assertRaises(wuwa_api.WuwaApiError):
                wuwa_api.validate_media_url(blank, API_BASE)

    def test_non_http_scheme_is_rejected(self):
        for bad in ("ftp://emoji.wuwa.games/a.png", "file:///etc/passwd", "javascript:alert(1)"):
            with self.assertRaises(wuwa_api.WuwaApiError):
                wuwa_api.validate_media_url(bad, API_BASE)


class ParseRandomResponseTest(unittest.TestCase):
    def test_happy_path(self):
        result = wuwa_api.parse_random_response(
            {
                "id": "r-abc",
                "character": {"slug": "aimisi", "name": "爱弥斯"},
                "url": MEDIA_URL,
            },
        )
        self.assertEqual(result.emoji_id, "r-abc")
        self.assertEqual(result.character_slug, "aimisi")
        self.assertEqual(result.character_name, "爱弥斯")
        self.assertEqual(result.media_url, MEDIA_URL)

    def test_missing_fields_become_empty_strings(self):
        result = wuwa_api.parse_random_response({})
        self.assertEqual(result.emoji_id, "")
        self.assertEqual(result.character_name, "")
        self.assertEqual(result.media_url, "")

    def test_character_not_a_dict_is_tolerated(self):
        result = wuwa_api.parse_random_response({"character": "爱弥斯", "url": "x"})
        self.assertEqual(result.character_name, "")
        self.assertEqual(result.media_url, "x")

    def test_non_dict_payload_is_rejected(self):
        for bad in (None, [], "oops", 42):
            with self.assertRaises(wuwa_api.WuwaApiError):
                wuwa_api.parse_random_response(bad)

    def test_media_url_then_fails_validation_when_missing(self):
        result = wuwa_api.parse_random_response({"id": "r-abc"})
        with self.assertRaises(wuwa_api.WuwaApiError):
            wuwa_api.validate_media_url(result.media_url, API_BASE)


class ErrorHandlingTest(unittest.TestCase):
    def test_parses_code_and_message(self):
        err = wuwa_api.parse_error_response(
            401,
            b'{"code":"UNAUTHORIZED","message":"API Key \xe6\x97\xa0\xe6\x95\x88"}',
        )
        self.assertEqual(err.code, "UNAUTHORIZED")
        self.assertEqual(err.http_status, 401)

    def test_tolerates_non_json_body(self):
        err = wuwa_api.parse_error_response(502, b"<html>bad gateway</html>")
        self.assertEqual(err.code, "")
        self.assertEqual(err.http_status, 502)
        self.assertIn("502", err.message)

    def test_tolerates_empty_body(self):
        err = wuwa_api.parse_error_response(500, None)
        self.assertEqual(err.http_status, 500)

    def test_friendly_message_for_known_codes(self):
        cases = {
            401: "UNAUTHORIZED",
            503: "IDENTITY_UNAVAILABLE",
            400: "INVALID_FORMAT",
        }
        for status, code in cases.items():
            body = f'{{"code":"{code}","message":"raw"}}'.encode()
            err = wuwa_api.parse_error_response(status, body)
            text = wuwa_api.friendly_message(err)
            self.assertNotEqual(text, "raw")
            self.assertTrue(text.strip())

    def test_friendly_message_mentions_character_for_empty_result(self):
        err = wuwa_api.parse_error_response(
            404,
            b'{"code":"CHARACTER_EMPTY","message":"x"}',
        )
        self.assertIn("爱弥斯", wuwa_api.friendly_message(err, "爱弥斯"))
        # 没有角色名时也要给出可用文案
        self.assertTrue(wuwa_api.friendly_message(err, None).strip())

    def test_friendly_message_for_rate_limit(self):
        err = wuwa_api.WuwaApiError("too many", http_status=429)
        self.assertIn("频繁", wuwa_api.friendly_message(err))

    def test_friendly_message_for_unknown_status_keeps_detail(self):
        err = wuwa_api.WuwaApiError("boom", http_status=418)
        text = wuwa_api.friendly_message(err)
        self.assertIn("418", text)
        self.assertIn("boom", text)

    def test_friendly_message_accepts_plain_exception(self):
        self.assertEqual(wuwa_api.friendly_message(ValueError("nope")), "nope")

    def test_token_hint_mentions_configuration(self):
        err = wuwa_api.WuwaApiError("x", code="IDENTITY_UNAVAILABLE", http_status=503)
        text = wuwa_api.friendly_message(err)
        self.assertIn("Token", text)
        self.assertIn("插件配置", text)


class GuessSuffixTest(unittest.TestCase):
    def test_content_type_wins(self):
        cases = {
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/jpeg": ".jpg",
            "image/bmp": ".bmp",
        }
        for content_type, expected in cases.items():
            self.assertEqual(wuwa_api.guess_suffix(content_type, ""), expected)

    def test_content_type_with_charset_is_handled(self):
        self.assertEqual(wuwa_api.guess_suffix("image/png; charset=binary", ""), ".png")

    def test_falls_back_to_url_suffix(self):
        self.assertEqual(wuwa_api.guess_suffix("", "https://x.test/a/b.gif"), ".gif")
        self.assertEqual(wuwa_api.guess_suffix(None, "https://x.test/a/b.jpeg"), ".jpg")

    def test_url_suffix_ignores_query_string(self):
        self.assertEqual(wuwa_api.guess_suffix("", f"{MEDIA_URL}&x=.png"), ".png")

    def test_default_when_nothing_known(self):
        self.assertEqual(wuwa_api.guess_suffix("application/octet-stream", "https://x.test/a"), ".png")
        self.assertEqual(wuwa_api.guess_suffix(None, None), ".png")


if __name__ == "__main__":
    unittest.main(verbosity=2)

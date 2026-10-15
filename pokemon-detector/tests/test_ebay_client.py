"""Offline official API client fixtures; never send credentials over the network."""
import os
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ebay_discovery import EbayClient, EbayError, EbayBudgetError, _NoRedirect

CREDS = {"EBAY_SANDBOX_CLIENT_ID": "fixture-id", "EBAY_SANDBOX_CLIENT_SECRET": "fixture-secret"}


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, CREDS, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def client(self, responses, **kwargs):
        self.calls = []
        def transport(url, **options):
            self.calls.append((url, options))
            answer = responses.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return EbayClient(transport=transport, sleep=lambda _: None, **kwargs)

    def test_cache_expiry_and_market_headers(self):
        now = [0]
        client = self.client([{"access_token": "first", "expires_in": 100}, {}, {},
                              {"access_token": "second", "expires_in": 100}, {}], clock=lambda: now[0])
        client.search("pokemon PSA", "EBAY_GB")
        client.search("pokemon PSA", "EBAY_US")
        now[0] = 91
        client.search("pokemon PSA", "EBAY_DE")
        self.assertEqual(client.oauth_requests_used, 2)
        self.assertEqual(client.requests_used, 3)
        self.assertTrue(all(url.startswith("https://api.sandbox.ebay.com/") for url, _ in self.calls))
        self.assertEqual(self.calls[2][1]["headers"]["X-EBAY-C-MARKETPLACE-ID"], "EBAY_US")
        self.assertEqual(self.calls[-1][1]["headers"]["Authorization"], "Bearer second")

    def test_environment_does_not_fallback(self):
        with self.assertRaises(EbayError):
            EbayClient("production")
        with patch.dict(os.environ, {"EBAY_PRODUCTION_CLIENT_ID": "a", "EBAY_PRODUCTION_CLIENT_SECRET": "b"}):
            self.assertEqual(EbayClient("production").base, "https://api.ebay.com")

    def test_pagination_dedupes_and_ignores_next_url(self):
        client = self.client([{"access_token": "t", "expires_in": 7200},
            {"itemSummaries": [{"itemId": "a"}, {"itemId": "b"}], "next": "https://evil.invalid/"},
            {"itemSummaries": [{"itemId": "b"}, {"itemId": "c"}], "next": "more"}])
        result = client.search("pokemon", limit=2, max_pages=2)
        self.assertEqual([r["itemId"] for r in result["items"]], ["a", "b", "c"])
        self.assertFalse(result["coverage"]["complete"])
        self.assertEqual(result["coverage"]["raw_count"], 4)
        self.assertEqual(result["coverage"]["raw_counts_per_page"], [2, 2])
        self.assertIn("offset=2", self.calls[-1][0])
        self.assertNotIn("evil", self.calls[-1][0])

    def test_401_refreshes_only_once(self):
        error = urllib.error.HTTPError("url", 401, "secret", {}, None)
        client = self.client([{"access_token": "t", "expires_in": 7200}, error,
                              {"access_token": "new", "expires_in": 7200}, error])
        with self.assertRaisesRegex(EbayError, "eBay HTTP 401"):
            client.search("pokemon")
        self.assertEqual(client.requests_used, 2)
        self.assertEqual(client.oauth_requests_used, 2)

    def test_429_retries_are_bounded_and_budgeted(self):
        error = urllib.error.HTTPError("url", 429, "secret", {"Retry-After": "2"}, None)
        client = self.client([{"access_token": "t", "expires_in": 7200}, error, error, error])
        delays = []
        client._sleep = delays.append
        with self.assertRaisesRegex(EbayError, "eBay HTTP 429"):
            client.search("pokemon")
        self.assertEqual(delays, [2, 2])
        self.assertEqual(client.requests_used, 3)

    def test_long_retry_after_stops_without_early_retry(self):
        error = urllib.error.HTTPError("url", 429, "secret", {"Retry-After": "99999"}, None)
        client = self.client([{"access_token": "t", "expires_in": 7200}, error])
        delays = []
        client._sleep = delays.append
        with self.assertRaisesRegex(EbayError, "later retry"):
            client.search("pokemon")
        self.assertEqual(delays, [])
        self.assertEqual(client.requests_used, 1)

    def test_nonfinite_retry_after_uses_bounded_backoff(self):
        error = urllib.error.HTTPError("url", 429, "secret", {"Retry-After": "nan"}, None)
        client = self.client([{"access_token": "t", "expires_in": 7200}, error, {}])
        delays = []
        client._sleep = delays.append
        client.search("pokemon")
        self.assertEqual(delays, [1])

    def test_future_retry_after_date_stops(self):
        error = urllib.error.HTTPError("url", 429, "secret", {"Retry-After": "Thu, 01 Jan 2099 00:00:00 GMT"}, None)
        client = self.client([{"access_token": "t", "expires_in": 7200}, error])
        with self.assertRaisesRegex(EbayError, "later retry"):
            client.search("pokemon")
        self.assertEqual(client.requests_used, 1)

    def test_redirect_handler_never_forwards_credentials(self):
        request = urllib.request.Request("https://api.ebay.com/path", headers={"Authorization": "Bearer secret"})
        with self.assertRaisesRegex(EbayError, "redirects are disabled"):
            _NoRedirect().redirect_request(request, None, 302, "Found", {}, "https://untrusted.invalid/")

    def test_budget_stops_before_another_request(self):
        client = self.client([{"access_token": "t", "expires_in": 7200}, {}], max_requests=1)
        client.search("pokemon")
        with self.assertRaises(EbayBudgetError):
            client.search("pokemon")
        self.assertEqual(len(self.calls), 2)

    def test_errors_are_sanitized(self):
        client = self.client([RuntimeError("fixture-secret")])
        with self.assertRaises(EbayError) as result:
            client.search("pokemon")
        self.assertNotIn("fixture-secret", str(result.exception))

    def test_bad_input_never_calls_transport(self):
        client = self.client([])
        for options in ({"market": "XX"}, {"max_pages": 11}, {"limit": 0}):
            with self.assertRaises(ValueError):
                client.search("pokemon", **options)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()

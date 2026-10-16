import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pydantic import ValidationError
from api.models import ScrapeRequest


class EbayBlockTests(unittest.TestCase):
    def test_ebay_hosts_rejected_before_queueing(self):
        for url in ("https://www.ebay.de/itm/1", "https://ebay.com/x", "https://i.ebayimg.com/a.jpg", "https://WWW.EBAY.CO.UK/"):
            with self.assertRaises(ValidationError):
                ScrapeRequest(url=url)
        self.assertEqual(ScrapeRequest(url="https://example.com/ebay").url, "https://example.com/ebay")
        self.assertEqual(ScrapeRequest(url="https://notebay.com/").url, "https://notebay.com/")


if __name__ == "__main__":
    unittest.main()

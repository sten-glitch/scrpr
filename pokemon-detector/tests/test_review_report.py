"""Offline tests for private HTML visual review report."""
import base64
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from review_report import render_report

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+y0QcAAAAASUVORK5CYII="
)


def result():
    return {
        "listing_id": "manual:<script>alert(1)</script>",
        "listing_url": "https://example.org/lot?id=%3Cscript%3E",
        "image_manifest": [{"index": 0, "source_type": "url",
                            "reference": "https://i.ebayimg.com/images/g/test/photo.jpg"}],
        "assessment": {"decision": "REVIEW", "asking_eur": 45.0, "net_profit_eur": None,
                       "roi": None, "warnings": ["Condition unclear"]},
        "visual_evidence": {"observations": [{
            "image_index": 0, "bbox_xyxy": [.10, .2, .6, .9],
            "name": "Pikachu <svg onload=alert(1)>",
            "set": "151", "number": "025/165",
            "language": "en", "finish": "holo", "condition": "unknown",
            "flags": ["possible_stock_photo"],
        }]},
        "catalog_resolutions": [{"identity_key":"tcgdex:sv03.5-025-holo-en-raw"}],
        "inventory_review": {
            "quantity_lower_bound_if_detections_correct": 1,
            "quantity_upper_bound_if_detections_correct": 2,
            "groups_requiring_review": 1,
            "groups": [{"identity_group":"some-id", "review_required":True,
                        "possible_distinct_copies_min":1, "possible_distinct_copies_max":2,
                        "image_indices":[0, 1]}],
        },
        "open_questions": ["Are we seeing the same physical card twice?"],
    }


class TestReport(unittest.TestCase):
    def test_sanitized_html_escapes_untrusted_data(self):
        page = render_report(result())
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertNotIn("<svg onload", page)
        self.assertNotIn("<script>", page)
        self.assertIn("Pikachu &lt;svg onload=alert(1)&gt;", page)
        self.assertIn("width:50.000%;height:70.000%", page)
        self.assertIn("possible_stock_photo", page)
        self.assertIn("necunoscut", page)
        self.assertIn("Inventar fizic", page)
        self.assertIn("nu validează", page)

    def test_local_photo_only_embedded_when_opted_in(self):
        with tempfile.TemporaryDirectory() as t:
            photo = Path(t) / "mycard.png"
            photo.write_bytes(PNG)
            info = result()
            info["image_manifest"] = [{"index":0, "source_type":"local",
                                       "reference":"mycard.png"}]
            unembedded = render_report(info)
            self.assertIn("Imaginea nu este inclusă", unembedded)
            self.assertNotIn("data:image/png;base64", unembedded)
            embedded = render_report(info, photo_dir=t)
            self.assertIn("data:image/png;base64,", embedded)
            self.assertIn("Fotografii și observații", embedded)

    def test_invalid_boxes_not_rendered(self):
        d = result()
        d["visual_evidence"]["observations"][0]["bbox_xyxy"] = [-2, .1, .4, .5]
        page = render_report(d)
        self.assertNotIn("class='bound'", page)

    def test_unknown_roi_never_described_as_a_confirmed_return(self):
        d = result()
        d["assessment"]["decision"] = "REVIEW"
        d["assessment"]["net_profit_eur"] = None
        d["assessment"]["roi"] = None
        page = render_report(d)
        self.assertIn("Profit net documentat", page)
        self.assertIn("necunoscut", page)
        self.assertIn("Necesită verificare", page)


if __name__ == "__main__":
    unittest.main()

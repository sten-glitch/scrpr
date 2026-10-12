"""No-network tests for BIGSTEN's rights-aware Commons/Roboflow source adapters."""
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from external_photo_sources import (
    SOURCES, PhotoSourceError, _allowed_commons_license,
    _public_commons_image_url, discover_commons, import_commons,
    download_roboflow,
)

PHOTO_PAYLOAD={
    "query":{"pages":{
        "11":{"title":"File:Pokemon cards table.jpg",
              "imageinfo":[{"url":"https://upload.wikimedia.org/example.jpg",
                            "thumburl":"https://upload.wikimedia.org/thumbs/example.jpg",
                            "extmetadata":{
                                "LicenseShortName":{"value":"CC BY-SA 4.0"},
                                "LicenseUrl":{"value":"https://creativecommons.org/licenses/by-sa/4.0/"},
                                "Artist":{"value":"<a href='/artist'>Photographer &amp; creator</a>"},
                            }}]},
        "12":{"title":"File:Pokemon proprietary logo.png",
              "imageinfo":[{"url":"https://upload.wikimedia.org/logo.png",
                            "extmetadata":{"LicenseShortName":{"value":"Fair use"}}}]},
        "13":{"title":"File:Pokemon card event.svg",
              "imageinfo":[{"url":"https://upload.wikimedia.org/event.svg",
                            "extmetadata":{"LicenseShortName":{"value":"CC BY 4.0"}}}]},
    }}
}


class TestExternalPhotoSources(unittest.TestCase):
    def test_source_registry_and_rights(self):
        self.assertEqual(SOURCES["detector"]["photos_reported"],494)
        self.assertFalse(SOURCES["detector"]["identity_labels"])
        self.assertEqual(SOURCES["binder"]["license_displayed"],"CC BY 4.0")
        self.assertTrue(_allowed_commons_license("CC BY-SA 4.0"))
        self.assertTrue(_allowed_commons_license("CC0"))
        self.assertFalse(_allowed_commons_license("CC BY-NC 4.0"))
        self.assertFalse(_allowed_commons_license("Fair use"))
        self.assertFalse(_allowed_commons_license("unknown"))

    def test_reject_bad_image_hosts_and_schemes(self):
        for url in (
            "http://upload.wikimedia.org/path.jpg",
            "https://upload.wikimedia.org.evil.example/path.jpg",
            "https://example.com/evil.jpg",
            "https://127.0.0.1/private.png",
            "https://upload.wikimedia.org:81/file.jpg",
            "https://evil.example@upload.wikimedia.org/file.jpg",
        ):
            with self.subTest(url=url),self.assertRaises(PhotoSourceError):
                _public_commons_image_url(url)
        self.assertEqual(_public_commons_image_url(
            "https://upload.wikimedia.org/path.jpg"),"https://upload.wikimedia.org/path.jpg")

    def test_commons_metadata_keeps_attribution_but_not_card_identity(self):
        with patch("external_photo_sources._request_json", return_value=PHOTO_PAYLOAD):
            records=discover_commons(limit=10)
        self.assertEqual(len(records),1)
        r=records[0]
        self.assertEqual(r["license"],"CC BY-SA 4.0")
        self.assertEqual(r["author"],"Photographer & creator")
        self.assertFalse(r["identity_confirmed"])
        self.assertFalse(r["copyright_subcontents_reviewed"])
        self.assertIn("source_page",r)

    def test_commons_dry_run_does_not_fetch_images(self):
        with patch("external_photo_sources._request_json", return_value=PHOTO_PAYLOAD),\
             patch("external_photo_sources._safe_image_download") as downloader:
            result=import_commons(10,"no-write-should-happen",dry_run=True)
        downloader.assert_not_called()
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["benchmark_ready"])
        self.assertEqual(result["items"][0]["status"],"CANDIDATE_NOT_DOWNLOADED")

    def test_commons_import_private_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as parent:
            dest=Path(parent)/"private"/"commons"
            with patch("external_photo_sources._request_json",return_value=PHOTO_PAYLOAD),\
                 patch("external_photo_sources._safe_image_download",
                       return_value=b"\xff\xd8\xffFAKE\xff\xd9"):
                result=import_commons(10,dest)
            self.assertEqual(len(result["items"]),1)
            self.assertFalse(result["identity_verified"])
            self.assertTrue((dest/result["items"][0]["image_file"]).is_file())
            manifest=json.loads((dest/"SOURCE_ATTRIBUTION.json").read_text())
            self.assertEqual(manifest["items"][0]["license"],"CC BY-SA 4.0")
            self.assertFalse(manifest["commercial_rights_cleared"] if "commercial_rights_cleared" in manifest else False)
            with patch("external_photo_sources._request_json",return_value=PHOTO_PAYLOAD):
                with self.assertRaisesRegex(PhotoSourceError,"refusing overwrite"):
                    import_commons(10,dest,dry_run=False)

    def test_roboflow_requires_environment_key_without_side_effects(self):
        with patch.dict(os.environ,{"ROBOFLOW_API_KEY":""}):
            with self.assertRaisesRegex(PhotoSourceError,"API key"):
                download_roboflow("detector")
        with self.assertRaises(PhotoSourceError):
            download_roboflow("unknown")

    def test_official_roboflow_adapter_never_exposes_key_in_manifest(self):
        with tempfile.TemporaryDirectory() as parent:
            dest=Path(parent)/"web-research"/"roboflow-detector"
            dest.mkdir(parents=True)
            (dest/"data.yaml").write_text("names: ['card']\n")
            provider=Mock()
            provider.workspace.return_value.project.return_value.version.return_value.download.return_value.location=str(dest)
            with patch.dict(os.environ,{"ROBOFLOW_API_KEY":"TEST_SECRET_DO_NOT_SAVE"}),\
                 patch.dict(sys.modules,{"roboflow":types.SimpleNamespace(Roboflow=lambda api_key:provider)}):
                # Existing directory with data.yaml is a protected destination:
                with self.assertRaisesRegex(PhotoSourceError,"overwrite"):
                    download_roboflow("detector",Path(parent)/"web-research")
            (dest/"data.yaml").unlink()
            dest.rmdir()
            def create_export(_format,location,overwrite):
                target=Path(location)
                target.mkdir(parents=True,exist_ok=True)
                (target/"data.yaml").write_text("names: ['card']\n")
                return types.SimpleNamespace(location=str(target))
            provider.workspace.return_value.project.return_value.version.return_value.download.side_effect=create_export
            with patch.dict(os.environ,{"ROBOFLOW_API_KEY":"TEST_SECRET_DO_NOT_SAVE"}),\
                 patch.dict(sys.modules,{"roboflow":types.SimpleNamespace(Roboflow=lambda api_key:provider)}):
                result=download_roboflow("detector",Path(parent)/"web-research")
            self.assertFalse(result["benchmark_ready"])
            self.assertFalse(result["dataset_original_artwork_rights_verified"])
            text=(dest/"SOURCE_ATTRIBUTION.json").read_text()
            self.assertNotIn("TEST_SECRET_DO_NOT_SAVE",text)
            self.assertIn("pokemon-card-detector-gksmy",text)


if __name__=="__main__":
    unittest.main()

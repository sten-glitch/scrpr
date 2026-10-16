import io
import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ebay_auth_check as diag

GOOD = {'EBAY_PRODUCTION_CLIENT_ID': 'Example-App-PRD-1a2b3c4d5-6e7f8a9b',
        'EBAY_PRODUCTION_CLIENT_SECRET': 'PRD-1a2b3c4d5e6f-7a8b-9c0d-1e2f-3a4b'}


def run(env, raw=None, **kw):
    with patch.dict(os.environ, env, clear=True), patch('ebay_auth_check.load_ebay_config'):
        r = diag.check('production', raw_file=raw if raw is not None else {})
        if kw.get('transport'):
            with patch('local_config.load_ebay_config'):
                r.update(diag.live('production', transport=kw['transport']))
        return r


class AuthCheckTests(unittest.TestCase):
    def test_good_config_has_no_problems_and_never_prints_values(self):
        r = run(GOOD)
        self.assertEqual(r['config_problems'], [])
        self.assertTrue(r['basic_auth_roundtrip_ok'])
        self.assertTrue(r['token_endpoint'].startswith('https://api.ebay.com/identity'))
        dumped = json.dumps(r)
        for v in GOOD.values():
            self.assertNotIn(v, dumped)
            self.assertNotIn(v[:12], dumped)

    def test_detects_sandbox_keys_swapped_values_and_whitespace(self):
        sbx = {'EBAY_PRODUCTION_CLIENT_ID': 'Example-App-SBX-1-2', 'EBAY_PRODUCTION_CLIENT_SECRET': 'SBX-1-2'}
        self.assertIn('looks_like_other_environment', run(sbx)['config_problems'])
        swapped = {'EBAY_PRODUCTION_CLIENT_ID': GOOD['EBAY_PRODUCTION_CLIENT_SECRET'], 'EBAY_PRODUCTION_CLIENT_SECRET': 'x'}
        self.assertIn('looks_swapped_id_and_secret', run(swapped)['config_problems'])
        raw = {'EBAY_PRODUCTION_CLIENT_ID': ' "' + GOOD['EBAY_PRODUCTION_CLIENT_ID'] + '"'}
        self.assertIn('env_file_has_spaces_or_quotes', run(GOOD, raw)['config_problems'])
        self.assertIn('cert_id_present', run({'EBAY_PRODUCTION_CLIENT_ID': 'a-PRD-b'})['config_problems'])

    def test_process_variable_overriding_env_file(self):
        raw = {'EBAY_PRODUCTION_CLIENT_ID': 'Old-App-PRD-0-0'}
        self.assertIn('process_env_overrides_env_file', run(GOOD, raw)['config_problems'])
        raw = {'EBAY_PRODUCTION_CLIENT_ID': GOOD['EBAY_PRODUCTION_CLIENT_ID']}
        self.assertNotIn('process_env_overrides_env_file', run(GOOD, raw)['config_problems'])

    def test_live_invalid_client_is_explained_without_body(self):
        def transport(url, **kw):
            body = io.BytesIO(b'{"error":"invalid_client","error_description":"secret-ish detail"}')
            raise urllib.error.HTTPError(url, 401, 'Unauthorized', {}, body)
        r = run(GOOD, transport=transport)
        self.assertEqual((r['auth'], r['http_status'], r['oauth_error']), ('failed', 401, 'invalid_client'))
        self.assertIn('not enabled', diag.explain(r))
        self.assertNotIn('secret-ish', json.dumps(r))

    def test_live_success(self):
        r = run(GOOD, transport=lambda url, **kw: {'access_token': 't', 'expires_in': 7200})
        self.assertEqual(r['auth'], 'success')


if __name__ == '__main__':
    unittest.main()

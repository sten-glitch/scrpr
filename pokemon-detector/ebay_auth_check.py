"""eBay OAuth diagnostics. Prints booleans, markers and sanitized error codes only; never values.

    python ebay_auth_check.py            # offline configuration checks
    python ebay_auth_check.py --live     # plus one client-credentials token request per environment
"""
import argparse
import base64
import json
import os
import urllib.error

from local_config import CONFIG_PATH, load_ebay_config

MARKER = {'production': 'PRD', 'sandbox': 'SBX'}
OAUTH_ERRORS = {'invalid_client', 'invalid_request', 'invalid_scope', 'unauthorized_client', 'unsupported_grant_type'}


def _file_values(path=CONFIG_PATH):
    """Raw .env values (before stripping) so whitespace/quote problems are visible."""
    raw = {}
    if os.path.exists(path):
        for line in open(path, encoding='utf-8-sig'):
            key, sep, value = line.rstrip('\r\n').partition('=')
            if sep and key.strip().startswith('EBAY_'):
                raw[key.strip()] = value
    return raw


def _clean(value):
    value = value.strip()  # same normalization as local_config.load_ebay_config
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'' else value


def check(environment, raw_file=None):
    raw_file = _file_values() if raw_file is None else raw_file
    prefix = 'EBAY_' + environment.upper()
    load_ebay_config()
    app_id, cert_id = os.environ.get(prefix + '_CLIENT_ID', ''), os.environ.get(prefix + '_CLIENT_SECRET', '')
    other = MARKER['sandbox' if environment == 'production' else 'production']
    result = {
        'environment': environment,
        'token_endpoint': ('https://api.ebay.com' if environment == 'production' else 'https://api.sandbox.ebay.com') + '/identity/v1/oauth2/token',
        'scope': 'https://api.ebay.com/oauth/api_scope',
        'app_id_present': bool(app_id), 'cert_id_present': bool(cert_id),
        # load_ebay_config uses setdefault: an existing process variable silently overrides .env.
        'process_env_overrides_env_file': any(prefix + k in raw_file and _clean(raw_file[prefix + k]) != os.environ.get(prefix + k)
                                              for k in ('_CLIENT_ID', '_CLIENT_SECRET')),
        'env_file_has_spaces_or_quotes': any(v != v.strip() or v.strip()[:1] in '"\'' for k, v in raw_file.items() if k.startswith(prefix)),
        'value_has_internal_whitespace': any(any(c.isspace() for c in v) for v in (app_id, cert_id)),
        'app_id_contains_colon': ':' in app_id,  # breaks HTTP Basic client_id:client_secret
        'app_id_marker_matches': f'-{MARKER[environment]}-' in app_id,
        'cert_id_marker_matches': cert_id.startswith(MARKER[environment] + '-'),
        'looks_like_other_environment': f'-{other}-' in app_id or cert_id.startswith(other + '-'),
        'looks_swapped_id_and_secret': app_id.startswith(('PRD-', 'SBX-')) and not cert_id.startswith(('PRD-', 'SBX-')),
    }
    if app_id and cert_id:
        pair = app_id + ':' + cert_id
        result['basic_auth_roundtrip_ok'] = base64.b64decode(base64.b64encode(pair.encode())).decode() == pair
    problems = [k for k in ('process_env_overrides_env_file', 'env_file_has_spaces_or_quotes', 'value_has_internal_whitespace',
                            'app_id_contains_colon', 'looks_like_other_environment', 'looks_swapped_id_and_secret') if result[k]]
    problems += [k for k in ('app_id_present', 'cert_id_present') if not result[k]]
    # Markers are eBay's documented key format; treat a mismatch as a strong hint, not proof.
    problems += [k for k in ('app_id_marker_matches', 'cert_id_marker_matches') if app_id and cert_id and not result[k]]
    result['config_problems'] = problems
    return result


def live(environment, transport=None):
    from ebay_discovery import EbayClient, _transport
    out = {}
    def diag(url, **kw):
        try:
            return (transport or _transport)(url, **kw)
        except urllib.error.HTTPError as e:
            out['http_status'] = e.code
            try:
                code = json.loads(e.read(32768)).get('error')
            except Exception:
                code = None
            out['oauth_error'] = code if code in OAUTH_ERRORS else 'other'
            raise
        except Exception as e:
            out['network_error'] = type(e).__name__
            raise
    try:
        EbayClient(environment, max_requests=1, transport=diag)._access_token()
        out['auth'] = 'success'
    except Exception:
        out['auth'] = 'failed'
    return out


def explain(r):
    if r.get('auth') == 'success':
        return 'Authentication works for this keyset.'
    if r['config_problems']:
        return 'Fix configuration first: ' + ', '.join(r['config_problems'])
    if r.get('oauth_error') == 'invalid_client':
        return ('Configuration looks well-formed, so eBay rejected the keyset itself: wrong/regenerated Cert ID, '
                'or the Production keyset is not enabled (Marketplace Account Deletion compliance pending). '
                'Code changes cannot enable a disabled keyset; check Application Keys in the eBay Developer Portal.')
    if 'network_error' in r:
        return 'eBay was not reachable from this machine; rerun where api.ebay.com is reachable.'
    return 'Run with --live to test authentication.'


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--live', action='store_true', help='Send one token request per environment')
    p.add_argument('--environment', choices=('sandbox', 'production', 'both'), default='both')
    args = p.parse_args(argv)
    for env in (('sandbox', 'production') if args.environment == 'both' else (args.environment,)):
        r = check(env)
        if args.live and r['app_id_present'] and r['cert_id_present']:
            r.update(live(env))
        r['diagnosis'] = explain(r)
        print(json.dumps(r, indent=2))


if __name__ == '__main__':
    main()

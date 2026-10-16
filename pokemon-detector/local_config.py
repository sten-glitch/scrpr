"""Load only local eBay settings, without interpolation, execution or logging values."""
import os
from pathlib import Path

KEYS = ('EBAY_SANDBOX_CLIENT_ID', 'EBAY_SANDBOX_CLIENT_SECRET',
        'EBAY_PRODUCTION_CLIENT_ID', 'EBAY_PRODUCTION_CLIENT_SECRET', 'EBAY_ENVIRONMENT',
        'EBAY_DELETION_VERIFICATION_TOKEN', 'EBAY_DELETION_ENDPOINT')
CONFIG_PATH = Path(__file__).resolve().parent / '.env'


def load_ebay_config(path=CONFIG_PATH):
    path = Path(path)
    if not path.exists():
        return
    if path.stat().st_size > 16384:
        raise ValueError('Local eBay configuration exceeds size limit')
    parsed = {}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if not separator or key not in KEYS:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if '\x00' in value or '\r' in value or '\n' in value:
            raise ValueError('Invalid local eBay configuration')
        if value:
            parsed[key] = value
    for key, value in parsed.items():
        os.environ.setdefault(key, value)


def credential_status():
    load_ebay_config()
    return {key: bool(os.environ.get(key)) for key in KEYS if key.endswith(('_CLIENT_ID', '_CLIENT_SECRET'))}

if __name__ == '__main__':
    import json
    print(json.dumps(credential_status(), indent=2))

"""Explicit read-only eBay validation; prints counters/status only, never tokens."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from ebay_discovery import EbayClient
from local_config import credential_status
from graded_identity import metadata_prefilter
from unique_supply import aggregate_supply

QUERIES = ('Pokemon Charizard PSA 10', 'Pokemon Pikachu PSA 10 Japanese',
           'Pokemon Umbreon PSA 10', 'Pokemon Charizard BGS 9.5', 'Pokemon CGC 10 Japanese')


def validate(production_searches=False):
    report={'timestamp':datetime.now(timezone.utc).isoformat(), 'credentials_present':credential_status(),
            'environments':{},'paid_ai_calls':0,'images_downloaded':0}
    for environment in ('sandbox','production'):
        start=time.perf_counter(); row={'auth':'not_attempted','searches':[]}
        client=None
        prefix='EBAY_'+environment.upper()
        if not all(report['credentials_present'][prefix+s] for s in ('_CLIENT_ID','_CLIENT_SECRET')):
            row['blocked']='missing_credentials'
            report['environments'][environment]=row
            continue
        try:
            client=EbayClient(environment,max_requests=20)
            row['auth']='attempted'
            client._access_token()
            before=client.oauth_requests_used
            client._access_token()
            row.update(auth='success', token_cache_reused=client.oauth_requests_used==before,
                       scope='https://api.ebay.com/oauth/api_scope')
            observations=[]
            if environment=='production' and production_searches:
                for market in ('EBAY_GB','EBAY_US','EBAY_DE'):
                    for query in QUERIES:
                        started=time.perf_counter()
                        try:
                            result=client.search(query,market,limit=20,max_pages=1)
                            kept=[i for i in result['items'] if metadata_prefilter(i)['status']=='CANDIDATE']
                            row['searches'].append({'market':market,'query':query,'coverage':result['coverage'],
                                                   'candidate_count':len(kept),'latency_ms':round((time.perf_counter()-started)*1000,2)})
                            observations.extend({'marketplace':market,'item_id':i['itemId']} for i in kept)
                        except Exception as error:
                            row['searches'].append({'market':market,'query':query,'error_type':type(error).__name__})
                row['metadata_only_supply']=aggregate_supply(observations)['counts']
                row['limitation']='No image permission or human-confirmed certificates; no physical-card merges asserted'
        except Exception as error:
            if row['auth']=='attempted':
                row['auth']='failed'
            row['error_type']=type(error).__name__
        row['elapsed_ms']=round((time.perf_counter()-start)*1000,2)
        row['browse_requests']=client.requests_used if client else 0
        row['oauth_requests']=client.oauth_requests_used if client else 0
        report['environments'][environment]=row
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--production-searches',action='store_true')
    parser.add_argument('--out',type=Path,default=Path('private/ebay-live-validation.json'))
    args=parser.parse_args()
    report=validate(args.production_searches)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))

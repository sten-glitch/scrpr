import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from local_config import load_ebay_config
from catalog_download import card_entries

class ValidationTests(unittest.TestCase):
    def test_credentials_do_not_override_environment_or_enable_paid_ai(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'EBAY_SANDBOX_CLIENT_ID':'process'}, clear=True):
            p=Path(temp)/'.env'
            p.write_text('EBAY_SANDBOX_CLIENT_ID=file\nEBAY_PRODUCTION_CLIENT_SECRET="test-secret"\nBIGSTEN_PAID_VISION_AUTHORIZED=1\n')
            load_ebay_config(p)
            self.assertEqual(os.environ['EBAY_SANDBOX_CLIENT_ID'], 'process')
            self.assertEqual(os.environ['EBAY_PRODUCTION_CLIENT_SECRET'], 'test-secret')
            self.assertNotIn('BIGSTEN_PAID_VISION_AUTHORIZED', os.environ)

    def test_catalog_preserves_japanese_editions_and_missing_variants(self):
        card={'id':'PMCG1-001','name':'フシギダネ','localId':'001','set':{'id':'PMCG1','name':'拡張パック'},'variants_detailed':[
            {'variantId':'a','type':'normal'}, {'variantId':'b','type':'normal','subtype':'no-rarity'}]}
        rows=card_entries(card,'ja','https://api.tcgdex.net/v2/ja/cards/PMCG1-001','digest')
        self.assertEqual(len({r['identity_key'] for r in rows}),2)
        self.assertNotEqual(rows[0]['finish'],rows[1]['finish'])
        self.assertEqual(rows[0]['name'],'フシギダネ')
        card.pop('variants_detailed')
        self.assertEqual(card_entries(card,'ja','url','digest'),[])

    def test_pair_metrics_penalize_false_merges_and_abstentions(self):
        from benchmark_supply import benchmark_pairs
        from tests.test_unique_supply import listing
        rows=[listing('a'),listing('b'),listing('c','different')]
        pairs=[{'a':['ebay','a'],'b':['ebay','b'],'same_physical_item':False,'reviewer':'fixture','truth_source':'synthetic'},
               {'a':['ebay','a'],'b':['ebay','c'],'same_physical_item':True,'reviewer':'fixture','truth_source':'synthetic'}]
        report=benchmark_pairs(rows,pairs)
        self.assertEqual(report['false_positive'],1)
        self.assertEqual(report['false_negative'],1)
        self.assertEqual(report['duplicate_precision'],0)
        self.assertEqual(report['false_merge_rate_among_predicted_merges'],1)

import copy
import json
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unique_supply import aggregate_supply


def listing(item, number='00123', **extra):
    return {'marketplace': 'ebay', 'item_id': item, 'identity_key': 'base:4:unlimited',
            'grade': '10', 'certificate': {'grader': 'PSA', 'number': number,
                'evidence_status': 'human_confirmed', 'source': 'photographed_label',
                'provenance': 'review:' + item}, **extra}


class SupplyTests(unittest.TestCase):
    def test_three_matching_certificates_and_repeated_item(self):
        rows = [listing('a'), listing('b'), listing('c'), listing('a')]
        report = aggregate_supply(rows)
        self.assertEqual(report['counts']['unique_listings'], 3)
        self.assertEqual(report['counts']['confirmed_certificate_groups'], 1)
        self.assertEqual(report['counts']['certificate_duplicate_listings'], 2)
        self.assertEqual(report['counts']['repeated_item_observations'], 1)
        self.assertEqual(report['groups'][0]['certificate']['number'], '00123')
        self.assertEqual(report, aggregate_supply(list(reversed(rows))))

    def test_different_certificates_and_graders_stay_distinct(self):
        rows = [listing('a'), listing('b', '00124'), listing('c')]
        rows[2]['certificate']['grader'] = 'CGC'
        self.assertEqual(len(aggregate_supply(rows)['groups']), 3)

    def test_same_certificate_different_card_or_grade_quarantines_all(self):
        for change in [{'identity_key': 'other'}, {'grade': '9'}]:
            with self.subTest(change=change):
                report = aggregate_supply([listing('a'), listing('b'), listing('c', **change)])
                self.assertEqual(report['counts']['confirmed_certificate_groups'], 0)
                self.assertEqual(report['counts']['unresolved_listings'], 3)
                self.assertEqual(report['counts']['conflicting_certificate_ids'], 1)

    def test_conflicting_same_item_preserved_and_taints_both_certificates(self):
        report = aggregate_supply([listing('a'), listing('a', '456'), listing('b'), listing('c', '456')])
        self.assertEqual(report['counts']['unique_listings'], 3)
        self.assertEqual(report['counts']['confirmed_certificate_groups'], 0)
        self.assertEqual(report['counts']['conflicting_certificate_ids'], 2)

    def test_recycled_photo_does_not_merge_missing_evidence(self):
        rows = [{'marketplace': 'ebay', 'item_id': s, 'image_sha256': 'a' * 64} for s in 'abc']
        result = aggregate_supply(rows)
        self.assertEqual(result['counts']['unresolved_listings'], 3)
        self.assertEqual(len(result['reused_photos']), 1)
        self.assertEqual(result['conditional_observed_identity_bounds']['lower'], 1)
        self.assertEqual(result['conditional_observed_identity_bounds']['upper'], 3)

    def test_text_and_ocr_confidence_cannot_confirm(self):
        for field, value in [('evidence_status', 'ocr'), ('source', 'seller_title'),
                             ('provenance', ''), ('number', 123)]:
            row = listing('a')
            row['certificate'][field] = value
            row['certificate']['confidence'] = 1.0
            self.assertEqual(aggregate_supply([row])['counts']['confirmed_certificate_groups'], 0)
        self.assertEqual(aggregate_supply([listing('a')], accepted_evidence_statuses=[])['counts']['unresolved_listings'], 1)

    def test_prices_currency_separated_repeats_dedup_and_conflicts_excluded(self):
        rows = [listing('a', price={'amount': 10, 'currency': 'EUR'}),
                listing('b', price={'amount': 20, 'currency': 'EUR'}),
                listing('c', price={'amount': 100, 'currency': 'USD'})]
        rows += [copy.deepcopy(rows[0])]
        result = aggregate_supply(rows)
        self.assertEqual(result['prices_by_currency']['EUR'], {
            'listing_count': 2, 'median_asking_price': 15, 'cheapest_asking_price': 10})
        rows.append(listing('a', price={'amount': 30, 'currency': 'EUR'}))
        result = aggregate_supply(rows)
        self.assertEqual(result['prices_by_currency']['EUR']['listing_count'], 1)
        self.assertEqual(len(result['price_conflict_listings']), 1)

    def test_empty_and_missing_ids(self):
        result = aggregate_supply([])
        self.assertEqual(result['conditional_observed_identity_bounds']['upper'], 0)
        with self.assertRaises(ValueError):
            aggregate_supply([{}])
        with self.assertRaises(ValueError):
            aggregate_supply([listing('a')], accepted_evidence_statuses=['seller_claim'])

    def test_invalid_optional_evidence_and_prices_do_not_confirm_or_emit_nan(self):
        row = listing('a', price={'amount': '1e999', 'currency': 'EUR'})
        row['certificate']['evidence_status'] = []
        report = aggregate_supply([row])
        self.assertEqual(report['counts']['unresolved_listings'], 1)
        self.assertEqual(report['prices_by_currency'], {})
        json.dumps(report, allow_nan=False)

    def test_ebay_marketplace_views_deduplicate_and_keep_provenance(self):
        rows = [listing('v1|123|0', marketplace=market) for market in ('EBAY_US', 'EBAY_GB', 'EBAY_DE')]
        result = aggregate_supply(rows)
        self.assertEqual(result['counts']['unique_listings'], 1)
        member = result['groups'][0]['members'][0]
        self.assertEqual(member['observed_marketplaces'], ['ebay_de', 'ebay_gb', 'ebay_us'])
        self.assertEqual(len(result['groups'][0]['evidence']), 3)
        self.assertEqual(result, aggregate_supply(rows[::-1]))
        for row in rows:
            row.pop('certificate')
        rows += [{'marketplace': 'unknown_a', 'item_id': 'v1|123|0'},
                 {'marketplace': 'unknown_b', 'item_id': 'v1|123|0'}]
        self.assertEqual(aggregate_supply(rows)['counts']['unique_listings'], 3)

    def test_invalid_grader_grade_and_certificate_format_remain_unresolved(self):
        for field, value in [('grader', 'FAKE'), ('number', '１２３'), ('number', '12a'),
                             ('number', '12 34')]:
            row = listing('a')
            row['certificate'][field] = value
            self.assertEqual(aggregate_supply([row])['counts']['unresolved_listings'], 1)
        for grade in ['99', 'NaN', 'Infinity', 0, -1]:
            self.assertEqual(aggregate_supply([listing('a', grade=grade)])['counts']['unresolved_listings'], 1)
        rows = [listing('a'), listing('b')]
        rows[0]['certificate']['grader'] = 'Beckett'
        rows[1]['certificate']['grader'] = 'BGS'
        self.assertEqual(aggregate_supply(rows)['counts']['confirmed_certificate_groups'], 1)

    def test_reused_photo_different_certificates_flagged_but_not_merged(self):
        rows = [listing('a', image_sha256='a' * 64), listing('b', '456', image_sha256='a' * 64)]
        result = aggregate_supply(rows)
        self.assertTrue(result['reused_photos'][0]['different_certificate_conflict'])
        self.assertEqual(result['counts']['confirmed_certificate_groups'], 2)
        self.assertEqual(result['counts']['conflicting_certificate_ids'], 0)

    def test_same_item_currency_views_have_separate_prices(self):
        rows = [listing('a', marketplace='EBAY_US', price={'amount': 15, 'currency': 'USD'}),
                listing('a', marketplace='EBAY_DE', price={'amount': 12, 'currency': 'EUR'})]
        report = aggregate_supply(rows)
        self.assertEqual(report['counts']['unique_listings'], 1)
        self.assertEqual(report['prices_by_currency']['EUR']['cheapest_asking_price'], 12)
        self.assertEqual(report['prices_by_currency']['USD']['cheapest_asking_price'], 15)
        self.assertEqual(report['price_conflict_listings'], [])

    def test_invalid_repeated_grade_quarantines_accepted_certificate(self):
        for invalid in ['99', 'NaN', 'Infinity', 0, -1, True]:
            with self.subTest(grade=invalid):
                rows = [listing('a'), listing('a', grade=invalid), listing('b')]
                report = aggregate_supply(rows)
                self.assertEqual(report['counts']['confirmed_certificate_groups'], 0)
                self.assertEqual(report['counts']['unresolved_listings'], 2)
                self.assertTrue(any('invalid_grade_observation' in g['reasons'] for g in report['groups']))

    def test_groups_disclose_attestation_not_independent_verification(self):
        group = aggregate_supply([listing('a')])['groups'][0]
        self.assertEqual(group['verification_status'], 'unavailable')
        self.assertEqual(group['confidence_kind'], 'explicit_attestation')
        row = listing('a')
        row.pop('certificate')
        group = aggregate_supply([row])['groups'][0]
        self.assertEqual(group['verification_status'], 'unavailable')
        self.assertEqual(group['confidence_kind'], 'insufficient_evidence')


if __name__ == '__main__':
    unittest.main()

"""Evaluate predicted dedup groups against separately annotated listing pairs."""
import argparse
import json
from pathlib import Path
from unique_supply import aggregate_supply


def benchmark_pairs(listings, pairs):
    report = aggregate_supply(listings)
    groups = {(m['marketplace'], m['item_id']): g['group_id'] for g in report['groups'] for m in g['members']}
    tp = fp = fn = tn = 0
    seen = set()
    if not pairs:
        raise ValueError('Independent human-labeled pairs are required')
    for pair in pairs:
        a, b = tuple(pair['a']), tuple(pair['b'])
        key = tuple(sorted((a, b)))
        if a == b or key in seen or a not in groups or b not in groups:
            raise ValueError('Pair must refer to distinct, known listings and occur once')
        if type(pair.get('same_physical_item')) is not bool or not pair.get('reviewer') or not pair.get('truth_source'):
            raise ValueError('Pair requires independent truth and provenance')
        seen.add(key)
        same = groups[a] == groups[b]
        truth = pair['same_physical_item']
        tp += same and truth
        fp += same and not truth
        fn += not same and truth
        tn += not same and not truth
    return {'labeled_pairs':len(pairs), 'true_positive':tp, 'false_positive':fp,
            'false_negative':fn, 'true_negative':tn,
            'duplicate_precision':tp/(tp+fp) if tp+fp else None,
            'duplicate_recall':tp/(tp+fn) if tp+fn else None,
            'false_merge_rate_among_predicted_merges':fp/(tp+fp) if tp+fp else None,
            'false_positive_rate_among_distinct_pairs':fp/(fp+tn) if fp+tn else None,
            'scope':'Selected annotated pairs only; ground truth must be independent of extracted certificates',
            'supply':report['counts']}

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args()
    data=json.loads(args.input.read_text(encoding='utf-8'))
    result=benchmark_pairs(data['listings'],data['pairs'])
    args.out.write_text(json.dumps(result,indent=2),encoding='utf-8')

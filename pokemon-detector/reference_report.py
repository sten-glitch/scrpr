"""Render a private local benchmark audit as readable, offline HTML.

No photo assets, URLs, scripts or external libraries. Strings are HTML-escaped.
The report must NEVER claim production-ready/certified accuracy from a sample
gate or from synthetic data. Operates on reference_benchmark.py JSON output.
"""
from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path

class BenchmarkReportError(ValueError):
    pass


def _esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def _pct(value):
    if value is None:
        return "N/A — missing samples"
    if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise BenchmarkReportError("Metric percentage outside 0..1")
    return f"{value * 100:.1f}%"


def _count(value):
    if type(value) is not int or value < 0:
        raise BenchmarkReportError("Invalid sample count")
    return value


CSS = """
:root{font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;color:#e5eff7;background:#0a1220}
*{box-sizing:border-box}
body{max-width:1300px;margin:0 auto;padding:35px 24px 75px;background:#0a1220}
h1{font-size:39px;letter-spacing:-.045em;line-height:1.1;margin:8px 0 13px}
h2{font-size:19px;margin:36px 0 14px;letter-spacing:-.025em}
p,li{line-height:1.65}
.eyebrow{font-size:12px;font-weight:850;letter-spacing:.17em;color:#cae591;text-transform:uppercase}
.muted{color:#9fb2c5}
small{color:#99aec4;font-size:12px}
.banner{padding:19px 21px;border-radius:11px;background:#27313d;border-left:5px solid #e2b96e;margin:27px 0}
.banner strong{display:block;margin:0 0 6px;font-size:18px}
.banner p{margin:0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(195px,1fr));gap:12px}
.metric{padding:20px;border-radius:11px;border:1px solid #33475a;background:#152236}
.metric strong{font-size:27px;display:block;line-height:1.35;letter-spacing:-.035em}
.metric span{font-size:12px;color:#a8bacb}
.card{background:#122033;border:1px solid #30425a;border-radius:11px;padding:18px 22px}
.chip{padding:6px 10px;background:#26364b;color:#c9d9eb;font-size:12px;border-radius:5px;display:inline-block;margin:4px}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{border-bottom:1px solid #334357;text-align:left;padding:12px 10px;vertical-align:top;overflow-wrap:anywhere}
th{color:#b6c8d8;background:#152339}
.scroll{overflow:auto}
.bad{color:#ffaaaa}.ok{color:#adf2c7}.warn{color:#f5dba4}
small.code{font-family:ui-monospace,Consolas,monospace}
.footer{border-top:1px solid #324357;margin-top:44px;padding-top:16px}
"""

def render_benchmark_report(report: dict) -> str:
    if not isinstance(report,dict) or not isinstance(report.get("metrics"),dict):
        raise BenchmarkReportError("Expected benchmark report with metrics")
    if not isinstance(report.get("pilot_sample_gate"),dict):
        raise BenchmarkReportError("Expected benchmark pilot sample gate")
    summary = report["metrics"]
    pilot = report["pilot_sample_gate"]
    cases = report.get("cases")
    by_kind = report.get("by_kind")
    if not isinstance(cases,list) or len(cases)>500 or not isinstance(by_kind,dict):
        raise BenchmarkReportError("Expected case rows and per-kind metrics")

    real_photos = _count(summary.get("distinct_real_photos",0))
    cases_count = _count(summary.get("cases",0))
    negatives = _count((summary.get("counts") or {}).get("negative_cases",0))
    certified = pilot.get("accuracy_certified") is True
    # Even if source data incorrectly claims certification, do not propagate it.
    if certified:
        raise BenchmarkReportError("Untrusted input claims unsupported certified accuracy")
    status = str(pilot.get("status") or "INSUFFICIENT_REAL_PHOTO_VALIDATION")
    headline = (
        "Minimum sampling gate reached — not an accuracy certification"
        if status == "SAMPLE_READY_FOR_MANUAL_REVIEW"
        else "Real-photo validation is incomplete"
    )
    stats=[
        ("Reviewed cases", str(cases_count)),
        ("Distinct REAL photos", str(real_photos)),
        ("Negatives", str(negatives)),
        ("Known card recall", _pct(summary.get("known_card_recall"))),
        ("Wrong-identity rate", _pct(summary.get("wrong_identity_rate_on_positives"))),
        ("False-match on negatives", _pct(summary.get("false_match_rate_on_negatives"))),
        ("Candidate precision", _pct(summary.get("accepted_candidate_precision_on_labeled_cases"))),
        ("Abstain rate", _pct(summary.get("abstain_rate"))),
        ("Ambiguous rate", _pct(summary.get("ambiguous_rate"))),
    ]
    html_out=[
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<meta name='robots' content='noindex,nofollow'>",
        "<title>BIGSTEN — Private Reference Accuracy Audit</title>",
        "<style>",CSS,"</style></head><body>",
        "<p class='eyebrow'>BIGSTEN · Collection Intelligence / Photo Truth Lab</p>",
        "<h1>Reference matching: independent holdout audit</h1>",
        "<p class='muted'>Results from locally reviewed photos. This is a research report, not a live market signal or product-grade performance claim.</p>",
        "<div class='banner'><strong>",_esc(headline),
        "</strong><p>No tested model can establish card authenticity, PSA grade, foil, hidden inventory or future resale profit from image similarity alone.</p></div>",
        "<section class='grid'>"
    ]
    for name,value in stats:
        html_out.extend(["<div class='metric'><strong>",_esc(value),
                         "</strong><span>",_esc(name),"</span></div>"])
    html_out.append("</section>")

    checks=[
        ("At least 50 distinct real photos",pilot.get("fifty_distinct_real_photos")),
        ("At least five negative/unknown cases",pilot.get("at_least_five_negative_cases")),
        ("Three or more evaluation categories",pilot.get("at_least_three_evaluation_categories")),
        ("All photo origins classified",pilot.get("all_photo_origins_reviewed")),
        ("Independently certified accuracy",False),
    ]
    html_out.extend(["<h2>P1 sample gates</h2><section class='card'>"])
    for label,state in checks:
        mark="✓" if state is True else "✕"
        html_out.extend(["<span class='chip ", "ok" if state else "warn","'>",
                         _esc(mark+" "+label),"</span>"])
    html_out.extend(["<p class='muted'>Satisfying the photo-count gates is necessary for initial validation, but not sufficient for shipping a commercial app. Real data can be biased, mislabeled or too similar to training references.</p></section>"])

    html_out.extend(["<h2>Performance by category</h2><div class='card scroll'><table>",
                     "<thead><tr><th>Category</th><th>Cases</th><th>Recall</th><th>Wrong identity</th><th>Negative false match</th><th>Abstain</th></tr></thead><tbody>"])
    for category, metrics in sorted(by_kind.items()):
        if not isinstance(metrics,dict):
            continue
        html_out.extend([
            "<tr><td>",_esc(category),"</td><td>",_esc(_count(metrics.get("cases",0))),
            "</td><td>",_esc(_pct(metrics.get("known_card_recall"))),
            "</td><td>",_esc(_pct(metrics.get("wrong_identity_rate_on_positives"))),
            "</td><td>",_esc(_pct(metrics.get("false_match_rate_on_negatives"))),
            "</td><td>",_esc(_pct(metrics.get("abstain_rate"))),"</td></tr>"
        ])
    html_out.extend(["</tbody></table></div>"])

    html_out.extend(["<h2>Case-by-case audit</h2><div class='card scroll'><table>",
                     "<thead><tr><th>Case</th><th>Category</th><th>Outcome</th><th>Expected</th><th>Image candidate</th><th>Matcher state</th></tr></thead><tbody>"])
    for row in cases:
        if not isinstance(row,dict):
            continue
        outcome=str(row.get("outcome") or "")
        status_class="ok" if outcome in {"correct","correct_rejection"} else "bad" if outcome in {"wrong_identity","false_match"} else "warn"
        html_out.extend([
            "<tr><td>",_esc(row.get("case_id")),"</td><td>",_esc(row.get("kind")),
            "</td><td class='",status_class,"'>",_esc(outcome),
            "</td><td><small class='code'>",_esc(row.get("expected_identity_key") or "UNKNOWN"),
            "</small></td><td><small class='code'>",_esc(row.get("candidate_identity_key") or "NONE"),
            "</small></td><td>",_esc(row.get("matcher_status")),"</td></tr>"
        ])
    html_out.extend(["</tbody></table></div>"])

    html_out.extend(["<h2>Uncertainties and limitations</h2><div class='card'><ul>"])
    for caution in (report.get("limitations") or [])[:25]:
        if isinstance(caution,str):
            html_out.extend(["<li>",_esc(caution),"</li>"])
    html_out.extend([
        "</ul><p class='muted'>Privacy: This HTML contains case IDs and expected card identifiers but no original photo bytes. Keep it in your PRIVATE local folder; do not publish identifiable review records.</p></div>",
        "<p class='footer'><small>Offline BIGSTEN audit · No AI API cost · Not investment advice · No authenticated card grades · Human review mandatory.</small></p>",
        "</body></html>"
    ])
    return "".join(html_out)


def main(argv=None):
    parser=argparse.ArgumentParser(description="Render a private, offline BIGSTEN benchmark HTML report")
    parser.add_argument("report",help="Private JSON result from reference_benchmark.py")
    parser.add_argument("--out",default="private/reference_accuracy.html")
    args=parser.parse_args(argv)
    data=json.loads(Path(args.report).read_text(encoding="utf-8"))
    output=render_benchmark_report(data)
    path=Path(args.out)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(output,encoding="utf-8")
    print(f"Private BIGSTEN benchmark report saved to {path}")


if __name__=="__main__":
    main()

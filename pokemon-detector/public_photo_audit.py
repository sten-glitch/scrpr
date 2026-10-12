"""BIGSTEN public photo research audit — ephemeral, real photographs, NO fake accuracy.

Downloads photos only through registered public-source adapters and performs
the existing free OpenCV contour detector. The original photos remain in a
temporary directory and are erased when the run ends. JSON and static HTML
reports store metadata/provenance and candidate BOX COUNTS only, NOT photos.

IMPORTANT: unlabeled photos cannot establish precision, recall, exact card
identity, edition, slab grade or resale value. Use provider-authorized YOLO
holdout exports and external_detection_benchmark.py for geometric precision.

Example:
  python public_photo_audit.py --commons 20 --previews --search "pokemon cards"
  python public_photo_audit.py --commons 12 --previews --out private/commons_audit
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import html
import json
import math
import tempfile
from pathlib import Path

from external_photo_sources import (
    PhotoSourceError, import_commons, import_roboflow_public_previews,
)
from local_cv import analyze_local_photo, LocalCVError

MAX_IMAGES = 50


class PublicAuditError(ValueError):
    pass


def run_public_photo_audit(*, commons=12, previews=True, search=None,
                           image_analysis=analyze_local_photo,
                           commons_import=import_commons,
                           preview_import=import_roboflow_public_previews) -> dict:
    if (type(commons) is not int or not 0<=commons<=MAX_IMAGES
            or type(previews) is not bool or (commons==0 and not previews)):
        raise PublicAuditError("Select 1–50 licensed Commons candidates and/or three public previews")
    if search is not None and (not isinstance(search,str) or not 3<=len(search.strip())<=100):
        raise PublicAuditError("Search is 3–100 characters")

    cases=[]
    failures=[]
    sources={}
    with tempfile.TemporaryDirectory(prefix="bigsten-web-photo-") as temp:
        root=Path(temp)
        to_scan=[]
        if commons:
            folder=root/"commons"
            try:
                imported=commons_import(max_images=commons,root=folder,search=search)
                sources["commons"]={
                    "obtained":len(imported.get("items",[])),
                    "failed":len(imported.get("failed",[])),
                    "search_query":search,
                }
                for item in imported.get("items",[]):
                    to_scan.append(("commons",folder,item))
                for failure in imported.get("failed",[]):
                    failures.append({"source":"commons","reason":str(failure.get("reason","download failed"))[:180]})
            except (OSError,PhotoSourceError,ValueError) as exc:
                sources["commons"]={"obtained":0,"failed":1,"search_query":search}
                failures.append({"source":"commons","reason":str(exc)[:180]})
        if previews:
            folder=root/"previews"
            try:
                imported=preview_import(root=folder)
                sources["roboflow_preview"]={
                    "obtained":len(imported.get("items",[])),
                    "failed":len(imported.get("failed",[])),
                }
                for item in imported.get("items",[]):
                    to_scan.append(("roboflow_preview",folder,item))
                for failure in imported.get("failed",[]):
                    failures.append({"source":"roboflow_preview","reason":str(failure.get("reason","download failed"))[:180]})
            except (OSError,PhotoSourceError,ValueError) as exc:
                sources["roboflow_preview"]={"obtained":0,"failed":1}
                failures.append({"source":"roboflow_preview","reason":str(exc)[:180]})

        seen=set()
        for source,folder,item in to_scan:
            try:
                name=item.get("image_file")
                if not isinstance(name,str) or Path(name).name!=name:
                    raise PublicAuditError("Unsafe importer file name")
                binary=(folder/name).read_bytes()
                if not binary or len(binary)>5*1024*1024:
                    raise PublicAuditError("Missing or oversized temporary image")
                digest=hashlib.sha256(binary).hexdigest()
                if digest in seen:
                    continue
                seen.add(digest)
                measured=image_analysis(binary,run_ocr=False)
                observations=measured.get("observations",[])
                if not isinstance(observations,list):
                    raise PublicAuditError("Detector result missing observation array")
                boxes=[]
                for record in observations[:30]:
                    bbox=record.get("bbox_xyxy") if isinstance(record,dict) else None
                    if (isinstance(bbox,list) and len(bbox)==4
                            and all(type(x) in (float,int) and math.isfinite(x) and 0<=x<=1 for x in bbox)):
                        boxes.append([round(float(x),4) for x in bbox])
                cases.append({
                    "source":source,
                    "source_page":item.get("source_page"),
                    "author":item.get("author",""),
                    "license":item.get("license",item.get("license_displayed","")),
                    "license_url":item.get("license_url",""),
                    "source_title":item.get("source_title",item.get("image_file")),
                    "photo_sha256":digest,
                    "image_bytes":len(binary),
                    "candidate_rectangles":len(boxes),
                    "candidate_bboxes_xyxy":boxes,
                    "exact_card_identity_verified":False,
                    "card_presence_human_verified":False,
                    "copyright_subcontents_reviewed":False,
                })
            except (OSError,LocalCVError,PublicAuditError,ValueError) as exc:
                failures.append({"source":source,"reason":str(exc)[:180]})
    cases.sort(key=lambda c:(c["source"],str(c.get("source_title"))))
    return {
        "status":"REAL_PUBLIC_UNLABELED_PHOTO_RESEARCH_NOT_AN_ACCURACY_BENCHMARK",
        "measured_at_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_registry":sources,
        "summary":{
            "real_public_photos_processed":len(cases),
            "provisional_rectangles":sum(x["candidate_rectangles"] for x in cases),
            "photos_with_at_least_one_rectangle":sum(bool(x["candidate_rectangles"]) for x in cases),
            "download_or_analysis_failures":len(failures),
            "independently_verified_photo_ground_truth":0,
            "identified_pokemon_card_printings":0,
            "real_photo_card_identity_accuracy":None,
            "card_box_precision":None,
            "card_box_recall":None,
        },
        "cases":cases,
        "failures":failures[:50],
        "limitations":[
            "Photograph presence of Pokémon cards is not independently established",
            "Card-like rectangles may include other objects; no verified bounding-box ground truth",
            "Neither geometry precision nor exact printing/foil/grade accuracy can be calculated from unlabeled photos",
            "Source license claims may not cover embedded artwork or commercial exploitation",
            "All image bytes are erased at end of audit and never included in the output report",
        ],
    }


def audit_html(audit: dict) -> str:
    if not isinstance(audit,dict) or audit.get("status") != "REAL_PUBLIC_UNLABELED_PHOTO_RESEARCH_NOT_AN_ACCURACY_BENCHMARK":
        raise PublicAuditError("Expected authentic BIGSTEN unlabeled research audit")
    e=lambda x:html.escape(str(x if x is not None else ""),quote=True)
    summary=audit["summary"]
    sources=audit.get("cases",[])
    parts=[
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<meta name='robots' content='noindex,nofollow'>",
        "<title>BIGSTEN Real Public Photo Research — Unlabeled</title>",
        "<style>body{font:15px system-ui;background:#0d1620;color:#edf6fd;max-width:1200px;margin:auto;padding:28px}",
        "h1{font-size:35px;letter-spacing:-.045em}p{line-height:1.6}a{color:#c8e58c}",
        ".warning{padding:20px;background:#293747;border-left:5px solid #e6b66d}",
        ".grid{display:flex;flex-wrap:wrap;gap:13px;margin:28px 0}.stat{padding:19px;flex:1;min-width:150px;border:1px solid #33485b;border-radius:10px}",
        ".stat strong{font-size:26px;display:block}table{width:100%;border-collapse:collapse;font-size:12px}",
        "th,td{text-align:left;padding:10px;border-bottom:1px solid #344453;vertical-align:top;overflow-wrap:anywhere}",
        "th{color:#bcd1e0}small{color:#9bb2c9}</style></head><body>",
        "<p><small>BIGSTEN Collection Intelligence · open-web research · no retained source photos</small></p>",
        "<h1>What can our free detector see in real web photos?</h1>",
        "<div class='warning'><strong>UNLABELED RESEARCH, NOT ACCURACY.</strong>",
        "<p>These counts are only OpenCV candidates. Card presence, publisher annotations, exact Pokémon printing, authenticity and commercial rights have NOT been independently verified.</p></div>",
        "<div class='grid'>",
    ]
    for label,key in (
        ("Real photos scanned","real_public_photos_processed"),
        ("Card-like contours","provisional_rectangles"),
        ("Photos with candidates","photos_with_at_least_one_rectangle"),
        ("Download or analysis errors","download_or_analysis_failures"),
        ("Confirmed Pokémon printings","identified_pokemon_card_printings"),
    ):
        parts.extend(["<div class='stat'><strong>",e(summary.get(key,0)),
                      "</strong><span>",e(label),"</span></div>"])
    parts.extend(["</div><h2>Case-by-case provenance and detections</h2><table><thead><tr>",
                 "<th>Source</th><th>Photo title</th><th>License / author</th><th>Contoured candidates</th>",
                 "</tr></thead><tbody>"])
    for c in sources:
        # Only allow known-source HTTPS page links to avoid HTML protocol injection.
        from urllib.parse import urlsplit
        url=c.get("source_page")
        parsed=urlsplit(url) if isinstance(url,str) else None
        if parsed and parsed.scheme=="https" and parsed.hostname in {
            "commons.wikimedia.org","universe.roboflow.com"
        }:
            title="<a href='"+e(url)+"' rel='noreferrer noopener'>"+e(c.get("source_title"))+"</a>"
        else:
            title=e(c.get("source_title"))
        parts.extend(["<tr><td>",e(c.get("source")),"</td><td>",title,
                      "</td><td>",e(c.get("license"))," — ",e(c.get("author")),
                      "</td><td>",e(c.get("candidate_rectangles",0)),"</td></tr>"])
    parts.extend(["</tbody></table><h2>Uncertainties</h2><ul>"])
    for line in audit.get("limitations",[]):
        parts.extend(["<li>",e(line),"</li>"])
    parts.append("</ul><p><small>BIGSTEN does not embed or redistribute web photos in this report. Copyright and commercial permission may require separate review.</small></p></body></html>")
    return "".join(parts)


def main(argv=None):
    parser=argparse.ArgumentParser(description="Audit real online photo contours, no exact identity or accuracy claims")
    parser.add_argument("--commons",type=int,default=12,help="Up to 50 Commons photos")
    parser.add_argument("--search",help="Search for public photos on Wikimedia Commons, default category")
    parser.add_argument("--previews",action="store_true",help="Include three public Roboflow example thumbnails")
    parser.add_argument("--out",default="private/public_photo_audit",help="Local path prefix for JSON + HTML")
    args=parser.parse_args(argv)
    report=run_public_photo_audit(commons=args.commons,previews=args.previews,search=args.search)
    target=Path(args.out)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.with_suffix(".json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    target.with_suffix(".html").write_text(audit_html(report),encoding="utf-8")
    print("BIGSTEN_REAL_PUBLIC_PHOTOS",report["summary"]["real_public_photos_processed"])
    print("BIGSTEN_PROVISIONAL_CARD_RECTANGLES",report["summary"]["provisional_rectangles"])
    print("BIGSTEN_PHOTOS_WITH_CANDIDATES",report["summary"]["photos_with_at_least_one_rectangle"])
    print("BIGSTEN_SOURCE_ERRORS",report["summary"]["download_or_analysis_failures"])
    print("BIGSTEN_REPORTED_CARD_IDENTITY_ACCURACY",None)
    print("BIGSTEN_PRIVATE_REPORTS",str(target.with_suffix(".json")),str(target.with_suffix(".html")))


if __name__=="__main__":
    main()

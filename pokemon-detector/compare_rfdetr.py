"""BIGSTEN paired detector experiment: OpenCV contours vs fine-tuned RF-DETR.

Uses exactly the same YOLO TEST/VALID images, label parser, IoU threshold,
one-to-one rectangle matching and sample exclusions for both algorithms.
Refuses nonidentical evaluated sample sets, false identity claims or the
COCO-pretrained model without a dedicated trading-card class.

No provider access needed at comparison time: images/labels must already be
downloaded legally into the private directory. Running inference may use CPU
and significant local RAM; installing RF-DETR does not mean a GPU or private
checkpoint is included.

Checkpoint loading with PyTorch can be unsafe for untrusted weights; use only
trusted own training artifacts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import math
from pathlib import Path

from external_detection_benchmark import benchmark_yolo, DetectionBenchmarkError
from rfdetr_card_detector import RFDETRCardDetector


class CompareError(ValueError):
    pass


def _pct(value):
    return "N/A" if value is None else f"{100*value:.1f}%"


def compare_reports(opencv: dict, rfdetr: dict, *,
                    checkpoint_sha256="MOCK_NEVER_REAL") -> dict:
    if not isinstance(opencv,dict) or not isinstance(rfdetr,dict):
        raise CompareError("Expected both benchmark reports")
    if opencv.get("status")!="DETECTION_ONLY_ON_EXTERNAL_PUBLISHED_ANNOTATIONS" or rfdetr.get("status")!=opencv["status"]:
        raise CompareError("Only real external YOLO geometry benchmarks may be compared")
    for key in ("split","source","card_class_id","class_names","iou_threshold"):
        if opencv.get(key)!=rfdetr.get(key):
            raise CompareError("The two runs used different dataset/annotation/evaluation settings")
    left=opencv.get("cases")
    right=rfdetr.get("cases")
    if not isinstance(left,list) or not isinstance(right,list):
        raise CompareError("Missing per-photo case data")
    lrows=[r for r in left if r.get("status")=="EVALUATED_BOXES_NOT_IDENTITY"]
    rrows=[r for r in right if r.get("status")=="EVALUATED_BOXES_NOT_IDENTITY"]
    if len(lrows)!=len(rrows) or not lrows:
        raise CompareError("Different or empty evaluated photo sets")
    deltas=[]
    for l,r in zip(lrows,rrows):
        if l.get("image")!=r.get("image") or l.get("ground_truth_boxes")!=r.get("ground_truth_boxes"):
            raise CompareError("Different photos or ground-truth boxes; paired comparison invalid")
        deltas.append({
            "image":l["image"],"publisher_ground_truth_boxes":l["ground_truth_boxes"],
            "opencv_tp":l["tp"],"opencv_fp":l["fp"],"opencv_fn":l["fn"],
            "rfdetr_tp":r["tp"],"rfdetr_fp":r["fp"],"rfdetr_fn":r["fn"],
            "rfdetr_recall_delta_boxes":r["tp"]-l["tp"],
            "rfdetr_false_positive_delta_boxes":r["fp"]-l["fp"],
        })
    def score(x):
        m=x.get("metrics") or {}
        return {
            "precision":m.get("precision"),
            "recall":m.get("recall"),
            "f1":m.get("f1"),
            "tp":m.get("true_positives"),
            "fp":m.get("false_positives"),
            "fn":m.get("false_negatives"),
        }
    return {
        "status":"PAIRED_LOCAL_CARD_BOX_RESEARCH_NOT_IDENTITY_ACCURACY",
        "created_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
        "source":opencv["source"],
        "split":opencv["split"],"iou_threshold":opencv["iou_threshold"],
        "evaluated_photos":len(lrows),
        "checkpoint_sha256":checkpoint_sha256,
        "opencv":score(opencv),"rfdetr_nano":score(rfdetr),
        "per_photo":deltas,
        "same_evaluated_photos":True,
        "source_labels_independently_audited":False,
        "actual_exact_card_identity_accuracy":None,
        "commercial_card_art_rights_verified":False,
        "model_training_dataset_rights_verified":False,
        "user_action":"Review validation labels, near-duplicate leaks, detector false positives and checkpoint provenance before deciding whether to replace OpenCV.",
        "limitations":[
            "Both algorithms are evaluated against potentially imperfect external publisher YOLO labels",
            "This compares 2D rectangles only; it does NOT recognize the Pokémon printing or foil",
            "Only a fine-tuned RF-DETR model with a dedicated card class can be compared; a pretrained COCO model has no card class",
            "Test split and original source-image commercial rights require independent review",
            "Near-duplicate train/test images and tuning threshold on test can bias scores",
            "Do not ship an experimental model just because its aggregate F1 is higher",
        ]
    }


def report_html(report):
    if report.get("status")!="PAIRED_LOCAL_CARD_BOX_RESEARCH_NOT_IDENTITY_ACCURACY":
        raise CompareError("Not an authentic paired BIGSTEN report")
    e=lambda v:html.escape(str(v if v is not None else "N/A"),quote=True)
    rows=[
        ("Precision",_pct(report["opencv"]["precision"]),_pct(report["rfdetr_nano"]["precision"])),
        ("Recall",_pct(report["opencv"]["recall"]),_pct(report["rfdetr_nano"]["recall"])),
        ("F1",_pct(report["opencv"]["f1"]),_pct(report["rfdetr_nano"]["f1"])),
        ("True positive boxes",report["opencv"]["tp"],report["rfdetr_nano"]["tp"]),
        ("False positive boxes",report["opencv"]["fp"],report["rfdetr_nano"]["fp"]),
        ("Missed boxes",report["opencv"]["fn"],report["rfdetr_nano"]["fn"]),
    ]
    bits=[
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<meta name='robots' content='noindex,nofollow'>",
        "<title>BIGSTEN — OpenCV vs RF-DETR Nano</title>",
        "<style>body{font:15px system-ui;color:#e6eff8;background:#0c1620;max-width:1250px;margin:auto;padding:28px}",
        "h1{font-size:34px;letter-spacing:-.04em}p{line-height:1.6}",
        "table{width:100%;border-collapse:collapse;font-size:13px}",
        "th,td{border-bottom:1px solid #394958;padding:12px;text-align:left;vertical-align:top;overflow-wrap:anywhere}",
        ".alert{background:#2a3645;border-left:5px solid #e8c378;border-radius:5px;padding:16px}",
        ".stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px}",
        ".card{border:1px solid #344759;padding:17px;border-radius:8px}small{color:#acbbce}</style>",
        "</head><body><p><small>BIGSTEN / P1 Card Rectangle Research</small></p>",
        "<h1>OpenCV vs fine-tuned RF-DETR Nano</h1>",
        "<p class='alert'><strong>Publisher-box comparison, NOT exact Pokémon identity accuracy.</strong> "
        "RF-DETR must have an explicit trading-card class. "
        "The same evaluation images and IoU threshold were used. "
        "Labels, photo rights, grading and commercial deployment remain unverified.</p>",
        "<div class='stats'><div class='card'>Holdout photos evaluated: <strong>",
        e(report["evaluated_photos"]),"</strong></div><div class='card'>IoU threshold: <strong>",
        e(report["iou_threshold"]),"</strong></div></div>",
        "<h2>Paired metrics</h2><table><thead><tr><th>Measure</th><th>OpenCV</th><th>RF-DETR Nano</th></tr></thead><tbody>",
    ]
    for label,cv,rf in rows:
        bits.extend(["<tr><td>",e(label),"</td><td>",e(cv),"</td><td>",e(rf),"</td></tr>"])
    bits.extend(["</tbody></table><h2>Per-photo errors</h2><table><thead><tr><th>Image</th>",
                 "<th>Ground truth</th><th>OpenCV TP / FP / FN</th><th>RF-DETR TP / FP / FN</th></tr></thead><tbody>"])
    for row in report["per_photo"][:400]:
        bits.extend(["<tr><td>",e(row["image"]),"</td><td>",e(row["publisher_ground_truth_boxes"]),
                     "</td><td>",e(f'{row["opencv_tp"]} / {row["opencv_fp"]} / {row["opencv_fn"]}'),
                     "</td><td>",e(f'{row["rfdetr_tp"]} / {row["rfdetr_fp"]} / {row["rfdetr_fn"]}'),"</td></tr>"])
    bits.extend(["</tbody></table><h2>Scientific limitations</h2><ul>"])
    for note in report["limitations"]:
        bits.extend(["<li>",e(note),"</li>"])
    bits.extend(["</ul><p><small>All raw training/test photos and checkpoint weights remain private. "
                 "No authenticated grade or investment signal is produced.</small></p></body></html>"])
    return "".join(bits)


def run_paired_benchmark(dataset,checkpoint, *,
                         source,split="test",max_images=300,
                         max_cards=30,iou=.5,confidence=.5,
                         loader=None):
    if (type(max_images) is not int or not 1<=max_images<=500
            or type(max_cards) is not int or not 1<=max_cards<=100
            or type(iou) not in (float,int) or not 0<iou<=1):
        raise CompareError("Invalid paired evaluation bounds")
    adapter=RFDETRCardDetector(checkpoint,threshold=confidence,
                              max_boxes=max_cards,loader=loader)
    kwargs={"split":split,"source":source,
            "max_images":max_images,"max_cards":max_cards,
            "iou_threshold":iou}
    opencv=benchmark_yolo(dataset,**kwargs)
    rfdetr=benchmark_yolo(
        dataset,**kwargs,detector=adapter,detector_name="rfdetr_nano_card_finetuned")
    return compare_reports(opencv,rfdetr,
                           checkpoint_sha256=adapter.checkpoint_sha256)


def main(argv=None):
    p=argparse.ArgumentParser(
        description="Pair OpenCV vs fine-tuned RF-DETR Nano on SAME authorized held-out YOLO photos")
    p.add_argument("dataset",help="Private YOLO export root with data.yaml and TEST/VALID labels")
    p.add_argument("--source",choices=("detector","binder","scanner"),required=True)
    p.add_argument("--checkpoint",required=True,
                   help="Trusted user-trained RF-DETR Nano .pth checkpoint (NOT public COCO weights)")
    p.add_argument("--split",choices=("test","valid"),default="test")
    p.add_argument("--max-images",type=int,default=300)
    p.add_argument("--max-cards",type=int,default=30)
    p.add_argument("--iou",type=float,default=.5)
    p.add_argument("--confidence",type=float,default=.5)
    p.add_argument("--out",default="private/rfdetr-comparison")
    args=p.parse_args(argv)
    report=run_paired_benchmark(
        args.dataset,args.checkpoint,source=args.source,split=args.split,
        max_images=args.max_images,max_cards=args.max_cards,
        iou=args.iou,confidence=args.confidence)
    output=Path(args.out)
    output.parent.mkdir(parents=True,exist_ok=True)
    j=output.with_suffix(".json")
    h=output.with_suffix(".html")
    if j.exists() or h.exists():
        raise CompareError("Refusing to overwrite an existing paired result")
    j.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    h.write_text(report_html(report),encoding="utf-8")
    print("BIGSTEN PAIRED PHOTOS:",report["evaluated_photos"])
    print("OpenCV F1:",report["opencv"]["f1"],
          "Fine-tuned RF-DETR F1:",report["rfdetr_nano"]["f1"])
    print("Card identity accuracy:",report["actual_exact_card_identity_accuracy"])
    print("Offline private reports:",j,h)


if __name__=="__main__":
    main()

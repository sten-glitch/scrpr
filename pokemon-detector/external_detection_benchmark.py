"""BIGSTEN YOLO photo detector benchmark — public research dataset only.

Works with official Roboflow YOLOv8 image+label exports in a private local
folder. Tests OpenCV rectangle detection, NOT Pokémon printing recognition,
card authenticity, foil, PSA label or profitable sale.

Use only independent validation/test splits. Do not benchmark on train.
Published CC BY dataset license still requires source/photographer/artwork
rights review before commercial reuse or redistribution.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import html
import json
import math
import re
from pathlib import Path

from local_cv import _checked_image, detect_card_boxes
from external_photo_sources import SOURCES


class DetectionBenchmarkError(ValueError):
    pass


IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_CASES = 1500


def _quoted_list(value: str):
    try:
        parsed = ast.literal_eval(value.strip())
    except (SyntaxError, ValueError) as exc:
        raise DetectionBenchmarkError(
            "Unsupported data.yaml class list. Use --card-class-id and inspect class names manually"
        ) from exc
    if not isinstance(parsed,(list,dict)):
        raise DetectionBenchmarkError("Invalid data.yaml class names")
    if isinstance(parsed,list):
        return {i:str(name) for i,name in enumerate(parsed)}
    if not all(str(k).isdigit() for k in parsed.keys()):
        raise DetectionBenchmarkError("Class map must have integer IDs")
    return {int(k):str(v) for k,v in parsed.items()}


def read_yolo_names(data_yaml: Path) -> dict[int,str]:
    if not data_yaml.is_file():
        raise DetectionBenchmarkError("Missing YOLO data.yaml from official export")
    text=data_yaml.read_text(encoding="utf-8")
    lines=text.splitlines()
    for i,line in enumerate(lines):
        if re.match(r"^names:\s*",line):
            inline=line.split(":",1)[1].strip()
            if inline and inline not in {"|",">"}:
                return _quoted_list(inline)
            result={}
            j=i+1
            while j<len(lines) and (lines[j].startswith(" ") or lines[j].startswith("-")):
                item=lines[j].strip()
                if item.startswith("-"):
                    result[len(result)]=item[1:].strip().strip("'\"")
                else:
                    match=re.match(r"^(\d+):\s*(.+)\s*$",item)
                    if match:
                        result[int(match.group(1))]=match.group(2).strip().strip("'\"")
                j+=1
            if result:
                return result
    raise DetectionBenchmarkError("Could not read class names from data.yaml")


def _class_id(root: Path, explicit: int | None):
    names=read_yolo_names(root/"data.yaml")
    if explicit is not None:
        if type(explicit) is not int or explicit not in names:
            raise DetectionBenchmarkError("Requested class ID missing in export data.yaml")
        return explicit,names
    cards=[index for index,name in names.items() if name.lower().strip()=="card"]
    if len(cards)!=1:
        raise DetectionBenchmarkError("Could not uniquely identify class 'card' in data.yaml; inspect file and supply --card-class-id")
    return cards[0],names


def _parse_boxes(text: str, class_id: int) -> list[list[float]]:
    boxes=[]
    if len(text)>400_000:
        raise DetectionBenchmarkError("Oversized YOLO label file")
    for line in text.splitlines():
        if not line.strip():
            continue
        pieces=line.strip().split()
        if len(pieces)!=5 and (len(pieces)<7 or len(pieces)%2!=1):
            raise DetectionBenchmarkError("Expected YOLO class + xywh or polygon x/y points")
        try:
            cls=int(pieces[0])
            coords=[float(x) for x in pieces[1:]]
        except ValueError as exc:
            raise DetectionBenchmarkError("Malformed numeric annotation") from exc
        if len(pieces)>5:
            if not all(math.isfinite(z) and 0<=z<=1 for z in coords):
                raise DetectionBenchmarkError("Invalid YOLO segmentation polygon")
            xs=coords[0::2]
            ys=coords[1::2]
            x0,y0,x1,y1=min(xs),min(ys),max(xs),max(ys)
            xc,yc,w,h=(x0+x1)/2,(y0+y1)/2,x1-x0,y1-y0
        else:
            xc,yc,w,h=coords
        if (not all(math.isfinite(z) for z in (xc,yc,w,h))
                or w<=0 or h<=0 or w>1 or h>1
                or not 0<=xc<=1 or not 0<=yc<=1
                or xc-w/2 < -1e-3 or yc-h/2 < -1e-3
                or xc+w/2>1+1e-3 or yc+h/2>1+1e-3):
            raise DetectionBenchmarkError("YOLO region outside image boundaries")
        if cls==class_id:
            boxes.append([max(0,xc-w/2),max(0,yc-h/2),
                          min(1,xc+w/2),min(1,yc+h/2)])
    return boxes


def _iou(a,b):
    w=max(0,min(a[2],b[2])-max(a[0],b[0]))
    h=max(0,min(a[3],b[3])-max(a[1],b[1]))
    overlap=w*h
    ar1=(a[2]-a[0])*(a[3]-a[1])
    ar2=(b[2]-b[0])*(b[3]-b[1])
    return overlap/(ar1+ar2-overlap) if ar1+ar2-overlap else 0


def match_rectangles(predicted,expected, threshold=0.5):
    """Best-first one-to-one greedy assignment, deterministic and auditable."""
    if not isinstance(predicted,list) or not isinstance(expected,list):
        raise DetectionBenchmarkError("Expected lists of rectangles")
    if not isinstance(threshold,(float,int)) or not 0 < threshold <= 1:
        raise DetectionBenchmarkError("Threshold must be in (0,1]")
    matches=sorted(
        ((_iou(p,e),i,j) for i,p in enumerate(predicted) for j,e in enumerate(expected)),
        reverse=True)
    used_pred,used_truth=set(),set()
    for score,i,j in matches:
        if score < threshold:
            break
        if i not in used_pred and j not in used_truth:
            used_pred.add(i)
            used_truth.add(j)
    return {
        "true_positives":len(used_pred),
        "false_positives":len(predicted)-len(used_pred),
        "false_negatives":len(expected)-len(used_truth),
        "matched_predictions":sorted(used_pred),
        "matched_ground_truth":sorted(used_truth),
    }


def _report_stats(tp,fp,fn):
    precision=round(tp/(tp+fp),4) if tp+fp else None
    recall=round(tp/(tp+fn),4) if tp+fn else None
    f1=round(2*tp/(2*tp+fp+fn),4) if 2*tp+fp+fn else None
    return {"precision":precision,"recall":recall,"f1":f1,
            "true_positives":tp,"false_positives":fp,"false_negatives":fn}


def benchmark_yolo(root: str | Path, *, split="test", card_class_id=None,
                   max_images=400, max_cards=30, iou_threshold=.5,
                   source="detector", detector=None,
                   detector_name="opencv_contours") -> dict:
    root=Path(root).expanduser().resolve()
    if source not in ("detector","binder","scanner"):
        raise DetectionBenchmarkError("Unknown registered dataset source")
    if split not in ("test","valid"):
        raise DetectionBenchmarkError("Do not use train split for validation")
    if not root.is_dir() or not 1<=max_images<=MAX_CASES or not 1<=max_cards<=100:
        raise DetectionBenchmarkError("Invalid dataset folder/limit")
    class_id,names=_class_id(root,card_class_id)
    folder=root/split
    image_root=folder/"images"
    labels_root=folder/"labels"
    if not image_root.is_dir() or not labels_root.is_dir():
        raise DetectionBenchmarkError("Expected test/images and test/labels or valid equivalents")
    files=sorted(f for f in image_root.iterdir()
                 if f.is_file() and not f.is_symlink() and f.suffix.lower() in IMAGE_TYPES)
    if not files:
        raise DetectionBenchmarkError("No evaluation photos in selected split")
    # Basic split-leakage guard: duplicate source bytes in train must NOT count
    # as independent held-out examples. Augmentation twins still need manual review.
    train_dir=root/"train"/"images"
    train_hashes=set()
    if train_dir.is_dir():
        for path in train_dir.iterdir():
            if path.is_file() and path.suffix.lower() in IMAGE_TYPES and path.stat().st_size<=5*1024*1024:
                train_hashes.add(hashlib.sha256(path.read_bytes()).hexdigest())
    counters={"tp":0,"fp":0,"fn":0,"evaluated":0,"skipped_missing_labels":0,
              "skipped_invalid_images":0,"skipped_train_duplicates":0,
              "skipped_query_duplicates":0,"zero_card_images":0}
    rows=[]
    seen=set()
    for photo in files:
        if counters["evaluated"]>=max_images:
            break
        label_path=labels_root/(photo.stem+".txt")
        if not label_path.is_file():
            counters["skipped_missing_labels"]+=1
            continue
        if photo.stat().st_size<=0 or photo.stat().st_size>5*1024*1024:
            counters["skipped_invalid_images"]+=1
            continue
        raw=photo.read_bytes()
        digest=hashlib.sha256(raw).hexdigest()
        if digest in train_hashes:
            counters["skipped_train_duplicates"]+=1
            continue
        if digest in seen:
            counters["skipped_query_duplicates"]+=1
            continue
        seen.add(digest)
        try:
            boxes=_parse_boxes(label_path.read_text(encoding="utf-8"),class_id)
            if len(boxes)>100:
                raise DetectionBenchmarkError("Annotation contains too many objects")
            cv2,img=_checked_image(raw)
        except (OSError,ValueError) as exc:
            counters["skipped_invalid_images"]+=1
            rows.append({"image":photo.name,"status":"INVALID_NOT_COUNTED",
                         "error":str(exc)[:120]})
            continue
        # Inference errors must FAIL the evaluation, not hide failed photos
        # and quietly inflate a research model's apparent precision/recall.
        try:
            predicted=(detector(img) if detector is not None else
                       detect_card_boxes(cv2,img,max_cards=max_cards))
        except Exception as exc:
            raise DetectionBenchmarkError(
                f"{detector_name} inference failed; benchmark incomplete"
            ) from exc
        if not isinstance(predicted,list) or len(predicted)>max_cards:
            raise DetectionBenchmarkError("Detector returned invalid/excessive box count")
        for box in predicted:
            if (not isinstance(box,(tuple,list)) or len(box)!=4
                    or any(isinstance(x,bool) or not isinstance(x,(float,int))
                           or not math.isfinite(x) or not 0<=x<=1 for x in box)
                    or not box[0]<box[2] or not box[1]<box[3]):
                raise DetectionBenchmarkError("Detector returned a malformed normalized box")
        match=match_rectangles(predicted,boxes,iou_threshold)
        counters["tp"]+=match["true_positives"]
        counters["fp"]+=match["false_positives"]
        counters["fn"]+=match["false_negatives"]
        counters["evaluated"]+=1
        if not boxes:
            counters["zero_card_images"]+=1
        rows.append({
            "image":photo.name,"status":"EVALUATED_BOXES_NOT_IDENTITY",
            "ground_truth_boxes":len(boxes),"predicted_boxes":len(predicted),
            "tp":match["true_positives"],"fp":match["false_positives"],
            "fn":match["false_negatives"],
            "iou_threshold":iou_threshold,
        })
    if not counters["evaluated"]:
        raise DetectionBenchmarkError(
            "No valid independent evaluation photos; inspect dataset split, labels and rights"
        )
    result={
        "status":"DETECTION_ONLY_ON_EXTERNAL_PUBLISHED_ANNOTATIONS",
        "evaluated_at":dt.datetime.now(dt.timezone.utc).isoformat(),
        "source":SOURCES[source],
        "split":split,"card_class_id":class_id,"class_names":names,
        "detector":detector_name,
        "iou_threshold":iou_threshold,"metrics":_report_stats(counters["tp"],counters["fp"],counters["fn"]),
        "samples":counters,"cases":rows,
        "real_photo_provenance_human_verified":False,
        "human_exact_card_id_labels":False,"commercial_rights_cleared":False,
        "card_identity_accuracy_measured":False,
        "segmentation_polygons_evaluated_as_boxes":source=="scanner",
        "limitations":[
            "Only box detection, NOT card identity, edition, foil, rarity, slab grade or authenticity",
            "Externally contributed labels may be noisy/incorrect; no human audit performed by BIGSTEN",
            "Exact train/test duplicate photos skipped; resized/augmented twins may still leak across splits",
            "Provider dataset license and embedded Pokémon artwork rights need independent review",
            "This result cannot satisfy BIGSTEN's 50 independent human-labeled card-identity photo gate",
        ],
    }
    return result


def report_html(report: dict) -> str:
    esc=lambda x:html.escape(str(x),quote=True)
    metrics=report["metrics"]
    values=[("Image count",report["samples"]["evaluated"]),
            ("Precision",f"{metrics['precision']*100:.1f}%" if metrics["precision"] is not None else "N/A"),
            ("Recall",f"{metrics['recall']*100:.1f}%" if metrics["recall"] is not None else "N/A"),
            ("F1",f"{metrics['f1']*100:.1f}%" if metrics["f1"] is not None else "N/A"),
            ("False positives",metrics["false_positives"]),
            ("Missed card boxes",metrics["false_negatives"])]
    bits=["<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
          "<meta name='robots' content='noindex,nofollow'><title>BIGSTEN External Card Detector Audit</title>",
          "<style>body{font:15px system-ui;background:#0c1520;color:#eaf1f8;padding:32px;max-width:1100px;margin:auto}",
          "h1{font-size:30px}.note{background:#283446;padding:20px;border-left:4px solid #e9ba66}",
          ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px;margin:24px 0}",
          ".box{border:1px solid #3a4f62;border-radius:8px;padding:16px}.box strong{font-size:23px;display:block}",
          "table{width:100%;border-collapse:collapse;font-size:12px}td,th{text-align:left;border-bottom:1px solid #374b5a;padding:9px}",
          "small{color:#aebfcf}</style></head><body>",
          "<small>BIGSTEN / Research-only external dataset benchmark</small><h1>Card bounding-box detection</h1>",
          "<div class='note'><strong>NOT A POKÉMON CARD ID ACCURACY TEST.</strong><p>",
          "Dataset bounding boxes may be incorrect. License of source dataset does not automatically license embedded Pokémon art for commercial redistribution. No official grading, no investment decisions.</p></div>",
          "<div class='grid'>"]
    for label,val in values:
        bits.extend(["<div class='box'><strong>",esc(val),"</strong><small>",esc(label),"</small></div>"])
    bits.extend(["</div><p>Source: ",esc(report["source"]["title"])," · split: ",esc(report["split"]),
                 " · IoU ≥ ",esc(report["iou_threshold"]),"</p>",
                 "<h2>Case audit</h2><table><thead><tr><th>Image</th><th>GT boxes</th><th>Detected</th><th>Matched</th><th>False positives</th><th>Missed</th></tr></thead><tbody>"])
    for row in report["cases"][:500]:
        bits.extend(["<tr><td>",esc(row.get("image")),"</td><td>",esc(row.get("ground_truth_boxes","—")),
                     "</td><td>",esc(row.get("predicted_boxes","—")),
                     "</td><td>",esc(row.get("tp","—")),"</td><td>",esc(row.get("fp","—")),
                     "</td><td>",esc(row.get("fn","—")),"</td></tr>"])
    bits.append("</tbody></table><p><small>Local static report. No photo bytes, embedded images, scripts or external assets.</small></p></body></html>")
    return "".join(bits)


def main(argv=None):
    p=argparse.ArgumentParser(description="Benchmark BIGSTEN offline OpenCV card rectangles on Roboflow YOLO exports")
    p.add_argument("dataset", help="Local official YOLOv8 export directory (with data.yaml)")
    p.add_argument("--split",choices=["test","valid"],default="test")
    p.add_argument("--source",choices=["detector","binder","scanner"],required=True)
    p.add_argument("--card-class-id",type=int,help="Override verified card class ID from data.yaml")
    p.add_argument("--max-images",type=int,default=400)
    p.add_argument("--iou",type=float,default=.5)
    p.add_argument("--out",default="private/external_detection_accuracy.json")
    p.add_argument("--html",default="private/external_detection_accuracy.html")
    args=p.parse_args(argv)
    doc=benchmark_yolo(args.dataset,split=args.split,source=args.source,
                       card_class_id=args.card_class_id,
                       max_images=args.max_images,iou_threshold=args.iou)
    j=Path(args.out);h=Path(args.html)
    j.parent.mkdir(parents=True,exist_ok=True)
    h.parent.mkdir(parents=True,exist_ok=True)
    j.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    h.write_text(report_html(doc),encoding="utf-8")
    print("Photos evaluated:",doc["samples"]["evaluated"])
    print("Card-box precision/recall:",doc["metrics"]["precision"],doc["metrics"]["recall"])
    print("PRIVATE local reports:",j,h)
    print("This is NOT card identity accuracy or commercial reuse clearance.")


if __name__ == "__main__":
    main()

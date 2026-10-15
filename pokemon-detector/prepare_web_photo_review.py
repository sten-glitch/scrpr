"""Prepare an external YOLO research split for human review (not auto-labelling).

Copies a bounded, deterministic random-like sample from a Roboflow-exported
TEST or VALID split into a separate PRIVATE photo folder. Preserves source,
class-annotation location and image hash. Critically, it DOES NOT carry a
card's exact identity, so the downstream Photo Review Lab still requires
independent human inspection of each exact printing.

Nothing is pushed to GitHub; source-image copyrights remain source-dependent.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path

from external_photo_sources import SOURCES
from photo_inputs import _mime_from_signature, PhotoInputError


class ReviewImportError(ValueError):
    pass


ALLOWED_EXTS={".jpg",".jpeg",".png",".webp"}


def _all_hashes(root: Path):
    hashes=set()
    if not root.is_dir():
        return hashes
    for file in root.iterdir():
        if file.is_file() and not file.is_symlink() and file.suffix.lower() in ALLOWED_EXTS:
            if 0 < file.stat().st_size <= 5*1024*1024:
                hashes.add(hashlib.sha256(file.read_bytes()).hexdigest())
    return hashes


def prepare_web_photo_review(dataset: str | Path, output: str | Path, *,
                             source: str, split="test", max_photos=50):
    if source not in ("detector","binder","scanner"):
        raise ReviewImportError("Unknown external source")
    if split not in ("test","valid"):
        raise ReviewImportError("Only official held-out test/valid splits are allowed")
    if isinstance(max_photos,bool) or not isinstance(max_photos,int) or not 1<=max_photos<=200:
        raise ReviewImportError("Maximum review photographs must be 1..200")
    dataset=Path(dataset).expanduser().resolve()
    output=Path(output).expanduser().resolve()
    if not (dataset/"data.yaml").is_file():
        raise ReviewImportError("Official YOLO dataset export with data.yaml required")
    photos=dataset/split/"images"
    if not photos.is_dir():
        raise ReviewImportError("Requested held-out image directory missing")
    if output.exists() and any(output.iterdir()):
        raise ReviewImportError("Target folder is not empty; refusing to mix independent review data")
    train_hashes=_all_hashes(dataset/"train"/"images")
    candidates=[]
    for path in photos.iterdir():
        if not path.is_file() or path.is_symlink() or path.suffix.lower() not in ALLOWED_EXTS:
            continue
        if not 0 < path.stat().st_size <= 5*1024*1024:
            continue
        data=path.read_bytes()
        try:
            _mime_from_signature(path,data)
        except PhotoInputError:
            continue
        digest=hashlib.sha256(data).hexdigest()
        if digest in train_hashes:
            continue
        # Deterministic hashed sort avoids original file-order cherry-picking.
        order=hashlib.sha256((source+"|"+split+"|"+path.name).encode()).hexdigest()
        candidates.append((order,path,digest))
    candidates.sort(key=lambda row:row[0])
    saved=[]
    seen_hashes=set()
    output.mkdir(parents=True,exist_ok=True)
    for _,path,digest in candidates:
        if len(saved)>=max_photos:
            break
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        dest_name=(source+"_"+split+"_"+digest[:16]+path.suffix.lower())
        shutil.copyfile(path, output/dest_name)
        saved.append({
            "image_file":dest_name,
            "source_file":path.name,
            "source_url":SOURCES[source]["url"],
            "license_displayed":SOURCES[source]["license_displayed"],
            "source_split":split,
            "sha256":digest,
            "is_human_labeled":False,
            "exact_card_identity_known":False,
            "provider_annotation_rights_checked":False,
            "commercial_reuse_cleared":False,
            "needs_manual_content_and_rights_review":True,
        })
    manifest={
        "status":"UNLABELED_EXTERNAL_PHOTO_RESEARCH_IMPORT",
        "source":SOURCES[source],
        "imported_at":dt.datetime.now(dt.timezone.utc).isoformat(),
        "photo_count":len(saved),
        "test_split_is_guaranteed_independent":False,
        "identity_accuracy_eligible_without_human_review":False,
        "notes":"No exact card identity is automatically inferred from Roboflow boxes. Check near-duplicate augmented photos, label identity and photo/art rights manually.",
        "images":saved,
    }
    (output/"SOURCE_ATTRIBUTION.json").write_text(
        json.dumps(manifest,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return manifest


def main(argv=None):
    p=argparse.ArgumentParser(description="Copy a research sample into private BIGSTEN human review folder")
    p.add_argument("dataset",help="Local Roboflow YOLO export root")
    p.add_argument("--source",choices=["detector","binder","scanner"],required=True)
    p.add_argument("--split",choices=["test","valid"],default="test")
    p.add_argument("--count",type=int,default=50)
    p.add_argument("--out",default="private/web-photo-review")
    args=p.parse_args(argv)
    result=prepare_web_photo_review(args.dataset,args.out,source=args.source,
                                    split=args.split,max_photos=args.count)
    print("Imported",result["photo_count"],"unlabeled private photographs")
    print("Now run: python photo_review_server.py --photos "+args.out+
          " --out private/web-photo-holdout.json")
    print("Card identities and commercial rights are NOT verified.")


if __name__=="__main__":
    main()

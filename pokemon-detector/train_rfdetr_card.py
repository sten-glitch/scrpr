"""BIGSTEN private RF-DETR Nano card-box experiment training launcher.

Runs only on a locally authorized YOLO dataset with TRAIN, VALID, TEST.
TRAIN+VALID are for model optimization; TEST remains untouched and is used
later exactly once for the final paired comparison.

This DOES NOT supply card art/photos/dataset permission. A human must verify
source licenses, embedded Pokemon artwork rights and provider ToS. The
--confirm-dataset-permission flag is user's attestation, not software proof.

Training may download Roboflow's official Apache-designated pretrained
RF-DETR Nano weights once, and consumes significant CPU/GPU/RAM resources.
No Roboflow hosted inference, eBay data, or paid APIs are required. Always
review checkpoint source because PyTorch serialized files are not generally
safe to load from unknown/untrusted origins.

Usage:
  python train_rfdetr_card.py --dataset private/.../roboflow-detector \
      --output private/rfdetr-card-nano --epochs 12 --batch-size 2 \
      --confirm-dataset-permission

Without a CUDA GPU, pass --allow-cpu explicitly; training may be expensive.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

from external_detection_benchmark import _class_id,IMAGE_TYPES,DetectionBenchmarkError


class TrainingGateError(ValueError):
    pass


def _files(directory:Path) -> list[Path]:
    return sorted(p for p in directory.iterdir() if
                  p.is_file() and not p.is_symlink()
                  and p.suffix.lower() in IMAGE_TYPES
                  and 0<p.stat().st_size<=5*1024*1024)


def _sha(path:Path) -> str:
    digest=hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda:file.read(1024*1024),b""):
            digest.update(block)
    return digest.hexdigest()


def audit_training_dataset(dataset: str | Path):
    """Fail-closed exact-byte leakage check. Near-duplicates need a human."""
    dataset=Path(dataset).expanduser().resolve()
    if not (dataset/"data.yaml").is_file():
        raise TrainingGateError("Official authorized YOLO dataset/data.yaml required")
    try:
        card_id,class_names=_class_id(dataset,None)
    except DetectionBenchmarkError as exc:
        raise TrainingGateError("Dataset lacks a uniquely named card label; inspect data.yaml") from exc
    indexed={}
    for split in ("train","valid","test"):
        images=dataset/split/"images"
        labels=dataset/split/"labels"
        if not images.is_dir() or not labels.is_dir():
            raise TrainingGateError(f"{split} requires images/ and labels/ directories")
        paths=_files(images)
        if not paths:
            raise TrainingGateError(f"Dataset {split} has no eligible image files")
        digest_set=set()
        for path in paths:
            if not (labels/(path.stem+".txt")).is_file():
                raise TrainingGateError(f"Missing {split} YOLO label file: {path.name}")
            digest=_sha(path)
            if digest in digest_set:
                raise TrainingGateError(f"Duplicate exact image in {split} split")
            digest_set.add(digest)
        indexed[split]=digest_set
    for a,b in (("train","test"),("valid","test"),("train","valid")):
        if indexed[a] & indexed[b]:
            raise TrainingGateError(
                f"Exact train/valid/test photo leakage between {a} and {b}"
            )
    return {
        "dataset":str(dataset),
        "card_class_id":card_id,
        "class_names":class_names,
        "split_counts":{name:len(values) for name,values in indexed.items()},
        "exact_cross_split_leakage_found":False,
        "near_duplicate_leakage_checked":False,
        "data_rights_independently_verified":False,
        "usable_for_exact_card_identification":False,
    }


def train_private_card_detector(dataset: str | Path,output: str | Path, *,
                                epochs=12,batch_size=2,allow_cpu=False,
                                confirm_permission=False,
                                model_factory=None,cuda_available=None):
    if confirm_permission is not True:
        raise TrainingGateError("Require explicit review and confirmation of dataset permissions")
    if type(epochs) is not int or not 1<=epochs<=60:
        raise TrainingGateError("Epochs must be 1..60")
    if type(batch_size) is not int or not 1<=batch_size<=16:
        raise TrainingGateError("Batch size must be 1..16")
    output=Path(output).expanduser().resolve()
    if "private" not in {part.casefold() for part in output.parts}:
        raise TrainingGateError("Store model checkpoints only in a gitignored private directory")
    if output.exists() and any(output.iterdir()):
        raise TrainingGateError("Refusing to overwrite existing training artifacts")
    sample=audit_training_dataset(dataset)
    if cuda_available is None:
        try:
            import torch
        except ImportError as exc:
            raise TrainingGateError("Optional PyTorch/RF-DETR not installed") from exc
        cuda_available=bool(torch.cuda.is_available())
    if not cuda_available and not allow_cpu:
        raise TrainingGateError(
            "CUDA unavailable. Training on CPU is opt-in via --allow-cpu; "
            "consider another GPU-equipped machine."
        )
    if model_factory is None:
        try:
            from rfdetr import RFDETRNano
        except ImportError as exc:
            raise TrainingGateError("Install official RF-DETR training extra in your local venv") from exc
        model_factory=RFDETRNano
    output.parent.mkdir(parents=True,exist_ok=True)
    # Vendor training is the only side effect after all gate checks pass.
    model=model_factory()
    model.train(dataset_dir=sample["dataset"],
                output_dir=str(output),
                epochs=epochs,batch_size=batch_size)
    result={
        "status":"EXPERIMENTAL_LOCAL_RFDETR_NANO_TRAINING_ATTEMPT",
        "completed_at_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_dataset":sample["dataset"],
        "data_rights_verified_by_software":False,
        "user_claimed_dataset_permission":True,
        "model_family":"RFDETRNano",
        "epochs":epochs,"batch_size":batch_size,
        "cuda_available":bool(cuda_available),
        "trained_card_class_id":sample["card_class_id"],
        "split_counts":sample["split_counts"],
        "checkpoint_directory":str(output),
        "weights_available_and_evaluated":False,
        "test_split_evaluated_in_training_launcher":False,
        "note":"Inspect checkpoint_best_total.pth and validate via compare_rfdetr.py on untouched TEST; do not claim card/foil/authenticity/valuation accuracy.",
    }
    output.mkdir(parents=True,exist_ok=True)
    (output/"BIGSTEN_TRAINING_RUN.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description="Fine-tune free RF-DETR Nano card detector on an authorized local YOLO TRAIN split")
    p.add_argument("--dataset",required=True,help="Private YOLO train/valid/test export")
    p.add_argument("--output",default="private/rfdetr-nano-card")
    p.add_argument("--epochs",type=int,default=12)
    p.add_argument("--batch-size",type=int,default=2)
    p.add_argument("--allow-cpu",action="store_true")
    p.add_argument("--confirm-dataset-permission",action="store_true")
    args=p.parse_args(argv)
    r=train_private_card_detector(
        args.dataset,args.output,epochs=args.epochs,
        batch_size=args.batch_size,allow_cpu=args.allow_cpu,
        confirm_permission=args.confirm_dataset_permission)
    print(json.dumps(r,indent=2,ensure_ascii=False))
    print("NEXT: Run compare_rfdetr.py on the independently held-out TEST split.")
    print("No exact Pokémon card identities or artwork/commercial rights verified.")


if __name__=="__main__":
    main()

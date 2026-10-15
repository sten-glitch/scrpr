"""Local environment and optional dataset/checkpoint preflight; never trains."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
from pathlib import Path


def inspect_local(dataset=None, checkpoint=None, require_cuda=False):
    report={"python":platform.python_version(),"platform":platform.platform(),
            "packages":{},"errors":[],"training_started":False,
            "real_photo_accuracy_measured":False}
    for package in ("rfdetr","torch","torchvision","pytorch-lightning","supervision",
                    "opencv-python-headless","numpy","Pillow"):
        try:
            report["packages"][package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            report["errors"].append(f"Missing package: {package}")
    try:
        import torch
        import torchvision
        from rfdetr import RFDETRNano
        from rfdetr.detr import RFDETR
        from rfdetr.config import TrainConfig
        from rfdetr.training import trainer
        if report["packages"].get("rfdetr")!="1.11.2":
            raise RuntimeError("This integration is validated against rfdetr==1.11.2")
        if not (callable(RFDETR.from_checkpoint) and callable(RFDETRNano.train)
                and "run_test" in TrainConfig.model_fields):
            raise RuntimeError("Unsupported RF-DETR runtime API")
        cuda=torch.cuda.is_available()
        report["cuda_available"]=cuda
        report["torch_cuda_version"]=torch.version.cuda
        if require_cuda and not cuda:
            report["errors"].append("CUDA unavailable in this PyTorch installation")
        device="cuda" if cuda else "cpu"
        # Exercise an actual kernel, not only driver discovery.
        tensor=torch.ones((16,16),device=device)
        report["tensor_kernel_ok"]=bool(torch.all(tensor@tensor==16).item())
        if not report["tensor_kernel_ok"]:
            raise RuntimeError("Tensor kernel returned unexpected values")
        if cuda:
            props=torch.cuda.get_device_properties(0)
            report["gpu"]={"name":props.name,"vram_bytes":props.total_memory}
        report["vendor_api_import_ok"]=True
    except Exception as exc:
        report["errors"].append(f"RF-DETR runtime: {type(exc).__name__}: {exc}")
    if dataset:
        try:
            from train_rfdetr_card import audit_training_dataset,verify_vendor_dataset
            from local_cv import _checked_image
            report["dataset"]=audit_training_dataset(dataset)
            verify_vendor_dataset(dataset)
            from train_rfdetr_card import _files
            for split in ("train","valid","test"):
                for photo in _files(Path(dataset)/split/"images"):
                    _checked_image(photo.read_bytes())
            report["dataset_decode_ok"]=True
        except Exception as exc:
            report["errors"].append(f"Dataset: {type(exc).__name__}: {exc}")
    if checkpoint:
        try:
            import numpy as np
            from rfdetr_card_detector import RFDETRCardDetector
            model=RFDETRCardDetector(checkpoint)
            boxes=model(np.zeros((384,384,3),dtype=np.uint8))
            report["checkpoint"]={"sha256":model.checkpoint_sha256,
                                  "card_class_id":model.card_class_id,
                                  "synthetic_frame_boxes":len(boxes)}
        except Exception as exc:
            report["errors"].append(f"Checkpoint: {type(exc).__name__}: {exc}")
    report["next_requirements"]=[]
    if not dataset:
        report["next_requirements"].append("Provide an authorized labeled train/valid/test dataset")
    if not checkpoint:
        report["next_requirements"].append("Provide a trusted card-fine-tuned Nano checkpoint for inference")
    report["status"]="FAILED" if report["errors"] else "LOCAL_PREFLIGHT_PASSED"
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset")
    parser.add_argument("--checkpoint",help="Only your trusted local Nano checkpoint")
    parser.add_argument("--require-cuda",action="store_true")
    parser.add_argument("--out",default="private/rfdetr-preflight.json")
    args=parser.parse_args()
    report=inspect_local(args.dataset,args.checkpoint,args.require_cuda)
    output=Path(args.out)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2,ensure_ascii=False))
    return 1 if report["errors"] else 0


if __name__=="__main__":
    raise SystemExit(main())

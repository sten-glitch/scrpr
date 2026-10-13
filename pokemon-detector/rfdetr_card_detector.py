"""BIGSTEN RF-DETR Nano optional card detector (offline, fine-tuned only).

Official RF-DETR documentation:
  https://rfdetr.roboflow.com/latest/learn/run/detection/
  https://rfdetr.roboflow.com/latest/learn/train/

The off-the-shelf RFDETRNano COCO checkpoint has NO Pokemon/trading-card
category; a COCO "book" or "cell phone" prediction MUST NEVER count as
a Pokemon card detection. Therefore this adapter requires a locally present,
trusted fine-tuned checkpoint and a class explicitly named 'card', 'pokemon
card', or 'trading card'. It NEVER silently downloads weights.

The model emits provisional card BOXES ONLY. Edition, finish, foil,
condition, slab authenticity and price are outside its scope.

Do not load untrusted .pth/.ckpt files: serialized PyTorch checkpoints may
execute code during deserialization depending on torch/rfdetr version.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

from external_detection_benchmark import DetectionBenchmarkError

CARD_CLASSES=frozenset(("card","pokemon card","pokémon card",
                         "trading card","pokemon tcg card","pokémon tcg card"))
MAX_CHECKPOINT_BYTES=2*1024*1024*1024


class RFDETRCardError(ValueError):
    pass


def _class_positions(class_names) -> frozenset[int]:
    """Only exact dedicated trading-card labels, never COCO lookalikes."""
    if isinstance(class_names,dict):
        rows=list(class_names.items())
    elif isinstance(class_names,(list,tuple)):
        rows=list(enumerate(class_names))
    else:
        raise RFDETRCardError("Checkpoint must expose class_names for every class")
    positions=[]
    for key,label in rows:
        if type(key) is not int or key < 0 or not isinstance(label,str):
            raise RFDETRCardError("Malformed checkpoint class_names")
        if " ".join(label.casefold().strip().replace("-"," ").replace("_"," ").split()) in CARD_CLASSES:
            positions.append(key)
    if len(positions)!=1:
        raise RFDETRCardError(
            "Checkpoint must have exactly one specific 'card' / 'pokemon card' "
            "/ 'trading card' class. COCO-pretrained weights cannot score "
            "trading-card detection without fine-tuning."
        )
    return frozenset(positions)


def _normalized_boxes(detections, *, class_id: int, width: int, height: int,
                      max_boxes=30) -> list[list[float]]:
    if width<=0 or height<=0 or type(class_id) is not int:
        raise RFDETRCardError("Invalid image dimensions or card class")
    try:
        xyxy=detections.xyxy
        ids=detections.class_id
    except (AttributeError,TypeError) as exc:
        raise RFDETRCardError("Expected supervision.Detections result") from exc
    if xyxy is None or ids is None or len(xyxy)!=len(ids):
        raise RFDETRCardError("Missing or inconsistent prediction boxes/classes")
    if len(xyxy)>1500:
        raise RFDETRCardError("Too many raw model predictions")
    result=[]
    for coords,category in zip(xyxy,ids):
        if int(category)!=class_id:
            continue
        if len(coords)!=4:
            raise RFDETRCardError("Bad RF-DETR xyxy shape")
        vals=[float(v) for v in coords]
        if not all(math.isfinite(v) for v in vals):
            raise RFDETRCardError("NaN/inf RF-DETR box")
        x0,y0,x1,y1=vals
        if x1<=x0 or y1<=y0:
            continue
        # Clamp minor overshoot caused by image resizing rounding.
        x0=max(0.0,min(1.0,x0/width))
        x1=max(0.0,min(1.0,x1/width))
        y0=max(0.0,min(1.0,y0/height))
        y1=max(0.0,min(1.0,y1/height))
        if x1<=x0 or y1<=y0:
            continue
        result.append([x0,y0,x1,y1])
    # This class deliberately abstains instead of dropping valid boxes to
    # create impressive precision numbers from cherry-picked top objects.
    if len(result)>max_boxes:
        raise RFDETRCardError("More trading cards detected than evaluation max_boxes")
    return result


class RFDETRCardDetector:
    """Local checkpoint predictor. Initializing never touches an API key."""
    def __init__(self, checkpoint: str | Path, *, threshold=.5,
                 max_boxes=30, loader=None):
        if type(threshold) not in (int,float) or not math.isfinite(threshold) or not 0<threshold<=1:
            raise RFDETRCardError("threshold must be in (0,1]")
        if type(max_boxes) is not int or not 1<=max_boxes<=100:
            raise RFDETRCardError("max_boxes must be 1..100")
        path=Path(checkpoint).expanduser().resolve()
        if (not path.is_file() or path.is_symlink()
                or path.suffix.lower() not in {".pth",".ckpt"}
                or not 1<=path.stat().st_size<=MAX_CHECKPOINT_BYTES):
            raise RFDETRCardError("Fine-tuned, local, trusted .pth/.ckpt checkpoint required")
        self.checkpoint_sha256=hashlib.sha256(path.read_bytes()).hexdigest()
        self.checkpoint_name=path.name
        self.threshold=float(threshold)
        self.max_boxes=max_boxes
        if loader is None:
            try:
                from rfdetr import RFDETR
            except (ImportError,RuntimeError) as exc:
                raise RFDETRCardError(
                    "Optional RF-DETR missing. Install in a local Python "
                    "environment with python -m pip install rfdetr."
                ) from exc
            loader=RFDETR.from_checkpoint
        # The checkpoint MUST be from a trusted fine-tuning run. Unlike
        # executable code, checkpoint weights are not safe to load from
        # arbitrary public links.
        try:
            model=loader(str(path))
        except Exception as exc:
            raise RFDETRCardError("Unable to open trusted RF-DETR checkpoint") from exc
        positions=_class_positions(model.class_names)
        self.card_class_id=next(iter(positions))
        self.model=model
        self.model_class_names=tuple(model.class_names) if isinstance(model.class_names,(list,tuple)) else dict(model.class_names)

    def __call__(self,bgr):
        """Return image-normalized candidate boxes for the dedicated card class."""
        if getattr(bgr,"ndim",None)!=3 or bgr.shape[2]!=3:
            raise RFDETRCardError("Expected OpenCV BGR 3-channel image")
        height,width=bgr.shape[:2]
        if not width or not height or width*height>12_000_000:
            raise RFDETRCardError("Bad or oversized image")
        try:
            import cv2
            from PIL import Image
            rgb=cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)
            frame=Image.fromarray(rgb)
            prediction=self.model.predict(frame,threshold=self.threshold)
        except Exception as exc:
            raise RFDETRCardError("RF-DETR local inference failed") from exc
        return _normalized_boxes(prediction,class_id=self.card_class_id,
                                 width=width,height=height,max_boxes=self.max_boxes)

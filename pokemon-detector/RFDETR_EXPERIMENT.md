# BIGSTEN — RF-DETR Nano vs OpenCV (P1 experiment)

**State (October 2026):** paired detector benchmark, RF-DETR card-only
checkpoint adapter, optional private trainer, private static HTML/JSON output,
and fail-closed CI tests are implemented. No actual fine-tuned checkpoint,
trained weights, or paid cloud model has been installed into this repo.

**RF-DETR Nano is not magically a Pokémon scanner.** The publicly pretrained
RFDETRNano is a general **COCO** detector. COCO has 80 classes (for example
books or cell phones), and *no* dedicated Pokémon or trading-card category.
The BIGSTEN adapter deliberately REJECTS that model for this experiment.
Do not use book/phone predictions as "cards"; that would mislead your buying
decisions. To compare fairly, you need a private Nano checkpoint fine-tuned
on actual legal card detection annotations.

Sources (verify before each upgrade):
- https://github.com/roboflow/rf-detr
- https://rfdetr.roboflow.com/latest/learn/run/detection/
- https://rfdetr.roboflow.com/latest/learn/train/
- https://rfdetr.roboflow.com/latest/learn/train/training-parameters/
- https://pypi.org/project/rfdetr/1.11.2/

Licensing: RF-DETR source and core Nano through Large models are Apache 2.0.
Special "Plus" variants are under different PML terms. The core model license
does **not** license third-party card photos, copyrighted Pokémon artwork,
hosted source data, logos, or reselling provider dataset access.

## A. Use a legally acquired YOLO dataset (private)

For bounding-box detection, download an authorized public Roboflow export
or use your own photographs and human annotations:

    .venv\Scripts\python.exe external_photo_sources.py roboflow --source detector

Roboflow official export requires ROBOFLOW_API_KEY in the local shell.
See WEB_IMAGE_DATASETS.md and start-full-photo-benchmark.ps1 for safe export.

Your private dataset must have:

    private/roboflow-source/
      data.yaml
      train/images/
      train/labels/
      valid/images/
      valid/labels/
      test/images/
      test/labels/

The class YAML must contain exactly one dedicated "card" category for this
starter experiment. Other classes may coexist (e.g. background), but the
RF-DETR adapter only accepts a specific class named card, pokemon card or
trading card in the fine-tuned checkpoint. Exact printed edition, foil,
grade and authenticity are NOT implied by the class.

No image assets or annotations may be committed to the public GitHub repo.
Use a clean, human-reviewed TEST split, never a reused train photo.
The training gate excludes byte-identical cross-split photo leakage, but
cannot automatically catch transformed near-duplicates.

## B. Install the OPTIONAL inference libraries on Windows

On your own PC from the pokemon-detector directory, open PowerShell:

    py -3 -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements-rfdetr.txt

This installs RF-DETR 1.11.2 and free local libraries. PyTorch libraries and
model weight files are large; CPU can be slow. Initial checkpoint download
requires internet but inference afterward runs locally. Check PyTorch's
official GPU installation instructions for your actual NVIDIA GPU/driver.

Do NOT install RF-DETR in the ordinary inexpensive BIGSTEN alpha CI, and
do not upload untrusted .pth/.ckpt file bytes or Python pickle objects.

## C. Fine-tune an RF-DETR Nano checkpoint (optional GPU work)

Training requires the extra local training dependencies and permission for
the source images and annotations:

    .venv\Scripts\python.exe -m pip install "rfdetr[train]==1.11.2"
    .venv\Scripts\python.exe train_rfdetr_card.py --dataset private/roboflow-source --output private/rfdetr-nano-card --epochs 12 --batch-size 2 --confirm-dataset-permission

**NO TRAINING HAS RUN JUST BY ADDING THESE COMMANDS.**

- By default, the trainer requires a CUDA GPU. To explicitly permit CPU-only
  training add --allow-cpu, which may consume considerable time/RAM/power.
- The trainer requires TRAIN, VALID and untouched TEST subdirectories,
  the expected YOLO card class and non-overlapping SHA-256 image hashes.
- The user permissions flag is an attestation, not a legal verification.
- Model weights and output remain under ignored private/.
- The official model may fetch an initial pretrained Apache-licensed
  checkpoint from Roboflow's release assets. That is not a paid hosted API.
- Checkpoint artifacts can differ by RF-DETR version. Look for the
  checkpoint_best_total.pth produced by this version; use only your
  own trusted model weights. Loading arbitrary third-party torch checkpoints
  may be unsafe.

If dataset size is tiny or unlabeled, do not expect reliable detection:
capture/annotate more diverse images and add hard negatives.

## D. Run identical photo comparison (requires trained checkpoint)

After training, use an independently held-out TEST set. Do not keep
optimizing threshold on it:

    .venv\Scripts\python.exe compare_rfdetr.py private/roboflow-source --source detector --checkpoint private/rfdetr-nano-card/checkpoint_best_total.pth --split test --max-images 300 --iou 0.5 --confidence 0.5 --out private/rfdetr-vs-opencv

Open:

    private/rfdetr-vs-opencv.html
    private/rfdetr-vs-opencv.json

The paired evaluation reuses external_detection_benchmark.py for both
engines, with **the same**:
- TEST/VALID photographs and expected YOLO boxes
- exclusions for exact train/test duplicates
- class mapping, max card count and minimum IoU
- one-to-one matching for true positive, false positive and missed boxes

BIGSTEN refuses to report results when different images or expected
annotation boxes are evaluated. RF-DETR load/predict failures abort the
experiment; they are not quietly reclassified as "bad photo" exclusions.
Photo-level errors appear side by side.

The report gives box precision, recall, F1, true/false positives and misses.
There are NO product IDs, editions, authentic grades, sold prices,
valuation differences, or investment returns in this comparison.

## E. Release decision — only with actual trained model and real data

For P1 research, decide whether RF-DETR is worth its extra compute only
after a representative, independently annotated dataset has been tested.
Prioritize false positive rate on negative scenes, missed binder cards and
difficult foil/reflection and phone-shot images.

- If the RF-DETR model has better measured recall/precision and acceptable
  inference costs on your Windows laptop, test it in a separate private beta.
- If an untrained or COCO checkpoint is the only available model, keep
  OpenCV as the current prototype. We must not produce made-up accuracy.
- Independent physical card identity and price checking still require
  BIGSTEN pHash/ORB, set-number-foil verification, authenticated sold comps
  and human approval. Detector boxes alone will never be buy signals.
- Commercial deployment requires data/artwork licenses, model weights/source
  rights, multi-tenant security, measured false decisions and full data costs.

The default BIGSTEN web application and public detector remain untouched;
this experiment exists only in the draft development branch.

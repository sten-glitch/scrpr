# RF-DETR benchmark status

Existing Nano integration and paired detection benchmarks remain optional.
`compare_rfdetr.compare_reports` checks image and annotation hashes, matching splits
and class maps; generic COCO weights are not accepted as trading-card weights.
No new RF-DETR default path was activated for graded labels.

The [upstream repository](https://github.com/roboflow/rf-detr) lists Apache-2.0
for core code. This does not establish the rights for every model variant, dataset
or card artwork. This checkout pins rfdetr 1.11.2; Plus-specific terms require a
separate check before any use. No new model/download/license acceptance occurred.

RTX 4050 6GB CUDA setup was verified in the previous local preflight. A dedicated
trained label checkpoint and labeled graded-image holdout are missing. Thus no
CPU/GPU inference latency, VRAM, label recall/IoU or downstream certificate exact
match has been measured for RF-DETR. Existing OpenCV geometry tests are synthetic.

Next comparison: same rights-cleared heldout images and annotations for existing
OpenCV localization, OCR-first label proposals and fine-tuned RF-DETR proposals.
Report localization IoU/recall, certificate exact match, latency and native memory;
adopt RF-DETR only after a measured useful improvement. See RFDETR_EXPERIMENT.md
for training/paired geometry commands and CERTIFICATE_OCR.md for OCR benchmarking.

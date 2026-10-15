# Certificate OCR

`certificate_reader.read_slab_certificate(bytes, grader_hint=None)` uses the
existing bounded decoder, now with EXIF orientation normalization, and Tesseract.
Two geometric label regions on an upright single-slab image are attempted;
each OCR call times out after three seconds. A semaphore bounds concurrent readers
to two. Coordinates, source/crop hashes, original text and errors survive parsing.
PSA, Beckett/BGS and CGC text markers are tested. Digit substitutions are never
automatic; contradictory graders/certificates abstain. Scores are explicitly
uncalibrated heuristics, not probabilities. Short explicit numbers remain evidence
but are not selected. This is not an exhaustive official certificate format grammar.

Runtime blocker: no Tesseract executable found on PATH. Python OCR wrapper is
installed. The HTTP endpoint reports unavailable; it does not invent text.
Japanese identity metadata works; Japanese OCR language data has not been installed
or evaluated. Perspective correction, multi-slab localization and calibrated
company-specific templates remain planned.

`certificate_benchmark.py manifest.json --image-root private/holdout` validates
reviewer, rights_basis, truth_source, original SHA and heldout declarations.
See its module docstring for the manifest schema. Reports exact match including
failures, clear-label results, latency and Python-only peak memory. At least 50
real independent clear-photo groups are required by the eligibility gate; passing
that sampling gate is separate from meeting accuracy targets. Fixtures do not qualify.

PSA exposes an authenticated [official API](https://www.psacard.com/publicapi).
No PSA credentials or registry calls were available. Beckett verification API access
has not been established. Verification stays `unavailable`; authenticity `unknown`.

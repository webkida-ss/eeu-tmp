# RM-12C initial workflow reproduction

Five exact baseline/test sources are frozen from the network-denied container.
Canonical focused test:backend:unit reported two failures and two passes. The
synchronous response-building case reproduces known cost 17 being replaced by
reservation 13. The complete measured preload control used a non-verbatim sentence,
triggering unintended fallback and failure; that fixture requires correction.
The above-floor shadow timeout case alone already passes baseline and is not
sufficient proof of the sticky-uncertainty defect. Below-floor and enforced
workflow cases are required alongside boundary regressions.

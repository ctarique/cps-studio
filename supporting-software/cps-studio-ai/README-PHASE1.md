# Offline AI loading and data-quality boundary (AI 0.1.3)

The AI pipeline is offline supplementary analysis. It has no authorization, HMAC, STOP, recovery, or actuator authority. The four feature definitions and IsolationForest parameters are unchanged.

## Trusted executable models

joblib/pickle deserialization may execute Python code. Calibration and scoring now require explicit `--trust-model` and an independently retained, trusted training manifest. Use this flag only when the local model, manifest, and calibration supplier are trusted. A matching SHA-256 establishes byte identity; it does not authenticate a supplier, approve executable code, or make an untrusted model safe.

Before deserialization the pipeline validates the manifest schema, feature order, fixed estimator parameters, observer/analytics schema versions, minimum window count, provenance, and Python major/minor plus exact NumPy/scikit-learn/joblib versions. It compares model SHA-256 to the manifest, then loads exactly those verified bytes through BytesIO. Scoring additionally checks the calibration schema and binds it to the model and the exact training manifest bytes. Wrong-hash or malformed metadata is rejected before joblib.load.

Examples (all paths are local; no Gateway connection is made):

```sh
python3 iforest_pipeline.py train \
  --input retained-training-features.jsonl --output-dir new-model \
  --capture-id retained-training-id --dataset-role TRAIN

python3 iforest_pipeline.py calibrate \
  --model new-model/model.joblib --manifest new-model/manifest.json \
  --input retained-calibration-features.jsonl --output calibration.json \
  --capture-id retained-calibration-id --dataset-role CALIBRATION \
  --quantile 0.05 --trust-model

python3 iforest_pipeline.py score \
  --model new-model/model.joblib --manifest new-model/manifest.json \
  --calibration calibration.json --input retained-evaluation-features.jsonl \
  --output scored.jsonl --trust-model
```

Existing historical model/calibration artifacts are preserved. Older artifacts without the new provenance or runtime metadata are rejected by this loader; the correction does not silently recertify or migrate them. Train fresh development artifacts from suitable retained data, and separately establish research acceptance.

## Observation quality and declared independence

Actual telemetry is eligible only with current Observer 0.1.3/Analytics 0.1.2, complete ten-second windows, telemetry quality schema 1, valid parse/lifecycle/temporal coverage, known loss accounting, zero recorded perf-buffer lost events, and zero recorded kernel submit failures. Missing historical loss information remains unknown and cannot establish complete benign observation.

Training and calibration retain each eligible window's observation_id and UTC start/end. Duplicate or overlapping windows within either dataset are rejected. Calibration must have a different dataset hash and capture label, different observation IDs, and nonoverlapping UTC acquisition windows. Missing provenance is rejected. These checks validate declared records, not authentic acquisition or statistically independent distributions; retain original event hashes, acquisition plans, trusted capture identity, and clock synchronization evidence.

Synthetic fixtures may explicitly identify themselves as SYNTHETIC_DEVELOPMENT_ONLY. That existing development exception remains, while provenance is still required. Generated manifests/calibrations identify synthetic window counts and source types. Such artifacts establish software workflow checks only. Neither a ten-window minimum, fixed random state, calibration quantile, nor synthetic workflow demonstrates detection accuracy.

## Numerical checks

Required event counts and any supplied aggregate counters must be finite, nonnegative integral values. The balance remains the original rounded minimum/maximum CAM/CAR ratio in [0,1]; contradictory supplied aggregates are rejected. Invalid deterministic unexpected-event counters cannot be treated as zero benign events. Threshold and model raw scores must be finite in [-1,0], consistent with IsolationForest.score_samples; quantile must be finite and strictly between zero and one. Malformed calibration schemas, unsupported models, dependency mismatch, and invalid input rows fail without a NORMAL result.

Local input files and model artifacts should be retained immutable during analysis. This loader is a trust gate and consistency check, not a signature system or a sandbox for hostile pickle.

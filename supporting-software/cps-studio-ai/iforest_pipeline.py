#!/usr/bin/python3

import argparse
import datetime
import hashlib
import io
import json
import math
import platform
from collections import Counter
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import IsolationForest


AI_VERSION = "0.1.3"

EXPECTED_OBSERVER_VERSION = "0.1.3"
EXPECTED_ANALYTICS_VERSION = "0.1.2"
EXPECTED_WINDOW_SECONDS = 10

FEATURES = [
    "cam_connections",
    "car_connections",
    "expected_route_execs",
    "device_balance",
]

MODEL_PARAMETERS = {
    "n_estimators": 256,
    "max_samples": "auto",
    "contamination": "auto",
    "random_state": 42,
    "n_jobs": 1,
    "bootstrap": False,
}


def utc_now():
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def sha256_file(path):
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def read_jsonl(path):
    rows = []

    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(
                    f"Invalid JSON line {number}: {exc}"
                )

            if not isinstance(row, dict):
                raise SystemExit(f"Invalid JSON line {number}: expected an object")
            rows.append(row)

    return rows


COUNTER_FIELDS = (
    "cam_connections", "car_connections", "expected_route_execs",
    "unexpected_connections", "unexpected_execs",
    "expected_device_connections", "expected_local_connections",
    "unique_destinations", "total_connections", "total_execs",
    "total_security_events", "telemetry_lost_events", "telemetry_submit_failures",
)
PROVENANCE_SCHEMA = 1
INDEPENDENCE_CHECK = "DECLARED_NONOVERLAPPING_OBSERVATIONS_AND_WINDOWS"


def numeric(value, label, integral=False, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid {label}")
    try:
        number = float(value)
    except (OverflowError, ValueError):
        raise ValueError(f"invalid {label}") from None
    if not math.isfinite(number):
        raise ValueError(f"non-finite {label}")
    if integral and (number != math.floor(number) or value != int(number)):
        raise ValueError(f"non-integral {label}")
    if minimum is not None and number < minimum:
        raise ValueError(f"out-of-range {label}")
    if maximum is not None and number > maximum:
        raise ValueError(f"out-of-range {label}")
    return number


def read_metadata(path, with_hash=False):
    try:
        data = path.read_bytes()
        value = json.loads(
            data, parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"nonfinite JSON value {value}")))
        if not isinstance(value, dict):
            raise ValueError("metadata must be an object")
        return (value, hashlib.sha256(data).hexdigest()) if with_hash else value
    except (OSError, UnicodeError, ValueError) as exc:
        raise SystemExit(f"Invalid metadata {path.name}: {exc}") from exc


def require_hash(value, label):
    if (not isinstance(value, str) or len(value) != 64 or
            any(char not in "0123456789abcdef" for char in value)):
        raise ValueError(f"invalid {label}")


def require_label(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing {label}")


def window_provenance(rows):
    """Validate declared acquisition identities and UTC intervals, not authenticity."""
    result = []
    for row in rows:
        item = {key: row.get(key) for key in (
            "observation_id", "window_start", "window_end")}
        require_label(item["observation_id"], "observation_id")
        starts = []
        for key in ("window_start", "window_end"):
            require_label(item[key], key)
            try:
                stamp = datetime.datetime.fromisoformat(
                    item[key].replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"invalid {key}") from exc
            if stamp.tzinfo is None or stamp.utcoffset() != datetime.timedelta(0):
                raise ValueError(f"{key} must declare UTC")
            starts.append(stamp)
        if (starts[1] - starts[0]).total_seconds() != EXPECTED_WINDOW_SECONDS:
            raise ValueError("provenance window size mismatch")
        result.append(item)
    intervals = sorted(
        (datetime.datetime.fromisoformat(p["window_start"].replace("Z", "+00:00")),
         datetime.datetime.fromisoformat(p["window_end"].replace("Z", "+00:00")))
        for p in result)
    if any(current[0] < previous[1]
           for previous, current in zip(intervals, intervals[1:])):
        raise ValueError("duplicate or overlapping windows within dataset")
    return result


def require_independent(training, calibration):
    # Different file hashes or user labels alone never establish independence.
    if not training or not calibration:
        raise ValueError("window provenance required for independence checks")
    training = window_provenance(training)
    calibration = window_provenance(calibration)
    observations = {p["observation_id"] for p in training}
    if observations.intersection(p["observation_id"] for p in calibration):
        raise ValueError("training and calibration reuse an observation")
    intervals = sorted(
        (datetime.datetime.fromisoformat(p["window_start"].replace("Z", "+00:00")),
         datetime.datetime.fromisoformat(p["window_end"].replace("Z", "+00:00")),
         group)
        for group, records in enumerate((training, calibration))
        for p in records)
    if any(current[0] < previous[1] and current[2] != previous[2]
           for previous, current in zip(intervals, intervals[1:])):
        raise ValueError("training and calibration acquisition windows overlap")


def validate_manifest(manifest):
    try:
        expected = {
            "ai_version": AI_VERSION, "purpose": "DEVELOPMENT_ONLY",
            "features": FEATURES, "model": "IsolationForest",
            "model_parameters": MODEL_PARAMETERS,
            "expected_observer_version": EXPECTED_OBSERVER_VERSION,
            "expected_analytics_version": EXPECTED_ANALYTICS_VERSION,
            "expected_window_seconds": EXPECTED_WINDOW_SECONDS,
            "requires_complete_windows": True,
            "provenance_schema": PROVENANCE_SCHEMA,
            "numpy_version": np.__version__, "sklearn_version": sklearn.__version__,
            "joblib_version": joblib.__version__,
        }
        for key, value in expected.items():
            if manifest.get(key) != value or (
                    isinstance(value, bool) and manifest.get(key) is not value) or (
                    type(value) is int and type(manifest.get(key)) is not int):
                raise ValueError(f"training manifest {key} mismatch")
        if (str(manifest.get("python_version", "")).split(".")[:2] !=
                platform.python_version().split(".")[:2]):
            raise ValueError("training manifest Python runtime mismatch")
        for key in ("model_sha256", "source_sha256"):
            require_hash(manifest.get(key), key)
        for key in ("capture_id", "dataset_role"):
            require_label(manifest.get(key), key)
        count = numeric(manifest.get("eligible_training_windows"),
                        "eligible_training_windows", integral=True, minimum=10)
        numeric(manifest.get("source_records"), "source_records",
                integral=True, minimum=count)
        records = manifest.get("eligible_window_provenance")
        if not isinstance(records, list) or len(records) != count:
            raise ValueError("training window provenance count mismatch")
        window_provenance(records)
    except (ValueError, TypeError, AttributeError) as exc:
        raise SystemExit(f"Invalid training manifest: {exc}") from exc
    return manifest


def verified_model_bytes(model_path, manifest):
    try:
        payload = model_path.read_bytes()
    except OSError as exc:
        raise SystemExit(f"Cannot read model: {exc}") from exc
    if hashlib.sha256(payload).hexdigest() != manifest["model_sha256"]:
        raise SystemExit("Model hash does not match trusted training manifest.")
    return payload


def validate_calibration(calibration, manifest, manifest_path, manifest_sha256=None):
    try:
        expected = {
            "calibration_schema": 1, "ai_version": AI_VERSION,
            "purpose": "DEVELOPMENT_ONLY", "features": FEATURES,
            "method": "BENIGN_SCORE_QUANTILE",
            "comparison": "AI_REVIEW_IF_RAW_SCORE_LT_THRESHOLD",
            "model_sha256": manifest["model_sha256"],
            "model_manifest_sha256": manifest_sha256 or sha256_file(manifest_path),
            "training_capture_id": manifest["capture_id"],
            "training_source_sha256": manifest["source_sha256"],
            "provenance_schema": PROVENANCE_SCHEMA,
            "independence_check": INDEPENDENCE_CHECK,
        }
        for key, value in expected.items():
            if (calibration.get(key) != value or
                    (type(value) is int and type(calibration.get(key)) is not int)):
                raise ValueError(f"calibration {key} mismatch")
        numeric(calibration.get("threshold"), "threshold", minimum=-1, maximum=0)
        quantile = numeric(calibration.get("quantile"), "quantile")
        if not 0 < quantile < 1:
            raise ValueError("quantile must be between 0 and 1")
        count = numeric(calibration.get("eligible_calibration_windows"),
                        "eligible_calibration_windows", integral=True, minimum=10)
        numeric(calibration.get("source_records"), "source_records",
                integral=True, minimum=count)
        require_hash(calibration.get("calibration_source_sha256"),
                     "calibration_source_sha256")
        require_label(calibration.get("calibration_capture_id"),
                      "calibration_capture_id")
        if (calibration["calibration_capture_id"] == manifest["capture_id"] or
                calibration["calibration_source_sha256"] == manifest["source_sha256"]):
            raise ValueError("calibration reuses training dataset identity")
        records = calibration.get("eligible_window_provenance")
        if not isinstance(records, list) or len(records) != count:
            raise ValueError("calibration window provenance count mismatch")
        require_independent(manifest["eligible_window_provenance"], records)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise SystemExit(f"Invalid calibration: {exc}") from exc
    return calibration


def validate_scores(scores, expected_count):
    values = list(scores)
    if len(values) != expected_count:
        raise SystemExit("Model returned an unexpected score count.")
    try:
        for value in values:
            numeric(value.item() if hasattr(value, "item") else value,
                    "model raw score", minimum=-1, maximum=0)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    return scores


def validate_feature_vector(row, number):
    if not isinstance(row, dict):
        raise ValueError(f"line {number}: feature row must be an object")
    for feature in FEATURES + ["unexpected_connections", "unexpected_execs"]:
        if feature not in row:
            raise ValueError(f"line {number}: missing {feature}")
    for field in COUNTER_FIELDS:
        if field in row:
            numeric(row[field], f"line {number}: {field}",
                    integral=True, minimum=0)
    balance = numeric(row["device_balance"], f"line {number}: device_balance",
                      minimum=0, maximum=1)
    cam, car = row["cam_connections"], row["car_connections"]
    expected_balance = round(min(cam, car) / max(cam, car), 4) if max(cam, car) else 0
    if abs(balance - expected_balance) > 0.0000001:
        raise ValueError(f"line {number}: inconsistent device_balance")

    relationships = [
        ("expected_device_connections", ("cam_connections", "car_connections")),
        ("total_connections", ("expected_device_connections",
                               "expected_local_connections", "unexpected_connections")),
        ("total_execs", ("expected_route_execs", "unexpected_execs")),
        ("total_security_events", ("total_connections", "total_execs")),
    ]
    for total, parts in relationships:
        if total in row and all(part in row for part in parts):
            if row[total] != sum(row[part] for part in parts):
                raise ValueError(f"line {number}: inconsistent {total}")
    # Bounds use only supplied disjoint counters; absent fields remain absent.
    known_connections = cam + car + row["unexpected_connections"]
    if "expected_local_connections" in row:
        known_connections += row["expected_local_connections"]
    known_execs = row["expected_route_execs"] + row["unexpected_execs"]
    if ("total_connections" in row and
            row["total_connections"] < known_connections):
        raise ValueError(f"line {number}: inconsistent total_connections")
    exact_connections = row.get("total_connections")
    if exact_connections is None and "expected_local_connections" in row:
        # All connection classes are supplied even if their aggregate is absent.
        exact_connections = known_connections
    if "total_security_events" in row:
        known_security_events = (
            exact_connections if exact_connections is not None else known_connections
        ) + known_execs
        if (row["total_security_events"] < known_security_events or
                (exact_connections is not None and
                 row["total_security_events"] != known_security_events)):
            raise ValueError(f"line {number}: inconsistent total_security_events")
    if "unique_destinations" in row:
        destinations = row["unique_destinations"]
        if (destinations == 0 and (
                known_connections > 0 or
                (exact_connections is not None and exact_connections > 0))):
            raise ValueError(f"line {number}: impossible zero unique_destinations")
        if exact_connections is not None and destinations > exact_connections:
            raise ValueError(f"line {number}: impossible unique_destinations")
    return [float(row[feature]) for feature in FEATURES]


def schema_reason(row):
    if not isinstance(row, dict):
        return "INVALID_FEATURE_ROW"
    if row.get("observer_version") != EXPECTED_OBSERVER_VERSION:
        return "OBSERVER_VERSION_MISMATCH"
    if row.get("analytics_version") != EXPECTED_ANALYTICS_VERSION:
        return "ANALYTICS_VERSION_MISMATCH"
    synthetic = row.get("source_type") == "SYNTHETIC_DEVELOPMENT_ONLY"
    if row.get("window_seconds") != EXPECTED_WINDOW_SECONDS and not synthetic:
        return "WINDOW_SIZE_MISMATCH"
    if row.get("window_complete") is not True and not synthetic:
        return "WINDOW_NOT_COMPLETE"
    if not synthetic:
        if (type(row.get("telemetry_quality_schema")) is not int or
                row.get("telemetry_quality_schema") != 1 or
                row.get("window_temporal_coverage") is not True or
                row.get("telemetry_parse_valid") is not True or
                row.get("telemetry_lifecycle_valid") is not True):
            return "TELEMETRY_QUALITY_UNVERIFIED"
        if row.get("telemetry_loss_accounting") != "known":
            return "TELEMETRY_LOSS_UNKNOWN"
        for field in ("telemetry_lost_events", "telemetry_submit_failures"):
            lost = row.get(field)
            if isinstance(lost, bool) or not isinstance(lost, int) or lost != 0:
                return "TELEMETRY_LOSS_INVALID_OR_NONZERO"
    return None


def deterministic_reasons(row):
    reasons = []
    for field, missing, detected in (
        ("unexpected_connections", "MISSING_UNEXPECTED_CONNECTION_FIELD",
         "UNEXPECTED_DESTINATION"),
        ("unexpected_execs", "MISSING_UNEXPECTED_EXEC_FIELD", "UNEXPECTED_EXEC"),
    ):
        if row.get(field) is None:
            reasons.append(missing)
            continue
        value = numeric(row[field], field, integral=True, minimum=0)
        if value > 0:
            reasons.append(detected)
    return reasons


def eligible_benign_rows(path):
    rows = read_jsonl(path)
    eligible, matrix, exclusions = [], [], Counter()
    for number, row in enumerate(rows, start=1):
        schema = schema_reason(row)
        if schema:
            exclusions[schema] += 1
            continue
        try:
            values = validate_feature_vector(row, number)
            reasons = deterministic_reasons(row)
        except ValueError:
            exclusions["INVALID_FEATURE_VECTOR"] += 1
            continue
        if reasons:
            exclusions["DETERMINISTIC_SECURITY_EVENT"] += 1
            continue
        eligible.append(row)
        matrix.append(values)
    return rows, eligible, np.asarray(matrix, dtype=np.float64), exclusions


def load_bundle(model_path, manifest_path, trust_model=False):
    manifest = validate_manifest(read_metadata(manifest_path))
    payload = verified_model_bytes(model_path, manifest)
    return _load_verified_bundle(payload, manifest, trust_model)


def _load_verified_bundle(payload, manifest, trust_model=False):
    # joblib/pickle can execute code. A matching hash is identity, not authenticity.
    # The operator must trust the model supplier AND the independently retained manifest.
    if trust_model is not True:
        raise SystemExit(
            "Model loading requires explicit --trust-model for a trusted local model "
            "and training manifest; hashes do not authenticate their supplier.")
    manifest = validate_manifest(manifest)
    if hashlib.sha256(payload).hexdigest() != manifest["model_sha256"]:
        raise SystemExit("Verified model bytes no longer match the trusted manifest.")
    # Deserialize precisely the bytes checked above, avoiding a second path open.
    bundle = joblib.load(io.BytesIO(payload))
    if not isinstance(bundle, dict):
        raise SystemExit("Model bundle must be an object.")
    expected = {
        "ai_version": AI_VERSION, "observer_version": EXPECTED_OBSERVER_VERSION,
        "analytics_version": EXPECTED_ANALYTICS_VERSION,
        "window_seconds": EXPECTED_WINDOW_SECONDS, "features": FEATURES,
        "model_parameters": MODEL_PARAMETERS,
    }
    if any(bundle.get(key) != value for key, value in expected.items()):
        raise SystemExit("Model bundle version, feature schema or parameters mismatch.")
    model = bundle.get("model")
    if not isinstance(model, IsolationForest):
        raise SystemExit("Model estimator is not IsolationForest.")
    parameters = model.get_params(deep=False)
    if (any(parameters.get(key) != value for key, value in MODEL_PARAMETERS.items())
            or getattr(model, "n_features_in_", None) != len(FEATURES)):
        raise SystemExit("Model estimator parameters or feature count mismatch.")
    return bundle


def train(
    input_path,
    output_dir,
    capture_id,
    dataset_role,
):
    (
        rows,
        eligible,
        X,
        exclusions,
    ) = eligible_benign_rows(input_path)

    if len(eligible) < 10:
        raise SystemExit(
            "Fewer than 10 eligible benign windows."
        )

    try:
        require_label(capture_id, "capture_id")
        require_label(dataset_role, "dataset_role")
        provenance = window_provenance(eligible)
    except ValueError as exc:
        raise SystemExit(f"Training provenance invalid: {exc}") from exc

    model = IsolationForest(
        **MODEL_PARAMETERS
    )

    model.fit(X)

    scores = validate_scores(model.score_samples(X), len(eligible))

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    model_path = output_dir / "model.joblib"

    bundle = {
        "ai_version": AI_VERSION,
        "observer_version":
            EXPECTED_OBSERVER_VERSION,
        "analytics_version":
            EXPECTED_ANALYTICS_VERSION,
        "window_seconds":
            EXPECTED_WINDOW_SECONDS,
        "features":
            FEATURES,
        "model_parameters":
            MODEL_PARAMETERS,
        "model":
            model,
    }

    joblib.dump(
        bundle,
        model_path,
    )

    manifest = {
        "ai_version":
            AI_VERSION,

        "created_at":
            utc_now(),

        "purpose":
            "DEVELOPMENT_ONLY",

        "capture_id":
            capture_id,

        "dataset_role":
            dataset_role,

        "source_file":
            str(input_path),

        "source_sha256":
            sha256_file(input_path),

        "source_records":
            len(rows),

        "eligible_training_windows":
            len(eligible),

        "excluded_records":
            dict(exclusions),

        "expected_observer_version":
            EXPECTED_OBSERVER_VERSION,

        "expected_analytics_version":
            EXPECTED_ANALYTICS_VERSION,

        "expected_window_seconds":
            EXPECTED_WINDOW_SECONDS,

        "requires_complete_windows":
            True,

        "features":
            FEATURES,

        "model":
            "IsolationForest",

        "model_parameters":
            MODEL_PARAMETERS,

        "model_sha256":
            sha256_file(model_path),

        "python_version":
            platform.python_version(),

        "numpy_version":
            np.__version__,

        "sklearn_version":
            sklearn.__version__,

        "training_raw_score_summary": {
            "minimum":
                float(np.min(scores)),
            "median":
                float(np.median(scores)),
            "maximum":
                float(np.max(scores)),
        },

        "decision_policy": (
            "Isolation Forest score_samples() "
            "provides behavioral unusualness. "
            "NORMAL/REVIEW is assigned only after "
            "a separately retained benign "
            "calibration dataset defines a threshold."
        ),

        "interpretation": (
            "Lower scores indicate greater "
            "statistical unusualness in the declared "
            "feature space. A score does not "
            "independently establish malicious "
            "intent, physical danger, or authority "
            "to alter CPS operation."
        ),
    }

    manifest["source_types"] = sorted({row.get("source_type", "OBSERVED_TELEMETRY") for row in eligible})
    manifest["synthetic_development_windows"] = sum(
        row.get("source_type") == "SYNTHETIC_DEVELOPMENT_ONLY" for row in eligible)
    manifest["joblib_version"] = joblib.__version__
    manifest["provenance_schema"] = PROVENANCE_SCHEMA
    manifest["eligible_window_provenance"] = provenance
    validate_manifest(manifest)

    manifest_path = (
        output_dir / "manifest.json"
    )

    manifest_path.write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    print(
        "Source records:",
        len(rows),
    )

    print(
        "Eligible training windows:",
        len(eligible),
    )

    print(
        "Exclusions:",
        dict(exclusions),
    )

    print(
        "Raw score min:",
        float(np.min(scores)),
    )

    print(
        "Raw score median:",
        float(np.median(scores)),
    )

    print(
        "Raw score max:",
        float(np.max(scores)),
    )

    print(
        "Model:",
        model_path,
    )

    print(
        "Manifest:",
        manifest_path,
    )


def calibrate(
    model_path, manifest_path, input_path, output_path,
    capture_id, dataset_role, quantile, trust_model=False,
):
    manifest, manifest_sha = read_metadata(manifest_path, with_hash=True)
    manifest = validate_manifest(manifest)
    # Check model binding before inspecting or deserializing its executable content.
    payload = verified_model_bytes(model_path, manifest)
    try:
        require_label(capture_id, "capture_id")
        require_label(dataset_role, "dataset_role")
        quantile = numeric(quantile, "quantile")
        if not 0 < quantile < 1:
            raise ValueError("quantile must be between 0 and 1")
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    input_sha = sha256_file(input_path)
    if input_sha == manifest["source_sha256"]:
        raise SystemExit("Calibration dataset is identical to training dataset.")
    if capture_id == manifest["capture_id"]:
        raise SystemExit("Calibration capture ID must differ from training capture ID.")
    rows, eligible, X, exclusions = eligible_benign_rows(input_path)
    if len(eligible) < 10:
        raise SystemExit("Fewer than 10 eligible calibration windows.")
    try:
        provenance = window_provenance(eligible)
        require_independent(manifest["eligible_window_provenance"], provenance)
    except ValueError as exc:
        raise SystemExit(f"Calibration independence cannot be established: {exc}") from exc
    bundle = _load_verified_bundle(payload, manifest, trust_model)
    scores = validate_scores(bundle["model"].score_samples(X), len(eligible))
    threshold = float(np.quantile(scores, quantile, method="linear"))
    below = int(np.sum(scores < threshold))
    calibration = {
        "calibration_schema": 1, "ai_version": AI_VERSION,
        "created_at": utc_now(), "purpose": "DEVELOPMENT_ONLY",
        "features": FEATURES, "method": "BENIGN_SCORE_QUANTILE",
        "quantile": quantile, "comparison": "AI_REVIEW_IF_RAW_SCORE_LT_THRESHOLD",
        "threshold": threshold,
        "training_capture_id": manifest["capture_id"],
        "training_source_sha256": manifest["source_sha256"],
        "model_sha256": manifest["model_sha256"],
        "model_manifest_sha256": manifest_sha,
        "calibration_capture_id": capture_id,
        "calibration_dataset_role": dataset_role,
        "calibration_source_file": str(input_path),
        "calibration_source_sha256": input_sha,
        "source_records": len(rows), "eligible_calibration_windows": len(eligible),
        "excluded_records": dict(exclusions),
        "source_types": sorted({row.get("source_type", "OBSERVED_TELEMETRY") for row in eligible}),
        "synthetic_development_windows": sum(
            row.get("source_type") == "SYNTHETIC_DEVELOPMENT_ONLY" for row in eligible),
        "provenance_schema": PROVENANCE_SCHEMA,
        "eligible_window_provenance": provenance,
        "independence_check": INDEPENDENCE_CHECK,
        "calibration_raw_score_summary": {
            "minimum": float(np.min(scores)), "median": float(np.median(scores)),
            "maximum": float(np.max(scores)),
        },
        "windows_below_threshold": below,
        "observed_fraction_below_threshold": below / len(scores),
        "interpretation": (
            "This benign-score review policy is not an attack probability or an "
            "accuracy result. Declared observation IDs and nonoverlapping UTC windows "
            "are checked; acquisition authenticity and clock synchronization require "
            "retained external evidence."),
    }
    validate_calibration(calibration, manifest, manifest_path, manifest_sha)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(
        calibration, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8")
    print("Calibration windows:", len(eligible))
    print("Exclusions:", dict(exclusions))
    print("Quantile:", quantile)
    print("Threshold:", threshold)
    print("Windows below threshold:", below)
    print("Calibration:", output_path)


def score(
    model_path,
    calibration_path,
    input_path,
    output_path,
    manifest_path=None,
    trust_model=False,
):
    if manifest_path is None:
        raise SystemExit("Scoring requires the trusted training manifest.")
    manifest, manifest_sha = read_metadata(manifest_path, with_hash=True)
    manifest = validate_manifest(manifest)
    calibration = validate_calibration(
        read_metadata(calibration_path), manifest, manifest_path, manifest_sha)
    payload = verified_model_bytes(model_path, manifest)
    bundle = _load_verified_bundle(payload, manifest, trust_model)
    model = bundle["model"]
    threshold = calibration["threshold"]

    rows = read_jsonl(input_path)

    vectors = []

    for number, row in enumerate(
        rows,
        start=1,
    ):
        schema = schema_reason(row)

        if schema:
            raise SystemExit(
                f"line {number}: {schema}"
            )

        try:
            values = validate_feature_vector(
                row,
                number,
            )
        except ValueError as exc:
            raise SystemExit(str(exc))

        vectors.append(values)

    if not vectors:
        raise SystemExit(
            "No records to score."
        )

    X = np.asarray(
        vectors,
        dtype=np.float64,
    )

    scores = validate_scores(model.score_samples(X), len(rows))

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_path.open(
        "w",
        encoding="utf-8",
    ) as output:

        for row, raw_score in zip(
            rows,
            scores,
        ):
            raw_score = float(
                raw_score
            )

            ai_review = (
                raw_score < threshold
            )

            reasons = (
                deterministic_reasons(
                    row
                )
            )

            deterministic_review = bool(
                reasons
            )

            overall_review = (
                ai_review
                or deterministic_review
            )

            result = {
                **row,

                "ai_version":
                    AI_VERSION,

                "ai_model":
                    "IsolationForest",

                "ai_raw_score":
                    raw_score,

                "ai_threshold":
                    threshold,

                "ai_margin":
                    raw_score - threshold,

                "ai_prediction":
                    (
                        "REVIEW"
                        if ai_review
                        else "NORMAL"
                    ),

                "deterministic_reasons":
                    reasons,

                "deterministic_review":
                    deterministic_review,

                "overall_assessment":
                    (
                        "REVIEW"
                        if overall_review
                        else "NORMAL"
                    ),

                "interpretation": (
                    "AI REVIEW means statistically "
                    "unusual relative to the trained "
                    "and calibrated benign behavior. "
                    "It is not equivalent to a "
                    "confirmed attack."
                ),
            }

            output.write(
                json.dumps(
                    result,
                    separators=(",", ":"),
                    sort_keys=True,
                    allow_nan=False,
                ) + "\n"
            )

    print(
        "Scored records:",
        len(rows),
    )

    print(
        "Threshold:",
        threshold,
    )

    print(
        "Output:",
        output_path,
    )


def main():
    parser = argparse.ArgumentParser()

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    p = sub.add_parser("train")

    p.add_argument(
        "--input",
        type=Path,
        required=True,
    )

    p.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )

    p.add_argument(
        "--capture-id",
        required=True,
    )

    p.add_argument(
        "--dataset-role",
        required=True,
    )

    p = sub.add_parser("calibrate")
    p.add_argument("--trust-model", action="store_true",
                   help="Trust the local executable model and its training manifest supplier.")

    p.add_argument(
        "--model",
        type=Path,
        required=True,
    )

    p.add_argument(
        "--manifest",
        type=Path,
        required=True,
    )

    p.add_argument(
        "--input",
        type=Path,
        required=True,
    )

    p.add_argument(
        "--output",
        type=Path,
        required=True,
    )

    p.add_argument(
        "--capture-id",
        required=True,
    )

    p.add_argument(
        "--dataset-role",
        required=True,
    )

    p.add_argument(
        "--quantile",
        type=float,
        default=0.05,
    )

    p = sub.add_parser("score")
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--trust-model", action="store_true",
                   help="Trust the local executable model and its training manifest supplier.")

    p.add_argument(
        "--model",
        type=Path,
        required=True,
    )

    p.add_argument(
        "--calibration",
        type=Path,
        required=True,
    )

    p.add_argument(
        "--input",
        type=Path,
        required=True,
    )

    p.add_argument(
        "--output",
        type=Path,
        required=True,
    )

    args = parser.parse_args()

    if args.command == "train":
        train(
            args.input,
            args.output_dir,
            args.capture_id,
            args.dataset_role,
        )

    elif args.command == "calibrate":
        if not 0 < args.quantile < 1:
            raise SystemExit(
                "Quantile must be between 0 and 1."
            )

        calibrate(
            args.model,
            args.manifest,
            args.input,
            args.output,
            args.capture_id,
            args.dataset_role,
            args.quantile,
            trust_model=args.trust_model,
        )

    elif args.command == "score":
        score(
            args.model,
            args.calibration,
            args.input,
            args.output,
            manifest_path=args.manifest,
            trust_model=args.trust_model,
        )


if __name__ == "__main__":
    main()

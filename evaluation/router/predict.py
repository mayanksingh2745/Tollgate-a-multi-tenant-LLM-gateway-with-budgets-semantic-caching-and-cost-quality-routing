"""CLI utility and helper for single-query router prediction."""

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure root, apps, and packages/core/src are in sys.path
root_dir = Path(__file__).resolve().parents[2]
for p in [str(root_dir), str(root_dir / "apps"), str(root_dir / "packages" / "core" / "src")]:
    if p not in sys.path:
        sys.path.insert(0, p)

import joblib
from gateway.src.router.features import FEATURE_NAMES, extract_features
from gateway.src.schemas.chat import ChatCompletionRequest, ChatMessage

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tollgate.router.predict")

ARTIFACT_DIR = root_dir / "artifacts" / "router"


def predict_route(prompt: str, threshold: float | None = None) -> dict:
    """Predict route and confidence for a prompt using the saved model artifact."""
    model_path = ARTIFACT_DIR / "model.joblib"
    metadata_path = ARTIFACT_DIR / "metadata.json"

    if not model_path.exists() or not metadata_path.exists():
        raise FileNotFoundError(
            f"Artifacts not found in {ARTIFACT_DIR}. Run evaluation/router/train.py first."
        )

    pipeline = joblib.load(model_path)
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    decision_threshold = (
        threshold if threshold is not None else float(metadata.get("threshold", 0.7))
    )
    cheap_model = metadata.get("cheap_model", "mock-fast")
    strong_model = metadata.get("strong_model", "mock-model")

    request = ChatCompletionRequest(
        model="auto",
        messages=[ChatMessage(role="user", content=prompt)],
    )

    feat = extract_features(request)
    probs = pipeline.predict_proba([feat.to_list()])
    confidence = float(probs[0][1])

    if confidence >= decision_threshold:
        selected_model = cheap_model
        route = "cheap"
        reason = f"confidence_{confidence:.3f}_gte_threshold_{decision_threshold:.3f}"
    else:
        selected_model = strong_model
        route = "strong"
        reason = f"confidence_{confidence:.3f}_lt_threshold_{decision_threshold:.3f}"

    features_dict = dict(zip(FEATURE_NAMES, feat.to_list(), strict=True))

    return {
        "prompt": prompt,
        "selected_model": selected_model,
        "route": route,
        "confidence": round(confidence, 4),
        "threshold": round(decision_threshold, 4),
        "reason": reason,
        "features": features_dict,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Predict router decision for a given prompt.")
    parser.add_argument("--prompt", type=str, required=True, help="Input prompt text")
    parser.add_argument(
        "--threshold", type=float, default=None, help="Optional decision threshold override"
    )
    args = parser.parse_args()

    result = predict_route(args.prompt, args.threshold)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

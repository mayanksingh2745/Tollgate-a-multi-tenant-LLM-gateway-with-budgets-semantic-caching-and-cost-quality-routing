"""Model artifact loading, validation, and metadata management."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from gateway.src.router.features import FEATURE_SCHEMA_VERSION

logger = logging.getLogger("tollgate.router.artifact")


@dataclass
class ArtifactMetadata:
    """Validated metadata for a router model artifact."""

    model_version: str
    feature_schema_version: int
    training_timestamp: str
    dataset_version: str
    cheap_model: str
    strong_model: str
    threshold: float
    training_config: Dict[str, Any]
    evaluation_metrics: Dict[str, Any]
    calibration: Dict[str, Any]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArtifactMetadata":
        return cls(
            model_version=str(data.get("model_version", "")),
            feature_schema_version=int(data.get("feature_schema_version", 0)),
            training_timestamp=str(data.get("training_timestamp", "")),
            dataset_version=str(data.get("dataset_version", "")),
            cheap_model=str(data.get("cheap_model", "")),
            strong_model=str(data.get("strong_model", "")),
            threshold=float(data.get("threshold", 0.5)),
            training_config=data.get("training_config", {}),
            evaluation_metrics=data.get("evaluation_metrics", {}),
            calibration=data.get("calibration", {}),
        )


class ArtifactValidationError(Exception):
    """Raised when a router artifact fails validation."""

    pass


class RouterArtifact:
    """
    Manages loading and validation of trained router model artifacts.

    Validates:
    - Artifact existence
    - Metadata schema
    - Feature schema version compatibility
    - Model version compatibility (if configured)
    """

    def __init__(self, artifact_path: Optional[str] = None):
        self._artifact_path = artifact_path
        self._model = None
        self._metadata: Optional[ArtifactMetadata] = None
        self._loaded = False

    @property
    def metadata(self) -> Optional[ArtifactMetadata]:
        return self._metadata

    @property
    def model(self):
        return self._model

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self, expected_version: Optional[str] = None) -> None:
        """
        Load and validate the model artifact from disk.

        Args:
            expected_version: If set, validate that the artifact's model_version matches.

        Raises:
            ArtifactValidationError: If the artifact is invalid or incompatible.
        """
        if not self._artifact_path:
            raise ArtifactValidationError("No artifact path configured")

        artifact_dir = Path(self._artifact_path)
        model_path = artifact_dir / "model.joblib"
        metadata_path = artifact_dir / "metadata.json"

        if not artifact_dir.exists():
            raise ArtifactValidationError(f"Artifact directory not found: {artifact_dir}")
        if not model_path.exists():
            raise ArtifactValidationError(f"Model file not found: {model_path}")
        if not metadata_path.exists():
            raise ArtifactValidationError(f"Metadata file not found: {metadata_path}")

        # Load metadata
        try:
            with open(metadata_path) as f:
                raw_metadata = json.load(f)
            self._metadata = ArtifactMetadata.from_dict(raw_metadata)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise ArtifactValidationError(f"Malformed metadata: {e}") from e

        # Validate feature schema version
        if self._metadata.feature_schema_version != FEATURE_SCHEMA_VERSION:
            raise ArtifactValidationError(
                f"Feature schema mismatch: artifact has version "
                f"{self._metadata.feature_schema_version}, "
                f"gateway expects version {FEATURE_SCHEMA_VERSION}"
            )

        # Validate model version if expected
        if expected_version and self._metadata.model_version != expected_version:
            raise ArtifactValidationError(
                f"Model version mismatch: artifact has {self._metadata.model_version}, "
                f"expected {expected_version}"
            )

        # Load model (joblib)
        try:
            import joblib

            self._model = joblib.load(model_path)
        except Exception as e:
            raise ArtifactValidationError(f"Failed to load model artifact: {e}") from e

        self._loaded = True
        logger.info(
            f"Router artifact loaded: version={self._metadata.model_version} "
            f"features_v={self._metadata.feature_schema_version} "
            f"threshold={self._metadata.threshold}"
        )

"""Versioned evaluation artifacts with content and compatibility metadata."""

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from pydantic import Field, ValidationInfo, model_validator
from typing_extensions import Self

from ai4algebra.contracts import Digest, Record, digest_json
from ai4algebra.representation import EncoderConfig, FeatureEncoder

from ._network import NetworkParameters
from ._records import CheckpointMetadata, DDQNConfig, NonnegativeInt


class EvaluationArtifact(Record):
    kind: Literal["ai4algebra-ddqn-evaluation-v1"]
    config: DDQNConfig
    encoder_config: EncoderConfig
    encoder_digest: Digest
    metadata: CheckpointMetadata
    online: NetworkParameters
    target: NetworkParameters
    update_steps: NonnegativeInt
    artifact_digest: Digest = Field(default="", validate_default=False)

    @model_validator(mode="after")
    def _check_identity(self, info: ValidationInfo) -> Self:
        if self.encoder_digest != FeatureEncoder(self.encoder_config).encoder_digest:
            raise ValueError(
                "checkpoint encoder digest does not match its configuration"
            )
        actual = digest_json(self.model_dump(mode="json", exclude={"artifact_digest"}))
        if info.mode == "json" and "artifact_digest" not in self.model_fields_set:
            raise ValueError("missing checkpoint digest")
        if self.artifact_digest and self.artifact_digest != actual:
            raise ValueError("checkpoint digest does not match contents")
        object.__setattr__(self, "artifact_digest", actual)
        return self

    def write(self, path: Path) -> None:
        payload = self.to_json()
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

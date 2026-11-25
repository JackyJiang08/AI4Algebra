"""Causal nearest-neighbor memory of verified training-branch returns.

Returns reflect the collection policy and select for branches that passed
verification. This success-only memory is a biased sample of search experience.

Only the neighbor records are capacity-bounded. The run retains one compact
publication entry per verified branch to detect retries after FIFO eviction.
"""

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import dist
from statistics import mean
from threading import Lock
from typing import Annotated

from pydantic import Field, model_validator
from typing_extensions import Self

from ai4algebra.contracts import (
    CandidateSet,
    Certificate,
    Digest,
    Identifier,
    Problem,
    Record,
    Transition,
    Verdict,
    digest_json,
)
from ai4algebra.representation import StateFeatures

from ._records import (
    MemoryArchive,
    MemorySettings,
    NonnegativeInt,
    PositiveInt,
    TrainingTrace,
    nonnegative_int,
    training_problem,
)


class _ReturnSettings(MemorySettings):
    gamma: Annotated[float, Field(ge=0, le=1)]
    feature_version: Digest
    state_size: PositiveInt
    policy_digest: Digest
    k: PositiveInt
    max_distance: Annotated[float, Field(ge=0)]

    def validate_features(self, features: StateFeatures) -> None:
        if features.encoder_digest != self.feature_version:
            raise ValueError("state features have an incompatible encoder version")
        if len(features.values) != self.state_size:
            raise ValueError("state features have an incompatible size")


class _ReturnRecord(TrainingTrace):
    state_features: StateFeatures
    available_at: NonnegativeInt
    discounted_return: float
    proof_digest: Digest

    @model_validator(mode="after")
    def _validate_observation_and_clock(self) -> Self:
        transition = self.transition
        if (
            self.state_features.state_digest != transition.observation.state_digest
            or self.state_features.encoder_digest != transition.feature_version
            or self.state_features.environment_digest
            != transition.observation.snapshot.environment_digest
        ):
            raise ValueError("return features do not match the transition")
        if transition.collection_step > self.available_at:
            raise ValueError("return is available before its collection step")
        if transition.truncated or transition.outcome not in {
            "advanced",
            "rejected",
            "verified",
        }:
            raise ValueError("ineligible transition outcome in verified return memory")
        return self

    def is_available(self, before_step: int) -> bool:
        return (
            self.transition.collection_step < before_step
            and self.available_at < before_step
        )


class _Publication(Record):
    """One compact entry per verified branch, retained after FIFO eviction."""

    episode_id: Identifier
    branch_id: Identifier
    task_id: Identifier
    source_digest: Digest
    statement_digest: Digest
    proof_digest: Digest
    certificate_digest: Digest
    content_digest: Digest
    completion_step: NonnegativeInt
    available_at: NonnegativeInt

    @property
    def key(self) -> tuple[str, str]:
        return self.episode_id, self.branch_id

    @model_validator(mode="after")
    def _validate_clock(self) -> Self:
        if self.available_at < self.completion_step:
            raise ValueError("publication precedes branch completion")
        return self

    def validate_record(self, item: _ReturnRecord) -> None:
        transition = item.transition
        if (
            item.available_at != self.available_at
            or item.proof_digest != self.proof_digest
            or item.source_digest != self.source_digest
            or item.statement_digest != self.statement_digest
            or transition.task_id != self.task_id
            or transition.collection_step > self.completion_step
            or transition.terminated
            != (transition.collection_step == self.completion_step)
        ):
            raise ValueError(
                "return record provenance or clock differs from its branch publication"
            )


class _ReturnArchive(MemoryArchive):
    settings: _ReturnSettings
    cutoff: NonnegativeInt
    cutoff_floor: NonnegativeInt
    publications: tuple[_Publication, ...]
    records: tuple[_ReturnRecord, ...]

    @model_validator(mode="after")
    def _validate_records(self) -> Self:
        if len(self.records) > self.settings.capacity:
            raise ValueError("return memory artifact exceeds capacity")
        if self.cutoff < self.cutoff_floor:
            raise ValueError("evaluation cutoff precedes retained return history")
        publications: dict[tuple[str, str], tuple[int, _Publication]] = {}
        previous_available_at = -1
        for index, publication in enumerate(self.publications):
            if (
                publication.key in publications
                or not previous_available_at <= publication.available_at < self.cutoff
            ):
                raise ValueError("invalid branch publication ledger")
            publications[publication.key] = index, publication
            previous_available_at = publication.available_at
        previous_position = (-1, -1)
        for item in self.records:
            transition = item.transition
            self.settings.validate_features(item.state_features)
            if (
                item.transition.candidate_set.policy_digest
                != self.settings.policy_digest
            ):
                raise ValueError("return record has an incompatible candidate policy")
            if not item.is_available(self.cutoff):
                raise ValueError(
                    "return record is unavailable at the evaluation cutoff"
                )
            ledger_entry = publications.get(
                (transition.episode_id, transition.branch_id)
            )
            if ledger_entry is None:
                raise ValueError("return record has no branch publication")
            index, publication = ledger_entry
            publication.validate_record(item)
            position = (index, transition.collection_step)
            if position <= previous_position:
                raise ValueError("return records are duplicated or out of FIFO order")
            previous_position = position
        return self


def _query(
    records: Iterable[_ReturnRecord],
    settings: _ReturnSettings,
    state: StateFeatures,
    candidates: CandidateSet,
    before_step: int,
    exclude_episode: str,
) -> dict[str, float]:
    nonnegative_int(before_step, "before_step")
    state = StateFeatures.from_json(state.to_json())
    candidates = CandidateSet.from_json(candidates.to_json())
    settings.validate_features(state)
    if candidates.state_digest != state.state_digest:
        raise ValueError("query candidates do not belong to the query state")
    if candidates.policy_digest != settings.policy_digest:
        raise ValueError("query candidates have an incompatible policy")

    eligible = {
        candidate.candidate_id
        for candidate, allowed in zip(
            candidates.candidates, candidates.eligible, strict=True
        )
        if allowed
    }
    neighbors: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for item in records:
        transition = item.transition
        candidate_id = transition.chosen_candidate_id
        if (
            candidate_id not in eligible
            or transition.episode_id == exclude_episode
            or transition.split != "train"
            or transition.feature_version != settings.feature_version
            or transition.candidate_set.policy_digest != settings.policy_digest
            or item.state_features.environment_digest != state.environment_digest
            or not item.is_available(before_step)
        ):
            continue
        distance = dist(state.values, item.state_features.values)
        if distance <= settings.max_distance:
            neighbors[candidate_id].append((distance, item.discounted_return))

    scores = {}
    for candidate_id, matches in neighbors.items():
        # Stable sorting preserves FIFO order among equal distances.
        matches.sort(key=lambda pair: pair[0])
        scores[candidate_id] = mean(value for _, value in matches[: settings.k])
    return scores


@dataclass(frozen=True, slots=True)
class FrozenReturnMemory:
    """Read-only training memory with a single held-out evaluation cutoff."""

    _archive: _ReturnArchive

    def __len__(self) -> int:
        return len(self._archive.records)

    @property
    def cutoff(self) -> int:
        return self._archive.cutoff

    @property
    def artifact_digest(self) -> str:
        return self._archive.artifact_digest

    @property
    def cutoff_floor(self) -> int:
        return self._archive.cutoff_floor

    def query(
        self,
        state: StateFeatures,
        candidates: CandidateSet,
        *,
        exclude_episode: str,
        before_step: int | None = None,
    ) -> dict[str, float]:
        if before_step is not None:
            nonnegative_int(before_step, "before_step")
            if before_step != self.cutoff:
                raise ValueError("evaluation must use the frozen return memory cutoff")
        return _query(
            self._archive.records,
            self._archive.settings,
            state,
            candidates,
            self.cutoff,
            exclude_episode,
        )

    def to_json(self) -> str:
        return self._archive.to_json()

    @classmethod
    def from_json(
        cls,
        data: str | bytes,
        *,
        run_id: str,
        task_sources: Mapping[str, Problem],
        feature_version: str,
        state_size: int,
        policy_digest: str,
        cutoff: int,
        expected_artifact_digest: str | None = None,
    ) -> Self:
        nonnegative_int(cutoff, "cutoff")
        archive = _ReturnArchive.from_json(data)
        if (
            expected_artifact_digest is not None
            and archive.artifact_digest != expected_artifact_digest
        ):
            raise ValueError("return memory differs from the expected artifact digest")
        settings = archive.settings
        if (
            settings.run_id,
            settings.feature_version,
            settings.state_size,
            settings.policy_digest,
            archive.cutoff,
        ) != (run_id, feature_version, state_size, policy_digest, cutoff):
            raise ValueError(
                "return memory identity or evaluation cutoff does not match"
            )
        for publication in archive.publications:
            problem = training_problem(publication.task_id, task_sources)
            if (
                publication.source_digest != problem.source.content_digest
                or publication.statement_digest != problem.statement_digest
            ):
                raise ValueError(
                    "memory provenance differs from the trusted task catalog"
                )
        return cls(archive)


class ReturnMemory:
    def __init__(
        self,
        capacity: int,
        *,
        gamma: float,
        feature_version: str,
        state_size: int,
        policy_digest: str,
        task_sources: Mapping[str, Problem],
        run_id: str,
        k: int = 3,
        max_distance: float = 1.0,
    ) -> None:
        self._settings = _ReturnSettings(
            capacity=capacity,
            run_id=run_id,
            gamma=gamma,
            feature_version=feature_version,
            state_size=state_size,
            policy_digest=policy_digest,
            k=k,
            max_distance=max_distance,
        )
        self._task_sources = dict(task_sources)
        self._records: deque[_ReturnRecord] = deque(maxlen=capacity)
        self._publications: dict[tuple[str, str], _Publication] = {}
        self._cutoff_floor = 0
        self._latest_publication = -1
        self._lock = Lock()

    def __len__(self) -> int:
        return len(self._records)

    def publish(
        self,
        episode: Sequence[Transition],
        verdict: Verdict,
        available_at: int,
        *,
        state_features: Sequence[StateFeatures],
        certificate: Certificate,
    ) -> int:
        """Publish a verified branch once, including after its records are evicted."""
        nonnegative_int(available_at, "available_at")
        traces = tuple(
            TrainingTrace.capture(transition, self._task_sources)
            for transition in episode
        )
        verdict = Verdict.from_json(verdict.to_json())
        if not traces or verdict.status != "accepted":
            return 0
        branch = tuple(trace.transition for trace in traces)
        final = branch[-1]
        if not final.terminated or any(
            step.truncated or step.outcome not in {"advanced", "rejected", "verified"}
            for step in branch
        ):
            return 0
        if len(state_features) != len(branch):
            raise ValueError("verified branch requires features for every transition")
        if available_at < final.collection_step:
            raise ValueError("publication precedes branch completion")
        certificate = Certificate.from_json(certificate.to_json())
        self._validate_branch(branch, certificate)
        certificate_digest = digest_json(certificate.model_dump(mode="json"))
        if verdict.certificate_digest != certificate_digest:
            raise ValueError(
                "accepted verdict does not identify the supplied certificate"
            )
        value = 0.0
        staged = []
        for trace, features in reversed(
            tuple(zip(traces, state_features, strict=True))
        ):
            features = StateFeatures.from_json(features.to_json())
            self._settings.validate_features(features)
            value = trace.transition.reward + self._settings.gamma * value
            staged.append(
                _ReturnRecord(
                    transition=trace.transition,
                    source_digest=trace.source_digest,
                    statement_digest=trace.statement_digest,
                    state_features=features,
                    available_at=available_at,
                    discounted_return=value,
                    proof_digest=certificate.proof_digest,
                )
            )
        staged.reverse()
        content_digest = digest_json(
            (
                verdict.model_dump(mode="json"),
                tuple(
                    item.model_dump(mode="json", exclude={"available_at"})
                    for item in staged
                ),
            )
        )
        key = final.episode_id, final.branch_id
        with self._lock:
            original = self._publications.get(key)
            if original is not None:
                if original.content_digest != content_digest:
                    raise ValueError(
                        "conflicting publication for a previously verified branch"
                    )
                return 0
            publication = _Publication(
                episode_id=final.episode_id,
                branch_id=final.branch_id,
                task_id=final.task_id,
                source_digest=traces[-1].source_digest,
                statement_digest=traces[-1].statement_digest,
                proof_digest=certificate.proof_digest,
                certificate_digest=certificate_digest,
                content_digest=content_digest,
                completion_step=final.collection_step,
                available_at=available_at,
            )
            if available_at < self._latest_publication:
                raise ValueError("publication clock must be monotone")
            if (
                self._records
                and len(self._records) + len(staged) > self._settings.capacity
                and self._records[0].available_at < available_at
            ):
                self._cutoff_floor = available_at + 1
            self._records.extend(staged)
            self._publications[key] = publication
            self._latest_publication = available_at
            return len(staged)

    def _validate_branch(
        self, branch: Sequence[Transition], certificate: Certificate
    ) -> None:
        first = branch[0]
        identity = (first.task_id, first.episode_id, first.branch_id)
        prefix: list[str] = []
        for step in branch:
            if (step.task_id, step.episode_id, step.branch_id) != identity:
                raise ValueError("publication mixes distinct proof branches")
            if (
                step.feature_version != self._settings.feature_version
                or step.candidate_set.policy_digest != self._settings.policy_digest
            ):
                raise ValueError(
                    "branch feature version or candidate policy is incompatible"
                )
            # The Lean bridge hashes ordered candidate IDs, starting from an empty prefix.
            if step.observation.snapshot.prefix_digest != digest_json(prefix):
                raise ValueError("branch observation has an unexpected proof prefix")
            if step.outcome != "rejected":
                prefix.append(step.chosen_candidate_id)
            if step.next_observation.snapshot.prefix_digest != digest_json(prefix):
                raise ValueError("branch successor has an unexpected proof prefix")
        for parent, child in zip(branch, branch[1:]):
            if (
                parent.terminated
                or parent.collection_step >= child.collection_step
                or parent.next_observation != child.observation
                or parent.next_candidate_set != child.candidate_set
            ):
                raise ValueError(
                    "publication requires a continuous ordered proof branch"
                )

        problem = training_problem(first.task_id, self._task_sources)
        certificate_steps = tuple(step.candidate_id for step in certificate.steps)
        if (
            certificate.task_id != first.task_id
            or certificate.statement_digest != problem.statement_digest
            or certificate.source_digest != problem.source.content_digest
            or certificate.imports != problem.imports
            or certificate.environment_digest
            != first.observation.snapshot.environment_digest
            or certificate.policy_digest != self._settings.policy_digest
            or certificate_steps != tuple(prefix)
        ):
            raise ValueError("certificate does not identify the verified proof branch")

    def query(
        self,
        state: StateFeatures,
        candidates: CandidateSet,
        *,
        before_step: int,
        exclude_episode: str,
    ) -> dict[str, float]:
        nonnegative_int(before_step, "before_step")
        with self._lock:
            if before_step < self._cutoff_floor:
                raise ValueError("query cutoff precedes retained return history")
            records = tuple(self._records)
        return _query(
            records, self._settings, state, candidates, before_step, exclude_episode
        )

    def freeze(self, cutoff: int) -> FrozenReturnMemory:
        nonnegative_int(cutoff, "cutoff")
        with self._lock:
            cutoff_floor = self._cutoff_floor
            if cutoff < cutoff_floor:
                raise ValueError("evaluation cutoff precedes retained return history")
            records = tuple(item for item in self._records if item.is_available(cutoff))
            publications = tuple(
                item
                for item in self._publications.values()
                if item.available_at < cutoff
            )
        return FrozenReturnMemory(
            _ReturnArchive(
                settings=self._settings,
                cutoff=cutoff,
                cutoff_floor=cutoff_floor,
                publications=publications,
                records=records,
            )
        )

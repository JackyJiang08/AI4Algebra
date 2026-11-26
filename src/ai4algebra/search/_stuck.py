"""Readable failure evidence projected from recorded search state."""

from ai4algebra.config import Limits
from ai4algebra.contracts import Observation, Problem

from ._records import ProofNode, SearchReport


def attempted_steps(report: SearchReport) -> dict[str, object]:
    selected = [
        {
            "parent_node": attempt.node_id,
            "candidate": attempt.candidate.model_dump(mode="json"),
            "outcome": attempt.outcome,
            "child_node": attempt.child_id,
            "step_status": attempt.result.status,
            "reused_probe": attempt.reused_probe,
            "diagnostics": attempt.result.diagnostics,
        }
        for attempt in report.attempts
    ]
    probed = []
    for generation in report.generations:
        candidates = {
            candidate.candidate_id: candidate
            for candidate in generation.candidate_set.candidates
        }
        for probe in generation.probes:
            candidate = candidates.get(probe.candidate_id)
            if candidate is None or probe.reused:
                continue
            if probe.status in {"not_probed", "already_attempted"}:
                continue
            if probe.result is None and probe.status not in {
                "timeout",
                "infrastructure_error",
            }:
                continue
            probed.append(
                {
                    "parent_node": generation.node_id,
                    "candidate": candidate.model_dump(mode="json"),
                    "outcome": probe.status,
                    "diagnostics": None
                    if probe.result is None
                    else probe.result.diagnostics,
                }
            )
    return {"selected_actions": selected, "applicability_probes": probed}


def _state(
    observation: Observation, node: ProofNode | None, nodes: dict[str, ProofNode]
) -> dict[str, object]:
    tactics = []
    ancestor = node
    while ancestor is not None and ancestor.incoming_candidate is not None:
        tactics.append(ancestor.incoming_candidate.model_dump(mode="json"))
        parent = (
            nodes.get(ancestor.parent_id) if ancestor.parent_id is not None else None
        )
        ancestor = (
            parent if parent is not None and parent.depth < ancestor.depth else None
        )
    return {
        "node_id": None if node is None else node.node_id,
        "depth": None if node is None else node.depth,
        "state_digest": observation.state_digest,
        "prefix_digest": observation.snapshot.prefix_digest,
        "path_tactics": list(reversed(tactics)) if ancestor is not None else None,
        "unresolved_goals": [
            {
                "goal_id": goal.goal_id,
                "target": goal.target,
                "hypotheses": [
                    hypothesis.model_dump(
                        mode="json",
                        exclude={"expression", "schema_version"},
                        exclude_none=True,
                    )
                    for hypothesis in goal.hypotheses
                ],
            }
            for goal in observation.goals
        ],
    }


def stuck_report(
    problem: Problem,
    report: SearchReport | None,
    *,
    reason: str = "execution_failed",
    diagnostics: tuple[str, ...] = (),
    limits: Limits | None = None,
) -> dict[str, object]:
    """Describe a failure using only chronological observations and attempted work."""
    evidence: dict[str, object] = {
        "schema_version": 1,
        "task_id": problem.task_id,
        "lean_name": problem.lean_name,
        "statement_digest": problem.statement_digest,
        "episode_id": None,
        "mode": None,
        "policy_name": None,
        "status": "infrastructure_error",
        "reason": reason,
        "diagnostics": diagnostics,
        "budget": {
            "limits": None if limits is None else limits.model_dump(mode="json"),
            "reasons": None,
            "work": None,
        },
        "last_observation": None,
        "last_visited": None,
        "frontier": None,
        "cutoffs": None,
        "attempted_candidates": None,
    }
    if report is None:
        return evidence

    nodes = {node.node_id: node for node in report.nodes}

    def node_state(node_id: str | None) -> dict[str, object] | None:
        node = nodes.get(node_id) if node_id is not None else None
        return None if node is None else _state(node.observation, node, nodes)

    last = report.last_observation
    last_node = next(
        (node for node in reversed(report.nodes) if node.observation == last), None
    )
    evidence.update(
        episode_id=report.episode_id,
        mode=report.mode,
        policy_name=report.policy_name,
        status=report.status,
        reason=report.reason,
        diagnostics=report.diagnostics,
        budget={
            "limits": report.limits.model_dump(mode="json"),
            "reasons": report.budget_reasons,
            "work": report.work.model_dump(mode="json"),
            "step_calls": report.work.step_calls,
            "remaining_step_calls": max(
                0, report.limits.max_steps - report.work.step_calls
            ),
        },
        last_observation=None if last is None else _state(last, last_node, nodes),
        last_visited=node_state(report.last_visited_node_id),
        frontier=None
        if report.frontier_node_ids is None
        else [node_state(node_id) for node_id in report.frontier_node_ids],
        cutoffs=None
        if report.frontier_node_ids is None
        else [
            {"reason": cutoff.reason, "state": node_state(cutoff.node_id)}
            for cutoff in report.cutoffs
        ],
        attempted_candidates=attempted_steps(report),
    )
    return evidence

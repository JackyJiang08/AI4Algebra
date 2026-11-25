import json

import numpy as np
import pytest

from retrieval_ddqn.contracts import Transition
from retrieval_ddqn.learner import MLP, DoubleDQNLearner, double_dqn_targets


def make_learner(seed: int = 11) -> DoubleDQNLearner:
    return DoubleDQNLearner(
        2, 2, 2, seed, gamma=0.5, learning_rate=0.03, target_update_interval=2
    )


def transition(terminated: bool = False, truncated: bool = False) -> Transition:
    return Transition(
        (1.0, 0.0), 1, 3.0, (0.0, 1.0), terminated, truncated, 0, "train-0"
    )


def test_double_dqn_uses_online_choice_and_masks_termination() -> None:
    online = [[-1, 4], [2, 0], [0, -1]]
    target = [[10, -2], [-4, 9], [5, 6]]
    values = double_dqn_targets([2, -1, 3], [False, False, True], online, target, 0.25)
    np.testing.assert_array_equal(values, [1.5, -2, 3])


@pytest.mark.parametrize(
    "terminated,truncated,expected",
    [
        (False, True, 4.0),
        (True, False, 3.0),
        (True, True, 3.0),
    ],
)
def test_update_uses_final_observation_for_bootstrap(
    terminated: bool, truncated: bool, expected: float
) -> None:
    learner = make_learner()
    identity = [[1.0, 0.0], [0.0, 1.0]]
    shared = {"w1": identity, "b1": [0.0, 0.0], "b2": [0.0, 0.0]}
    learner.online.load_state_dict({**shared, "w2": identity})
    learner.target.load_state_dict({**shared, "w2": [[6.0, 1.0], [9.0, 2.0]]})
    metrics = learner.update([transition(terminated, truncated)])
    assert metrics["target_mean"] == expected
    assert metrics["loss"] == expected**2


def test_selected_action_mse_gradient_matches_central_differences() -> None:
    network = MLP(2, 3, 2, seed=7)
    initial = {
        "w1": [[1.0, -0.5], [0.25, 1.0]],
        "b1": [0.1, -0.2],
        "w2": [[0.3, 0.2, 0.1], [-0.4, -0.3, 0.5]],
        "b2": [0.0, 0.1, 0.2],
    }
    network.load_state_dict(initial)
    states = [[1.0, 0.1], [-0.5, 1.0], [1.0, 1.0]]
    actions = [0, 2, 0]
    targets = np.array([1.0, -0.5, 0.75])

    def mse() -> np.float64:
        chosen = network.predict(states)[np.arange(len(actions)), actions]
        value: np.float64 = np.mean((chosen - targets) ** 2)
        return value

    expected_loss = mse()
    epsilon = 1e-6
    finite_differences = {}
    for name, values in initial.items():
        parameter = np.array(values)
        gradient = np.zeros_like(parameter)
        for index in np.ndindex(parameter.shape):
            delta = np.zeros_like(parameter)
            delta[index] = epsilon
            network.load_state_dict({**initial, name: parameter + delta})
            upper = mse()
            network.load_state_dict({**initial, name: parameter - delta})
            gradient[index] = (upper - mse()) / (2 * epsilon)
        finite_differences[name] = gradient

    network.load_state_dict(initial)
    rate = 0.01
    assert network.train(states, actions, targets, rate) == pytest.approx(expected_loss)
    for name, updated in network.state_dict().items():
        actual_gradient = (np.asarray(initial[name]) - updated) / rate
        np.testing.assert_allclose(actual_gradient, finite_differences[name], atol=1e-8)


def test_hard_sync_and_json_round_trip_between_syncs() -> None:
    learner = make_learner()
    original = learner.online.state_dict()
    assert original == learner.target.state_dict()
    batch = [transition()]
    assert learner.update(batch)["update_steps"] == 1
    assert learner.target.state_dict() == original
    assert learner.online.state_dict() != original

    restored = make_learner(seed=1234)
    restored.load_state_dict(json.loads(json.dumps(learner.state_dict())))
    assert restored.state_dict() == learner.state_dict()
    assert restored.update(batch) == learner.update(batch)
    assert restored.state_dict() == learner.state_dict()
    assert learner.update_steps == 2
    assert learner.online.state_dict() == learner.target.state_dict()

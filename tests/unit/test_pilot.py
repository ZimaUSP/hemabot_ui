from hemabot_ui.teleop.pilot import AcquireOutcome, PilotArbiter


def test_first_client_becomes_pilot() -> None:
    arbiter = PilotArbiter()
    assert arbiter.acquire("a") is AcquireOutcome.GRANTED
    assert arbiter.pilot_id == "a"
    assert arbiter.is_pilot("a")


def test_acquire_is_idempotent_for_the_pilot() -> None:
    arbiter = PilotArbiter()
    arbiter.acquire("a")
    assert arbiter.acquire("a") is AcquireOutcome.ALREADY_PILOT
    assert arbiter.acquire("a", force=True) is AcquireOutcome.ALREADY_PILOT


def test_second_client_is_refused_without_force() -> None:
    arbiter = PilotArbiter()
    arbiter.acquire("a")
    outcome = arbiter.acquire("b")
    assert outcome is AcquireOutcome.BUSY
    assert not outcome.is_pilot
    assert arbiter.pilot_id == "a"


def test_force_takes_over() -> None:
    arbiter = PilotArbiter()
    arbiter.acquire("a")
    assert arbiter.acquire("b", force=True) is AcquireOutcome.TAKEN_OVER
    assert arbiter.pilot_id == "b"
    assert not arbiter.is_pilot("a")


def test_only_the_pilot_can_release() -> None:
    arbiter = PilotArbiter()
    arbiter.acquire("a")
    assert arbiter.release("b") is False
    assert arbiter.pilot_id == "a"
    assert arbiter.release("a") is True
    assert arbiter.pilot_id is None


def test_control_is_free_after_release() -> None:
    arbiter = PilotArbiter()
    arbiter.acquire("a")
    arbiter.release("a")
    assert arbiter.acquire("b") is AcquireOutcome.GRANTED

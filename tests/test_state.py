import pytest

from videodownloader.core.state import AppStateMachine
from videodownloader.models import JobState


def test_state_machine_accepts_download_lifecycle() -> None:
    state = AppStateMachine()
    for target in (
        JobState.ANALYZING,
        JobState.READY,
        JobState.DOWNLOADING,
        JobState.POST_PROCESSING,
        JobState.COMPLETED,
    ):
        state.transition(target)

    assert state.state is JobState.COMPLETED


def test_state_machine_rejects_download_before_analysis() -> None:
    state = AppStateMachine()

    with pytest.raises(ValueError, match="Invalid state transition"):
        state.transition(JobState.DOWNLOADING)


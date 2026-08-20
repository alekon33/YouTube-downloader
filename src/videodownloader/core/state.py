"""Explicit state machine for user-visible application operations."""

from __future__ import annotations

from videodownloader.models import JobState

_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.IDLE: frozenset({JobState.ANALYZING}),
    JobState.ANALYZING: frozenset({JobState.IDLE, JobState.READY, JobState.FAILED}),
    JobState.READY: frozenset({JobState.ANALYZING, JobState.DOWNLOADING}),
    JobState.DOWNLOADING: frozenset(
        {
            JobState.POST_PROCESSING,
            JobState.COMPLETED,
            JobState.CANCELLED,
            JobState.FAILED,
        }
    ),
    JobState.POST_PROCESSING: frozenset(
        {JobState.COMPLETED, JobState.CANCELLED, JobState.FAILED}
    ),
    JobState.COMPLETED: frozenset({JobState.ANALYZING, JobState.DOWNLOADING, JobState.READY}),
    JobState.CANCELLED: frozenset({JobState.ANALYZING, JobState.DOWNLOADING, JobState.READY}),
    JobState.FAILED: frozenset({JobState.IDLE, JobState.READY, JobState.ANALYZING}),
}


class AppStateMachine:
    """Prevent contradictory controls and illegal operation overlap."""

    def __init__(self) -> None:
        self._state = JobState.IDLE

    @property
    def state(self) -> JobState:
        return self._state

    def transition(self, target: JobState) -> None:
        if target is self._state:
            return
        if target not in _TRANSITIONS[self._state]:
            raise ValueError(f"Invalid state transition: {self._state.value} -> {target.value}")
        self._state = target

    def reset(self, ready: bool = False) -> None:
        """Recover after an error while preserving analyzed metadata when possible."""

        target = JobState.READY if ready else JobState.IDLE
        if self._state is JobState.FAILED:
            self.transition(target)
        else:
            self._state = target


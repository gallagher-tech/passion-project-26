"""Unit tests for the hardware-free state machine.

Uses a fake clock and a fake timer scheduler -- no real hardware, no OSC
server, and no actual sleeping/waiting.
"""
import pytest

from wok_detection.state_machine import (
    WOK_ABSENT,
    WOK_PRESENT,
    Debouncer,
    WokStateMachine,
    raw_to_logical,
)


class FakeClock:
    def __init__(self, start=0.0):
        self.now = start

    def advance(self, seconds):
        self.now += seconds

    def __call__(self):
        return self.now


class FakeScheduler:
    """Records scheduled timers so tests can fire them manually instead of
    waiting on a real clock."""

    def __init__(self):
        self.scheduled = []  # list of (delay_seconds, callback)
        self.cancelled = []

    def schedule(self, delay_seconds, callback):
        handle = object()
        self.scheduled.append((handle, delay_seconds, callback))
        return handle

    def cancel(self, handle):
        self.cancelled.append(handle)

    def fire_all(self):
        for _handle, _delay, callback in self.scheduled:
            callback()


class FakeOscSender:
    def __init__(self):
        self.sent = []

    def __call__(self, value):
        self.sent.append(value)


def make_machine(clock, scheduler, osc, debounce_seconds=0.05, lockout_seconds=60):
    return WokStateMachine(
        debounce_seconds=debounce_seconds,
        lockout_seconds=lockout_seconds,
        send_osc=osc,
        schedule_timer=scheduler.schedule,
        cancel_timer=scheduler.cancel,
        clock=clock,
        initial_logical=WOK_PRESENT,
    )


# --- polarity inversion -------------------------------------------------


def test_raw_high_is_wok_present():
    assert raw_to_logical(1) == WOK_PRESENT
    assert WOK_PRESENT == 0


def test_raw_low_is_wok_absent():
    assert raw_to_logical(0) == WOK_ABSENT
    assert WOK_ABSENT == 1


# --- debounce / jitter rejection (on Debouncer directly) ---------------


def test_debouncer_rejects_short_jitter():
    clock = FakeClock()
    debouncer = Debouncer(stable_duration_seconds=0.05, initial_value=0, clock=clock)

    assert debouncer.update(1, now=clock()) is None  # candidate starts
    clock.advance(0.02)
    assert debouncer.update(0, now=clock()) is None  # flips back before stable
    clock.advance(0.02)
    assert debouncer.update(1, now=clock()) is None  # brief blip, resets candidate timer
    clock.advance(0.02)
    # only 0.02s since the last flip to 1 -- not yet stable
    assert debouncer.update(1, now=clock()) is None


def test_debouncer_accepts_after_stable_duration():
    clock = FakeClock()
    debouncer = Debouncer(stable_duration_seconds=0.05, initial_value=0, clock=clock)

    debouncer.update(1, now=clock())
    clock.advance(0.05)
    assert debouncer.update(1, now=clock()) == 1


# --- edge detection ------------------------------------------------------


def test_transition_to_absent_sends_one_shot_1_and_enters_busy():
    clock, scheduler, osc = FakeClock(), FakeScheduler(), FakeOscSender()
    machine = make_machine(clock, scheduler, osc)

    machine.feed_logical(WOK_ABSENT, now=clock())
    clock.advance(0.05)
    machine.feed_logical(WOK_ABSENT, now=clock())

    assert osc.sent == [1]
    assert machine.busy is True


def test_transition_to_present_sends_one_shot_0():
    clock, scheduler, osc = FakeClock(), FakeScheduler(), FakeOscSender()
    machine = make_machine(clock, scheduler, osc)

    # move away from initial WOK_PRESENT first, then back to it
    machine.feed_logical(WOK_ABSENT, now=clock())
    clock.advance(0.05)
    machine.feed_logical(WOK_ABSENT, now=clock())
    osc.sent.clear()
    scheduler.fire_all()  # clear busy so the WOK_PRESENT edge isn't suppressed
    scheduler.scheduled.clear()

    machine.feed_logical(WOK_PRESENT, now=clock())
    clock.advance(0.05)
    machine.feed_logical(WOK_PRESENT, now=clock())

    assert osc.sent == [0]


# --- busy / lockout suppression ------------------------------------------


def test_transitions_suppressed_while_busy():
    clock, scheduler, osc = FakeClock(), FakeScheduler(), FakeOscSender()
    machine = make_machine(clock, scheduler, osc)

    machine.feed_logical(WOK_ABSENT, now=clock())
    clock.advance(0.05)
    machine.feed_logical(WOK_ABSENT, now=clock())
    assert osc.sent == [1]
    assert machine.busy is True

    # Wok placed back, then removed again, all while still busy -- both
    # transitions must be fully ignored, no OSC traffic at all.
    clock.advance(0.05)
    machine.feed_logical(WOK_PRESENT, now=clock())
    clock.advance(0.05)
    machine.feed_logical(WOK_PRESENT, now=clock())
    clock.advance(0.05)
    machine.feed_logical(WOK_ABSENT, now=clock())
    clock.advance(0.05)
    machine.feed_logical(WOK_ABSENT, now=clock())

    assert osc.sent == [1]
    assert machine.busy is True


# --- timer-based unlock ---------------------------------------------------


def test_unlock_after_lockout_resumes_normal_edge_behavior():
    clock, scheduler, osc = FakeClock(), FakeScheduler(), FakeOscSender()
    machine = make_machine(clock, scheduler, osc, lockout_seconds=60)

    machine.feed_logical(WOK_ABSENT, now=clock())
    clock.advance(0.05)
    machine.feed_logical(WOK_ABSENT, now=clock())
    assert machine.busy is True
    assert len(scheduler.scheduled) == 1
    assert scheduler.scheduled[0][1] == 60

    scheduler.fire_all()  # simulate the lockout timer elapsing
    assert machine.busy is False

    # fresh edge after unlock is handled normally again
    machine.feed_logical(WOK_PRESENT, now=clock())
    clock.advance(0.05)
    machine.feed_logical(WOK_PRESENT, now=clock())
    assert osc.sent == [1, 0]


def test_shutdown_cancels_pending_lockout_timer():
    clock, scheduler, osc = FakeClock(), FakeScheduler(), FakeOscSender()
    machine = make_machine(clock, scheduler, osc)

    machine.feed_logical(WOK_ABSENT, now=clock())
    clock.advance(0.05)
    machine.feed_logical(WOK_ABSENT, now=clock())
    assert machine.busy is True

    machine.shutdown()

    assert len(scheduler.cancelled) == 1
    assert scheduler.cancelled[0] == scheduler.scheduled[0][0]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

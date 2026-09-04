"""Unit tests for the hardware-free state machine.

Debounce and lockout are both timer-based (see state_machine.py), so tests
drive a fake scheduler directly -- firing or cancelling timers -- instead of
advancing a fake clock. No real hardware, no OSC server, no actual waiting.
"""
import pytest

from wok_detection.state_machine import (
    WOK_ABSENT,
    WOK_PRESENT,
    Debouncer,
    WokStateMachine,
    raw_to_logical,
)


class FakeScheduler:
    """Records scheduled timers so tests can fire or cancel them manually.

    More than one timer can be pending at once now (a debounce timer and an
    in-flight lockout timer, say) -- `fire_all` fires every pending timer,
    while `fire_latest` fires only the most recently scheduled one, leaving
    earlier pending timers (e.g. a lockout already in flight) untouched.
    """

    def __init__(self):
        self.scheduled = []  # list of (handle, delay_seconds, callback), pending only
        self.cancelled = []

    def schedule(self, delay_seconds, callback):
        handle = object()
        self.scheduled.append((handle, delay_seconds, callback))
        return handle

    def cancel(self, handle):
        self.cancelled.append(handle)
        self.scheduled = [entry for entry in self.scheduled if entry[0] != handle]

    def fire_all(self):
        pending = list(self.scheduled)
        self.scheduled.clear()
        for _handle, _delay, callback in pending:
            callback()

    def fire_latest(self):
        _handle, _delay, callback = self.scheduled.pop()
        callback()


class FakeOscSender:
    def __init__(self):
        self.sent = []

    def __call__(self, value):
        self.sent.append(value)


def make_debouncer(scheduler, on_stable_change, debounce_seconds=0.05, initial_value=WOK_PRESENT):
    return Debouncer(debounce_seconds, initial_value, on_stable_change, scheduler.schedule, scheduler.cancel)


def make_machine(scheduler, osc, debounce_seconds=0.05, lockout_seconds=60):
    return WokStateMachine(
        debounce_seconds=debounce_seconds,
        lockout_seconds=lockout_seconds,
        send_osc=osc,
        schedule_timer=scheduler.schedule,
        cancel_timer=scheduler.cancel,
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


def test_debouncer_ignores_repeats_of_the_current_stable_value():
    scheduler = FakeScheduler()
    changes = []
    debouncer = make_debouncer(scheduler, changes.append)

    debouncer.update(WOK_PRESENT)
    debouncer.update(WOK_PRESENT)

    assert scheduler.scheduled == []
    assert changes == []


def test_debouncer_rejects_short_jitter():
    """Real Firmata reports edges, not continuous samples -- a candidate
    that flips back to the current stable value before its debounce timer
    fires must be cancelled and never commit."""
    scheduler = FakeScheduler()
    changes = []
    debouncer = make_debouncer(scheduler, changes.append)

    debouncer.update(WOK_ABSENT)  # candidate timer scheduled
    debouncer.update(WOK_PRESENT)  # flips back to stable before timer fires -- cancelled
    debouncer.update(WOK_ABSENT)  # brief blip again -- new timer scheduled
    debouncer.update(WOK_PRESENT)  # flips back again -- cancelled again

    assert changes == []
    assert len(scheduler.cancelled) == 2
    assert scheduler.scheduled == []


def test_debouncer_accepts_after_timer_fires_uninterrupted():
    scheduler = FakeScheduler()
    changes = []
    debouncer = make_debouncer(scheduler, changes.append)

    debouncer.update(WOK_ABSENT)
    scheduler.fire_all()  # simulate the debounce window elapsing, undisturbed

    assert changes == [WOK_ABSENT]


def test_repeated_reports_of_the_same_pending_candidate_do_not_restart_the_timer():
    """A real sensor may report the same new value more than once before it
    settles -- that must not keep pushing the debounce window out."""
    scheduler = FakeScheduler()
    changes = []
    debouncer = make_debouncer(scheduler, changes.append)

    debouncer.update(WOK_ABSENT)
    debouncer.update(WOK_ABSENT)

    assert len(scheduler.scheduled) == 1


# --- edge detection ------------------------------------------------------


def test_transition_to_absent_sends_one_shot_1_and_enters_busy():
    scheduler, osc = FakeScheduler(), FakeOscSender()
    machine = make_machine(scheduler, osc)

    machine.feed_logical(WOK_ABSENT)
    scheduler.fire_all()  # debounce timer fires -> edge accepted -> lockout starts

    assert osc.sent == [1]
    assert machine.busy is True


def test_transition_to_present_sends_one_shot_0():
    scheduler, osc = FakeScheduler(), FakeOscSender()
    machine = make_machine(scheduler, osc)

    machine.feed_logical(WOK_ABSENT)
    scheduler.fire_all()  # debounce -> edge -> lockout timer now pending
    osc.sent.clear()
    scheduler.fire_all()  # lockout timer fires -> busy clears

    machine.feed_logical(WOK_PRESENT)
    scheduler.fire_all()  # debounce timer fires -> edge accepted

    assert osc.sent == [0]


# --- busy / lockout suppression ------------------------------------------


def test_transitions_suppressed_while_busy():
    scheduler, osc = FakeScheduler(), FakeOscSender()
    machine = make_machine(scheduler, osc)

    machine.feed_logical(WOK_ABSENT)
    scheduler.fire_all()  # debounce -> edge -> lockout timer now pending
    assert osc.sent == [1]
    assert machine.busy is True

    # Wok placed back, then removed again, all while still busy -- both
    # debounce timers must fire without producing any OSC traffic, and the
    # already-pending lockout timer must be left untouched throughout.
    machine.feed_logical(WOK_PRESENT)
    scheduler.fire_latest()  # fires only the WOK_PRESENT debounce timer
    machine.feed_logical(WOK_ABSENT)
    scheduler.fire_latest()  # fires only the WOK_ABSENT debounce timer

    assert osc.sent == [1]
    assert machine.busy is True
    assert len(scheduler.scheduled) == 1  # the still-pending lockout timer


# --- timer-based unlock ---------------------------------------------------


def test_unlock_after_lockout_resumes_normal_edge_behavior():
    scheduler, osc = FakeScheduler(), FakeOscSender()
    machine = make_machine(scheduler, osc, lockout_seconds=60)

    machine.feed_logical(WOK_ABSENT)
    scheduler.fire_all()  # debounce -> edge -> lockout timer scheduled
    assert machine.busy is True
    assert len(scheduler.scheduled) == 1
    assert scheduler.scheduled[0][1] == 60

    scheduler.fire_all()  # simulate the lockout timer elapsing
    assert machine.busy is False

    # fresh edge after unlock is handled normally again
    machine.feed_logical(WOK_PRESENT)
    scheduler.fire_all()  # debounce timer fires -> edge accepted
    assert osc.sent == [1, 0]


def test_shutdown_cancels_pending_lockout_timer():
    scheduler, osc = FakeScheduler(), FakeOscSender()
    machine = make_machine(scheduler, osc)

    machine.feed_logical(WOK_ABSENT)
    scheduler.fire_all()  # debounce -> edge -> lockout timer scheduled
    assert machine.busy is True
    assert len(scheduler.scheduled) == 1

    machine.shutdown()

    assert len(scheduler.cancelled) == 1
    assert scheduler.scheduled == []


def test_shutdown_cancels_pending_debounce_timer():
    scheduler, osc = FakeScheduler(), FakeOscSender()
    machine = make_machine(scheduler, osc)

    machine.feed_logical(WOK_ABSENT)  # debounce timer scheduled, not yet fired
    assert len(scheduler.scheduled) == 1

    machine.shutdown()

    assert len(scheduler.cancelled) == 1
    assert scheduler.scheduled == []
    assert osc.sent == []  # never fired, so never sent


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

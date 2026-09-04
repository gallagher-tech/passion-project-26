"""Hardware-free state machine: polarity inversion, timer-based debounce,
edges, busy/lockout.

No Firmata or OSC imports here on purpose -- this module is exercised in
tests with fake pin-state sequences, a fake OSC sender, and a fake timer
scheduler.

Debounce is timer-based, not poll-based: real Firmata digital reporting is
edge-triggered (StandardFirmata sends a report only when a port's value
actually changes -- `samplingOn()`'s interval governs analog sampling, not
digital), so this can be called just once per real transition rather than
continuously while a value holds steady. A poll-based debouncer (accepting
a candidate once `now - candidate_since >= stable_duration` on a later call)
can never fire under that access pattern, since every call's `candidate`
just changed and its own elapsed time is always ~0. Scheduling an actual
timer per candidate, and cancelling it if a competing value shows up before
it fires, works correctly regardless of how often (or rarely) `update()` is
called while a value is held.
"""
import logging

logger = logging.getLogger(__name__)

# Logical values. The sensor's raw electrical signal is inverted exactly once,
# at the boundary in `raw_to_logical`, and every consumer below only ever sees
# these logical values -- never raw polarity.
WOK_PRESENT = 0
WOK_ABSENT = 1


def raw_to_logical(raw_value):
    """Invert the raw Firmata digital pin reading at the input boundary.

    raw HIGH (1) -> WOK_PRESENT (0); raw LOW (0) -> WOK_ABSENT (1).
    """
    return WOK_ABSENT if raw_value == 0 else WOK_PRESENT


class Debouncer:
    """Accepts a value only after it has held for `stable_duration_seconds`
    uninterrupted, using an injected timer rather than polling elapsed time.

    `on_stable_change(value)` is called once a candidate survives the full
    debounce window without a competing value showing up first. A report of
    the current stable value cancels any in-flight competing candidate (a
    glitch that reversed itself); a repeated report of the same in-flight
    candidate is a no-op (it must not keep pushing the window out).
    """

    def __init__(
        self,
        stable_duration_seconds,
        initial_value,
        on_stable_change,
        schedule_timer,
        cancel_timer,
    ):
        self._stable_duration = stable_duration_seconds
        self._on_stable_change = on_stable_change
        self._schedule_timer = schedule_timer
        self._cancel_timer = cancel_timer
        self._stable_value = initial_value
        self._pending_value = None
        self._pending_timer = None

    def update(self, raw_value):
        """Feed a new raw reading -- may be called once per real transition
        or many times while a value holds; both are handled correctly."""
        if raw_value == self._stable_value:
            self._cancel_pending()
            return

        if raw_value == self._pending_value:
            return  # already debouncing toward this value -- let it run

        self._cancel_pending()
        self._pending_value = raw_value
        self._pending_timer = self._schedule_timer(self._stable_duration, self._commit)

    def _commit(self):
        self._stable_value = self._pending_value
        self._pending_value = None
        self._pending_timer = None
        self._on_stable_change(self._stable_value)

    def _cancel_pending(self):
        if self._pending_timer is not None:
            self._cancel_timer(self._pending_timer)
            self._pending_timer = None
            self._pending_value = None

    def shutdown(self):
        self._cancel_pending()


class WokStateMachine:
    """Debounce + edge detection + busy/lockout, decoupled from I/O.

    `send_osc(value)` and `schedule_timer(delay_seconds, callback) -> handle`
    are injected so this can run against a fake OSC sender and a fake timer
    in tests, or real python-osc / threading.Timer at runtime.
    """

    def __init__(
        self,
        debounce_seconds,
        lockout_seconds,
        send_osc,
        schedule_timer,
        cancel_timer=None,
        initial_logical=WOK_PRESENT,
    ):
        self._debouncer = Debouncer(
            debounce_seconds,
            initial_logical,
            self._on_debounced_transition,
            schedule_timer,
            cancel_timer,
        )
        self._lockout_seconds = lockout_seconds
        self._send_osc = send_osc
        self._schedule_timer = schedule_timer
        self._cancel_timer = cancel_timer
        self._busy = False
        self._timer_handle = None

    @property
    def busy(self):
        return self._busy

    def feed_raw(self, raw_value):
        self.feed_logical(raw_to_logical(raw_value))

    def feed_logical(self, logical_value):
        self._debouncer.update(logical_value)

    def _on_debounced_transition(self, new_logical_value):
        if self._busy:
            logger.debug(
                "Ignored transition to %s while busy (lockout in progress)",
                "WOK_ABSENT" if new_logical_value == WOK_ABSENT else "WOK_PRESENT",
            )
            return

        if new_logical_value == WOK_ABSENT:
            logger.info("WOK_ABSENT detected -> video on")
            self._send_osc(1)
            self._start_lockout()
        else:
            logger.info("WOK_PRESENT detected -> video off")
            self._send_osc(0)

    def _start_lockout(self):
        self._busy = True
        self._timer_handle = self._schedule_timer(self._lockout_seconds, self._unlock)

    def _unlock(self):
        # Deliberately does not re-check the sensor's current state here --
        # see README for the rationale and the option to revisit this later.
        self._busy = False
        self._timer_handle = None

    def shutdown(self):
        self._debouncer.shutdown()
        if self._timer_handle is not None and self._cancel_timer is not None:
            self._cancel_timer(self._timer_handle)
            self._timer_handle = None

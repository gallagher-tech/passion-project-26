"""Hardware-free state machine: polarity inversion, debounce, edges, busy/lockout.

No Firmata or OSC imports here on purpose -- this module is exercised in tests
with fake pin-state sequences, a fake clock, and a fake timer scheduler.
"""
import logging
import time

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
    """Requires a value to be stable for `stable_duration_seconds` before
    accepting it, and reports only actual changes (i.e. also acts as the
    edge detector on the debounced signal)."""

    def __init__(self, stable_duration_seconds, initial_value, clock=time.monotonic):
        self._stable_duration = stable_duration_seconds
        self._clock = clock
        self._stable_value = initial_value
        self._candidate_value = initial_value
        self._candidate_since = None

    def update(self, raw_value, now=None):
        """Feed a new raw reading. Returns the new stable value if a debounced
        transition just occurred, otherwise None."""
        now = self._clock() if now is None else now

        if raw_value != self._candidate_value:
            self._candidate_value = raw_value
            self._candidate_since = now

        if self._candidate_value == self._stable_value:
            return None

        if now - self._candidate_since >= self._stable_duration:
            self._stable_value = self._candidate_value
            return self._stable_value

        return None


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
        clock=time.monotonic,
        initial_logical=WOK_PRESENT,
    ):
        self._debouncer = Debouncer(debounce_seconds, initial_logical, clock=clock)
        self._lockout_seconds = lockout_seconds
        self._send_osc = send_osc
        self._schedule_timer = schedule_timer
        self._cancel_timer = cancel_timer
        self._busy = False
        self._timer_handle = None

    @property
    def busy(self):
        return self._busy

    def feed_raw(self, raw_value, now=None):
        self.feed_logical(raw_to_logical(raw_value), now=now)

    def feed_logical(self, logical_value, now=None):
        changed = self._debouncer.update(logical_value, now=now)
        if changed is None:
            return
        self._on_debounced_transition(changed)

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
        if self._timer_handle is not None and self._cancel_timer is not None:
            self._cancel_timer(self._timer_handle)
            self._timer_handle = None

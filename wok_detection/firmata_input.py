"""Non-blocking Firmata digital pin reader, using pyfirmata2 (the maintained fork).

pyfirmata2's `Arduino` runs its own background iterator thread once
`samplingOn()` is called, and delivers pin values via callback -- there is
no blocking read/poll loop here. Verify method names below against your
installed pyfirmata2 version if you hit AttributeErrors; the fork's public
API has been stable but is not guaranteed across major versions.
"""
import logging

from pyfirmata2 import Arduino

logger = logging.getLogger(__name__)


class FirmataDigitalInput:
    def __init__(self, port, pin, sampling_interval_ms, on_raw_value):
        self._on_raw_value = on_raw_value
        self._board = Arduino(port)
        self._board.samplingOn(sampling_interval_ms)
        self._pin = self._board.get_pin("d:{}:i".format(pin))
        self._pin.register_callback(self._handle_value)
        self._pin.enable_reporting()
        logger.info(
            "Firmata connected on %s, watching D%s (sampling every %sms)",
            port,
            pin,
            sampling_interval_ms,
        )

    def _handle_value(self, value):
        if value is None:
            return
        self._on_raw_value(int(value))

    def close(self):
        try:
            self._board.exit()
        except Exception:
            logger.exception("Error while closing Firmata board")

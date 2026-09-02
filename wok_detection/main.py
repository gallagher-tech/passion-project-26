"""Entry point: wires Firmata input -> state machine -> OSC output.

Run with: python -m wok_detection.main --port COM3
See README.md for the full CLI, defaults, and MadMapper-side setup.
"""
import argparse
import logging
import signal
import threading

from wok_detection.firmata_input import FirmataDigitalInput
from wok_detection.osc_output import OscVideoSender
from wok_detection.state_machine import WOK_PRESENT, WokStateMachine

# Sole driver of the `busy` lockout window (see README). Trivial to find and
# adjust on-site without digging through the rest of the script.
LOCKOUT_DURATION_SECONDS = 60


def parse_args():
    parser = argparse.ArgumentParser(description="WOK detection Firmata -> OSC bridge")
    parser.add_argument("--port", required=True, help="Arduino serial port, e.g. COM3 or /dev/ttyACM0")
    parser.add_argument("--pin", type=int, default=2, help="Digital pin number (default: 2)")
    parser.add_argument("--debounce-ms", type=float, default=50, help="Debounce duration in ms (default: 50)")
    parser.add_argument(
        "--sampling-interval-ms",
        type=int,
        default=19,
        help="Firmata sampling interval in ms (default: 19, pyfirmata2's own default)",
    )
    parser.add_argument("--osc-host", default="127.0.0.1", help="MadMapper OSC listen host (default: 127.0.0.1)")
    parser.add_argument("--osc-port", type=int, default=8000, help="MadMapper OSC listen port (default: 8000)")
    parser.add_argument("--osc-address", default="/video", help="OSC address (default: /video)")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    return parser.parse_args()


def schedule_timer(delay_seconds, callback):
    timer = threading.Timer(delay_seconds, callback)
    timer.daemon = True
    timer.start()
    return timer


def cancel_timer(timer):
    timer.cancel()


def main():
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    logger = logging.getLogger("wok_detection.main")

    osc_sender = OscVideoSender(args.osc_host, args.osc_port, args.osc_address)

    state_machine = WokStateMachine(
        debounce_seconds=args.debounce_ms / 1000.0,
        lockout_seconds=LOCKOUT_DURATION_SECONDS,
        send_osc=osc_sender.send,
        schedule_timer=schedule_timer,
        cancel_timer=cancel_timer,
        initial_logical=WOK_PRESENT,
    )

    firmata_input = FirmataDigitalInput(
        port=args.port,
        pin=args.pin,
        sampling_interval_ms=args.sampling_interval_ms,
        on_raw_value=state_machine.feed_raw,
    )

    stop_event = threading.Event()

    def handle_shutdown_signal(signum, frame):
        logger.info("Shutdown signal received, cleaning up...")
        stop_event.set()

    signal.signal(signal.SIGINT, handle_shutdown_signal)
    signal.signal(signal.SIGTERM, handle_shutdown_signal)

    logger.info("WOK detection bridge running. Press Ctrl+C to stop.")
    try:
        while not stop_event.is_set():
            stop_event.wait(0.2)
    finally:
        state_machine.shutdown()
        firmata_input.close()
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    main()

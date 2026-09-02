"""OSC client wrapper for sending video on/off messages to MadMapper."""
import logging

from pythonosc.udp_client import SimpleUDPClient

logger = logging.getLogger(__name__)


class OscVideoSender:
    def __init__(self, host, port, address):
        self._client = SimpleUDPClient(host, port)
        self._address = address
        logger.info("OSC out -> %s:%s%s", host, port, address)

    def send(self, value):
        logger.info("Sending OSC %s %s", self._address, value)
        self._client.send_message(self._address, value)

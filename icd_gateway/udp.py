"""One portable UDP service adapter. No original toolchain is replaced."""

import math
import socket
import time

from icd_runtime.errors import ICDError
from .config import endpoint
from .session import PeerBinding


class UDPGateway:
    def __init__(self, receiver, *, bind, feedback_routes, channel):
        self.receiver = receiver
        self.channel = channel
        if channel not in {f"ETH_{i}" for i in range(4)} or not feedback_routes:
            raise ICDError("SCHEMA", "declared Ethernet channel and explicit feedback routes required")
        self._routes = {}
        for binding, target in feedback_routes.items():
            if binding.channel != channel or binding.transport != "UDP" or not receiver.registry.link_authorized(binding):
                raise ICDError("AUTHORIZATION", "feedback route lacks matching input grant")
            self._routes[binding] = endpoint(target)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.socket.bind(endpoint(bind, allow_ephemeral=True))
        except Exception:
            self.socket.close()
            raise
        self.address = self.socket.getsockname()
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if not self._closed:
            self._closed = True
            self.socket.close()
        return self.receiver.close()

    def _send(self, binding, replies):
        if binding not in self._routes or not self.receiver.registry.link_authorized(binding):
            raise ICDError("AUTHORIZATION", "resource feedback has no original authorized route")
        sent = 0
        for reply in replies:
            for encoded in self.receiver.wire.encode(reply, "UDP"):
                self.socket.sendto(encoded, self._routes[binding])
                sent += 1
        return sent

    def _resource_feedback(self):
        sent = 0
        for binding, reply in self.receiver.resource_feedback(now_ns=time.monotonic_ns()):
            try:
                sent += self._send(binding, (reply,))
            except ICDError as error:
                self.receiver.note_error(error)
            except OSError:
                self.receiver.note_error(ICDError("STATE", "actual UDP feedback send failed; original result retained"))
        return sent

    def poll(self, *, timeout=0.02):
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout < 0:
            raise ICDError("SCHEMA", "finite nonnegative polling timeout required")
        if self._closed:
            raise ICDError("STATE", "UDP gateway closed")
        self.receiver.tick(now_ns=time.monotonic_ns())
        sent = self._resource_feedback()
        self.socket.settimeout(min(timeout, 0.02))
        try:
            packet, actual_peer = self.socket.recvfrom(1201)
        except (socket.timeout, BlockingIOError):
            self.receiver.tick(now_ns=time.monotonic_ns())
            return sent + self._resource_feedback()
        binding = PeerBinding(self.channel, "UDP", f"{actual_peer[0]}:{actual_peer[1]}")
        try:
            if binding not in self._routes:
                raise ICDError("AUTHORIZATION", "no registered reverse route for actual source")
            replies = self.receiver.receive(packet, binding, now_ns=time.monotonic_ns())
            return sent + self._send(binding, replies)
        except ICDError as error:
            self.receiver.note_error(error)
            return sent

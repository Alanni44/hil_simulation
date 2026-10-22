"""Deployment-owned factory for the minimal formal UDP execution backend."""

from pathlib import Path
import hashlib

from icd_gateway.config import parse_endpoint
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import loads

from .run_executor import FormalHILExecutionBackend
from .session import SourceSession
from .udp_source import UDPSource


class FormalRuntimeFactory:
    """Validate fixed transport identity once and create one source per Run."""

    _LEGACY_FIELDS = frozenset({"identity", "roles", "channel", "source_bind", "feedback_bind",
                                "receiver_endpoint", "stop_lead_steps", "status_poll_ms",
                                "can_channel", "can_interface", "resource_root"})
    _FIELDS = _LEGACY_FIELDS | frozenset({"session_max_records"})

    @classmethod
    def load(cls, contract, path):
        path = Path(path)
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise ICDError("RESOURCE", "formal simulator runtime configuration is unavailable") from error
        if len(raw) > 65536:
            raise ICDError("CAPACITY", "formal simulator runtime configuration is too large")
        return cls(contract, loads(raw))

    def __init__(self, contract, value):
        if type(value) is not dict or set(value) not in {self._LEGACY_FIELDS, self._FIELDS}:
            raise ICDError("SCHEMA", "complete fixed formal runtime configuration required")
        if type(value["roles"]) is not list or not value["roles"] or type(value["channel"]) is not str:
            raise ICDError("SCHEMA", "formal runtime roles/channel required")
        self.contract = contract
        self.identity = value["identity"]
        self.roles = tuple(value["roles"])
        self.channel = value["channel"]
        self.source_bind = parse_endpoint(value["source_bind"])
        self.feedback_bind = parse_endpoint(value["feedback_bind"])
        self.receiver_endpoint = parse_endpoint(value["receiver_endpoint"])
        if (value["can_channel"] != "CANFD_0" or type(value["can_interface"]) is not str
                or not value["can_interface"]):
            raise ICDError("SCHEMA", "fixed CANFD_0 runtime binding required")
        # The service validates UDP ownership at startup.  The CAN resources
        # are deliberately checked only when a CANT scenario starts, so an
        # idle management service does not claim that its scenario driver is
        # available before the actual immutable resources are read.
        self.resource_root = Path(value["resource_root"])
        self.can_channel, self.can_interface = value["can_channel"], value["can_interface"]
        lead, poll = value["stop_lead_steps"], value["status_poll_ms"]
        if type(lead) is not int or not 1 <= lead <= 1000 or type(poll) is not int or not 1 <= poll <= 1000:
            raise ICDError("SCHEMA", "bounded formal runtime stop lead/poll required")
        # Existing deployed configurations predate this bounded evidence
        # setting.  Keep them usable with the safe maximum; newly exported
        # configurations state the same value explicitly.
        session_max_records = value.get("session_max_records", 4096)
        if type(session_max_records) is not int or not 64 <= session_max_records <= 4096:
            raise ICDError("SCHEMA", "formal runtime session evidence capacity must be 64..4096")
        # SourceSession performs full identity and requested-role contract checks.
        try:
            probe_transport = UDPSource(contract, source_bind=self.source_bind, feedback_bind=self.feedback_bind,
                                        receiver_endpoint=self.receiver_endpoint, channel=self.channel)
        except OSError as error:
            raise ICDError("RESOURCE", "formal simulator runtime UDP endpoints cannot be bound") from error
        try:
            probe = SourceSession(probe_transport, self.identity, self.roles,
                                  max_records=session_max_records)
            probe.close()
        finally:
            probe_transport.close()
        self.stop_lead_steps, self.status_poll_s = lead, poll / 1000.0
        self.session_max_records = session_max_records

    def _can_sender(self, session, request):
        """Create the original CANT sender from the Run's frozen resources."""
        from .can_signal import CANSignalSender
        from .live_tool_input import LiveToolInputBuilder
        from .protocol import ProtocolParser
        from .replay_export import ExportBinding
        from .tools import ChannelReservations

        inputs = request.get("source_inputs")
        protocol = None if type(inputs) is not dict else inputs.get("protocol")
        refs = None if type(protocol) is not dict else protocol.get("resources")
        if type(refs) is not list:
            raise ICDError("RESOURCE", "frozen CANT protocol resources are missing")
        try:
            root = self.resource_root.resolve(strict=True)
        except OSError as error:
            raise ICDError("RESOURCE", "formal simulator CAN resource root is unavailable") from error
        if not root.is_dir():
            raise ICDError("RESOURCE", "formal simulator CAN resource root is not a directory")
        resources = {}
        for ref in refs:
            if type(ref) is not dict or type(ref.get("resource_id")) is not str:
                raise ICDError("RESOURCE", "frozen CANT resource reference is invalid")
            name, size, digest = ref.get("file_name"), ref.get("size_bytes"), ref.get("sha256")
            if (type(name) is not str or Path(name).name != name or type(size) is not int
                    or type(digest) is not str):
                raise ICDError("RESOURCE", "frozen CANT resource metadata is invalid")
            path = (root / name).resolve(strict=False)
            try:
                path.relative_to(root)
                raw = path.read_bytes()
            except (OSError, ValueError) as error:
                raise ICDError("RESOURCE", "frozen CANT resource is unavailable") from error
            if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
                raise ICDError("RESOURCE", "frozen CANT resource bytes differ")
            resources[ref["resource_id"]] = raw
        parser = ProtocolParser(self.contract)
        parser.parse(protocol, resources)
        book = ChannelReservations()
        token = book.reserve("formal-run-cant", "CANT", (self.can_interface,), mode="SEND")
        sender = CANSignalSender(LiveToolInputBuilder(book, session, protocol=parser), token,
                                 ExportBinding(self.can_channel, self.can_interface))
        return sender, book, token

    def backend(self):
        def session_factory(_snapshot):
            transport = UDPSource(self.contract, source_bind=self.source_bind,
                                  feedback_bind=self.feedback_bind,
                                  receiver_endpoint=self.receiver_endpoint, channel=self.channel)
            return SourceSession(transport, self.identity, self.roles,
                                 max_records=self.session_max_records)
        return FormalHILExecutionBackend(session_factory, can_sender_factory=self._can_sender,
                                         stop_lead_steps=self.stop_lead_steps,
                                         status_poll_s=self.status_poll_s)

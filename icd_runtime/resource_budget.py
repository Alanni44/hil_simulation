"""Conservative background IPv4/UDP Ethernet accounting, not realtime timing."""

from .errors import ICDError


class ResourceBudget:
    def __init__(self, contract, *, bits_per_second=None):
        maximum = contract.catalogue["policy"]["max_resource_bps"]
        self.bits_per_second = maximum if bits_per_second is None else bits_per_second
        if type(self.bits_per_second) is not int or not 1 <= self.bits_per_second <= maximum:
            raise ICDError("CAPACITY", "background resource rate must be1..frozen max_resource_bps")
        self._next_ns = 0
        self._last_ns = -1

    @staticmethod
    def wire_bits(packets):
        if type(packets) is not tuple or not packets:
            raise ICDError("SCHEMA", "actual nonempty UDP packet tuple required")
        if any(type(packet) is not bytes or not 40 <= len(packet) <= 1200 for packet in packets):
            raise ICDError("CAPACITY", "resource budget requires actual bounded ICD UDP packets")
        # IPv4+UDP28, Ethernet+FCS18, preamble8 and IFG12. Target VLANs need a separate link budget.
        return sum((max(len(packet) + 46, 64) + 20) * 8 for packet in packets)

    def preview(self, packets, *, now_ns):
        if type(now_ns) is not int or now_ns < 0 or now_ns < self._last_ns:
            raise ICDError("SCHEMA", "nondecreasing background budget clock required")
        bits = self.wire_bits(packets)
        duration = (bits * 1_000_000_000 + self.bits_per_second - 1) // self.bits_per_second
        return max(now_ns, self._next_ns) + duration

    def reserve(self, packets, *, now_ns):
        due = self.preview(packets, now_ns=now_ns)
        self._last_ns = now_ns
        self._next_ns = due
        return due

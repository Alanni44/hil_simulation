"""Source-neutral physical-UUT boundary and deterministic simulated adapter.

No electrical or bus protocol is assumed here.  A future CAN/serial/Ethernet
driver implements the same two methods and is still subject to the C-core
``physical_uut`` source selection and timeout safety path.
"""
from __future__ import print_function

from abc import ABCMeta, abstractmethod
from collections import deque


class PhysicalUutAdapter(object, metaclass=ABCMeta):
    @abstractmethod
    def publish_sensor(self, sensor_frame):
        """Deliver one normalized sensor frame to the UUT."""

    @abstractmethod
    def poll_actuators(self):
        """Return newest normalized actuator vector or ``None``."""

    @abstractmethod
    def close(self):
        """Release adapter resources."""


class SimulatedUutAdapter(PhysicalUutAdapter):
    """In-memory adapter for integration tests before a hardware ICD exists."""
    def __init__(self, max_history=1024):
        self.sensor_history = deque(maxlen=int(max_history))
        self._actuators = deque(maxlen=1)
        self.closed = False

    def publish_sensor(self, sensor_frame):
        if self.closed:
            raise RuntimeError('simulated UUT adapter is closed')
        self.sensor_history.append(dict(sensor_frame))

    def inject_actuators(self, values):
        if self.closed:
            raise RuntimeError('simulated UUT adapter is closed')
        self._actuators.append(list(values))

    def poll_actuators(self):
        if self.closed or not self._actuators:
            return None
        return self._actuators.pop()

    def close(self):
        self.closed = True
        self._actuators.clear()

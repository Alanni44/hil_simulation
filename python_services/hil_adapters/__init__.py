"""Transport adapters for external HIL control sources.

Adapters translate a transport protocol to source-neutral actuator and sensor
frames.  They never arbitrate control authority; the C core does that.
"""

from .mavlink_hil import MavlinkHilAdapter
from .px4_hil_service import Px4HilService
from .physical_uut import PhysicalUutAdapter, SimulatedUutAdapter

__all__ = ('MavlinkHilAdapter', 'Px4HilService', 'PhysicalUutAdapter',
           'SimulatedUutAdapter')

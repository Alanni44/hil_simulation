"""uXRCE-DDS adapter contract.

The concrete wire binding is deferred until the PX4 message set, Agent address
and QoS policy are deployed.  Keeping this interface transport-neutral avoids
letting DDS bypass the same C-core control-source arbiter used by MAVLink.
"""
from __future__ import print_function


class UxrceDdsAdapter(object):
    def __init__(self, agent_host, agent_port, namespace=''):
        self.agent_host = agent_host
        self.agent_port = int(agent_port)
        self.namespace = namespace
        self.connected = False

    def connect(self):
        raise RuntimeError('uXRCE-DDS transport requires the deployed PX4 message set and Agent QoS configuration')

    def publish_sensor(self, sensor_frame):
        if not self.connected:
            raise RuntimeError('uXRCE-DDS adapter is not connected')

    def poll_actuators(self):
        if not self.connected:
            return None
        return None

"""Original python-can/SocketCAN adapter into the same standard ICD Receiver."""

import math
import re
import time
import can

from icd_runtime.errors import ICDError
from icd_runtime.wire import CANFrame
from .session import PeerBinding


class CANGateway:
    def __init__(self, receiver, *, channel, interface, bus=None):
        if (channel not in {f'CANFD_{i}' for i in range(4)} or type(interface) is not str
                or re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}',interface) is None or interface=='any'):
            raise ICDError('SCHEMA','explicit formal CAN FD channel/interface required')
        self.binding=PeerBinding(channel,'CANFD',interface)
        if not receiver.registry.link_authorized(self.binding):
            raise ICDError('AUTHORIZATION','CAN input requires its registered original grant')
        if bus is None:
            try:
                bus=can.Bus(interface='socketcan',channel=interface,fd=True,
                            receive_own_messages=False,ignore_config=True)
            except Exception as exc:
                raise ICDError('TARGET_MISSING','original SocketCAN unavailable; no alternate backend') from exc
        if not isinstance(bus,can.BusABC) or bus._is_shutdown:
            raise ICDError('STATE','actual live python-can bus required')
        self.receiver,self.bus=receiver,bus
        self._closed=False

    def __enter__(self):
        return self

    def __exit__(self,*args):
        self.close()

    def close(self):
        if not self._closed:
            self.bus.shutdown()
            self._closed=True

    def poll(self, *, timeout=0.01, now_ns=None):
        if self._closed or self.bus._is_shutdown:
            raise ICDError('STATE','CAN gateway closed')
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<=timeout<=0.02:
            raise ICDError('SCHEMA','CAN polling timeout must be finite and within 0..20ms')
        now=time.monotonic_ns() if now_ns is None else now_ns
        self.receiver.tick(now_ns=now)
        try:
            frame=self.bus.recv(timeout)
        except (can.CanError,OSError) as exc:
            raise ICDError('RESOURCE','original CAN receive failed') from exc
        if frame is None:
            return 0
        now=time.monotonic_ns() if now_ns is None else now_ns
        try:
            if (frame.is_fd is not True or frame.bitrate_switch is not True
                    or frame.is_extended_id is not False or frame.is_remote_frame is not False
                    or frame.is_error_frame is not False or frame.error_state_indicator is not False
                    or frame.is_rx is not True or type(frame.dlc) is not int or frame.dlc!=64
                    or len(frame.data)!=64):
                raise ICDError('SCHEMA','actual received non-error FD/BRS standard 64-byte data frame required')
            packet=CANFrame(frame.arbitration_id,bytes(frame.data))
            replies=self.receiver.receive(packet,self.binding,now_ns=now)
            sent=0
            for reply in replies:
                for encoded in self.receiver.wire.encode(reply,'CANFD'):
                    try:
                        result=self.bus.send(can.Message(arbitration_id=encoded.arbitration_id,data=encoded.data,
                            is_extended_id=False,is_fd=True,bitrate_switch=True,check=True),timeout=0.01)
                        if result is not None:
                            raise can.CanError('original CAN feedback returned an invalid result')
                    except (can.CanError,OSError) as exc:
                        raise ICDError('RESOURCE','original CAN feedback failed; decoded record retained') from exc
                    sent+=1
            return sent
        except ICDError as exc:
            self.receiver.note_error(exc)
            if exc.code=='RESOURCE':
                raise
            return 0

"""Real python-can library reception, explicitly not physical CAN qualification."""

import importlib.util
import uuid
import can
from unittest.mock import patch

from common import GatewayTest, message
from icd_gateway.receiver import Receiver
from icd_gateway.reception_service import ReceptionService
from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
from icd_runtime.json_codec import loads
from icd_runtime.reassembly import Reassembler
from icd_runtime.wire import CANFrame


class CANIngressTests(GatewayTest):
    def create(self):
        self.assertIsNotNone(importlib.util.find_spec('icd_gateway.can_ingress'),'same-path CAN ingress missing')
        from icd_gateway.can_ingress import CANGateway
        self.link=PeerBinding('CANFD_0','CANFD','can0')
        self.udp=PeerBinding('ETH_0','UDP','127.0.0.1:36102')
        self.registry=SessionRegistry(self.contract,[SourceGrant(message(1)['payload']['identity'],
            ('STIMULUS',),(self.udp,self.link))])
        self.service=ReceptionService(self.contract,self.registry,(10,))
        self.receiver=Receiver(self.contract,self.registry,reception_service=self.service)
        opening=message(1)
        opened=self.receiver.receive(self.receiver.wire.encode(opening,'UDP')[0],self.udp,now_ns=0)[0]
        self.sid=opened['payload']['session_id']
        channel=uuid.uuid4().hex
        self.bus=can.Bus(interface='virtual',channel=channel,ignore_config=True)
        self.peer=can.Bus(interface='virtual',channel=channel,ignore_config=True)
        self.gateway=CANGateway(self.receiver,channel='CANFD_0',interface='can0',bus=self.bus)
        self.addCleanup(self.peer.shutdown)
        self.addCleanup(self.gateway.close)
        self.addCleanup(self.receiver.close)

    def send(self, *, corrupt=False):
        value=message(10)
        value['header'].update(session_id=self.sid,sequence=2,transaction_id=2,target_step=80)
        for frame in self.receiver.wire.encode(value,'CANFD'):
            raw=bytearray(frame.data)
            if corrupt:
                raw[-1]^=1
            self.peer.send(can.Message(arbitration_id=frame.arbitration_id,data=raw,
                is_fd=True,bitrate_switch=True,is_extended_id=False,check=True))
            self.gateway.poll(timeout=0.01,now_ns=1)
        return value

    def test_actual_original_fd_frames_decode_and_return_standard_feedback(self):
        self.create()
        value=self.send()
        self.assertEqual(loads(self.service.records[0].message_json),value)
        self.assertEqual(self.service.records[0].binding,self.link)
        assembler=Reassembler(self.contract)
        replies=[]
        while True:
            frame=self.peer.recv(0.01)
            if frame is None:
                break
            part=self.receiver.wire.decode(CANFrame(frame.arbitration_id,bytes(frame.data)),
                                            'CANFD',direction='FROM_36')
            result=assembler.push(part,channel='CANFD_0',direction='FROM_36',authorized=True,now_ns=2)
            if result is not None:
                replies.append(result.message)
        self.assertEqual([r['payload']['stage'] for r in replies],['RECEIVED','VALIDATED'])
        self.assertTrue(all(r['payload']['probe_id']==0 for r in replies))

    def test_bad_crc_and_classic_frame_do_not_decode_or_admit(self):
        self.create()
        self.send(corrupt=True)
        self.assertEqual(self.service.records,())
        self.peer.send(can.Message(arbitration_id=1,data=b'bad',is_extended_id=False,check=True))
        self.gateway.poll(timeout=0.01,now_ns=2)
        self.assertEqual(self.service.records,())
        self.assertGreater(self.receiver.errors['CRC'],0)
        self.assertGreater(self.receiver.errors['SCHEMA'],0)

    def test_close_owns_only_bus_not_other_receiver_transports(self):
        self.create()
        self.gateway.close()
        self.assertTrue(self.bus._is_shutdown)
        self.assertFalse(self.receiver._closed)
        self.rejects('STATE',lambda:self.gateway.poll(timeout=0))

    def test_native_receive_and_feedback_failure_keep_decoded_records(self):
        self.create()
        with patch.object(self.bus,'recv',side_effect=can.CanError('test receive failed')):
            self.rejects('RESOURCE',lambda:self.gateway.poll(timeout=0,now_ns=1))
        with patch.object(self.bus,'send',side_effect=can.CanError('test feedback failed')):
            self.rejects('RESOURCE',self.send)
        self.assertEqual(len(self.service.records),1)
        self.assertEqual(loads(self.service.records[0].message_json)['message_id'],10)

    def test_unregistered_binding_rejects_before_backend_open(self):
        self.create()
        from icd_gateway.can_ingress import CANGateway
        self.rejects('AUTHORIZATION',lambda:CANGateway(self.receiver,channel='CANFD_1',interface='can1'))

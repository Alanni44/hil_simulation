"""ID10 can become APPLIED only through the installed model consumer."""

from common import GatewayTest, message
from test_model_bindings import declared_runtime
from icd_gateway.model_consumer import QuadrotorEnvironmentBridge


class FakeEnvironmentBridge(QuadrotorEnvironmentBridge):
    """Test double retains the concrete bridge type's application contract."""

    def apply_environment(self, request, bindings, *, now_ns):
        from icd_gateway.model_consumer import EnvironmentApplication
        from icd_runtime.json_codec import canonicalize
        return EnvironmentApplication(request['header']['target_step'], 7,
                                      canonicalize(request['payload']))

    def apply_flight_control(self, request, bindings, *, now_ns):
        from icd_gateway.model_consumer import EnvironmentApplication
        from icd_runtime.json_codec import canonicalize
        return EnvironmentApplication(request['header']['target_step'], 9,
                                      canonicalize(request['payload']['motor_command']))


class EnvironmentConsumerTests(GatewayTest):
    def setUp(self):
        super().setUp()
        from icd_gateway.model_bindings import ModelBindings
        from icd_gateway.model_consumer import EnvironmentModelConsumerService
        from icd_gateway.receiver import Receiver
        from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
        identity = message(1)['payload']['identity']
        identity['model_id'] = 'quadrotor_hil'
        self.binding = PeerBinding('ETH_0', 'UDP', '127.0.0.1:36102')
        self.registry = SessionRegistry(self.contract, [SourceGrant(identity, ('STIMULUS',), (self.binding,))])
        bindings = ModelBindings(self.contract, 'quadrotor_hil', declared_runtime(self.contract, 'quadrotor_hil'))
        fake = FakeEnvironmentBridge()
        self.service = EnvironmentModelConsumerService(self.contract, self.registry, bindings, fake,
                                                        clock=lambda: 100)
        self.receiver = Receiver(self.contract, self.registry, model_consumer_service=self.service)
        opening = message(1)
        opening['payload']['identity'] = identity
        self.sid = self.deliver(opening)[0]['payload']['session_id']

    def deliver(self, value, now=0):
        replies = ()
        for packet in self.receiver.wire.encode(value, 'UDP'):
            replies = self.receiver.receive(packet, self.binding, now_ns=now)
        return replies

    def request(self):
        value = message(10)
        value['header'].update(session_id=self.sid, sequence=2, transaction_id=20, target_step=80)
        return value

    def test_complete_environment_is_applied_at_its_target_step(self):
        opened = self.receiver._opened(self.sid, 1)
        self.assertIn(10, opened['payload']['capabilities']['implemented_message_ids'])
        self.assertIn('consumer.Environment', opened['payload']['capabilities']['available_probes'])
        request = self.request()
        replies = self.deliver(request)
        self.assertEqual([reply['payload']['stage'] for reply in replies], ['RECEIVED', 'APPLIED'])
        terminal = replies[-1]['payload']
        self.assertEqual((terminal['probe_id'], terminal['applied_step'], terminal['model_revision']),
                         (1010, 80, 7))
        self.assertEqual(self.deliver(request, now=101), replies)
        self.assertEqual(len(self.service.records), 1)

    def test_tampered_consumer_cannot_mint_an_applied_reply(self):
        request = self.request()
        received = self.receiver._ack(10, request['header'], stage='RECEIVED', error='OK')
        forged = self.receiver._ack(10, request['header'], stage='APPLIED', error='OK',
                                    applied_step=80, model_revision=7, probe_id=1010)
        self.rejects('STATE', lambda: self.registry._record_environment_response(
            request, (received, forged), object(), now_ns=100))

    def test_controller_flight_command_is_applied_at_its_target_step(self):
        from icd_gateway.model_bindings import ModelBindings
        from icd_gateway.model_consumer import FlightModelConsumerService
        from icd_gateway.receiver import Receiver
        from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
        identity = message(1)['payload']['identity']
        identity['model_id'] = 'quadrotor_hil'
        binding = PeerBinding('ETH_0', 'UDP', '127.0.0.1:36112')
        registry = SessionRegistry(self.contract, [SourceGrant(identity, ('CONTROLLER',), (binding,))])
        bindings = ModelBindings(self.contract, 'quadrotor_hil', declared_runtime(self.contract, 'quadrotor_hil'))
        service = FlightModelConsumerService(self.contract, registry, bindings, FakeEnvironmentBridge(),
                                             clock=lambda: 100)
        receiver = Receiver(self.contract, registry, model_consumer_service=service)

        def deliver(value, now=0):
            replies = ()
            for packet in receiver.wire.encode(value, 'UDP'):
                replies = receiver.receive(packet, binding, now_ns=now)
            return replies

        opening = message(1)
        opening['payload']['identity'] = identity
        opening['payload']['roles'] = ['CONTROLLER']
        sid = deliver(opening)[0]['payload']['session_id']
        value = message(7)
        value['header'].update(session_id=sid, sequence=2, transaction_id=20, target_step=80)
        replies = deliver(value)
        self.assertEqual([reply['payload']['stage'] for reply in replies], ['RECEIVED', 'APPLIED'])
        self.assertEqual((replies[-1]['payload']['probe_id'], replies[-1]['payload']['applied_step']),
                         (1007, 80))

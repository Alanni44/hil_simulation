"""Original CAN and Ethernet tool coordination, not a byte-forwarding gateway."""

from contextlib import contextmanager, ExitStack
import threading

from icd_runtime.errors import ICDError
from ._native_scope import _scope
from .can_signal import CANSignalSender
from .dispatch import UDPDispatcher


class NativeToolCoordinator:
    def __init__(self, dispatcher, senders):
        if (type(dispatcher) is not UDPDispatcher or type(senders) is not tuple
                or not 1 <= len(senders) <= 4 or any(type(s) is not CANSignalSender for s in senders)):
            raise ICDError('STATE', 'actual dispatcher and one to four explicit original CAN senders required')
        self.dispatcher, self.session, self.senders = dispatcher, dispatcher.session, senders
        self._lock = threading.Lock()
        self._operation_thread = None
        self._active_scope = self._delegated_entry = None
        self._delegated_owner = None
        self._delegated_cleanup = False
        self._closing = self._closed = False
        with dispatcher._operation(), self.session._operation(owner=dispatcher):
            if (self.session._native_tool_coordinator is not None or self.session._dispatcher is not dispatcher
                    or self.session._state != 'LIVE' or self.session._now() >= self.session._deadline_ns
                    or self.session._next_sequence != 2 or dispatcher.pending_count
                    or self.session._observation_recorder is not None):
                raise ICDError('STATE', 'fresh live grant before input allocation and one original coordinator required')
            book = senders[0].book
            if (any(s.session is not self.session or s.book is not book or s.pending_count
                    or s._closed or s._closing or s.bus._is_shutdown for s in senders)
                    or len({id(s) for s in senders}) != len(senders)
                    or len({s.binding.channel_id for s in senders}) != len(senders)
                    or len({s.binding.interface for s in senders}) != len(senders)):
                raise ICDError('STATE', 'distinct current original CAN channels in one actual session/book required')
            for sender in senders:
                book.validate(sender.reservation)
            self.session._native_tool_coordinator = self
            self._observation_owners = (dispatcher, self.session, dispatcher.transport, senders,
                                       tuple((s, s.builder, s.binding, s.book) for s in senders))

    @property
    def execution_ready(self):
        return False

    @property
    def safety_verified(self):
        return False

    @contextmanager
    def _operation(self, *, closed_ok=False):
        if not self._lock.acquire(blocking=False):
            raise ICDError('STATE', 'original tool coordinator requires one serialized owner')
        try:
            if (self._closed or self._closing) and not closed_ok:
                raise ICDError('STATE', 'original tool coordinator is permanently closing or closed')
            self._operation_thread = threading.get_ident()
            yield
        finally:
            self._operation_thread = None
            self._lock.release()

    def _registered(self, sender):
        if not any(s is sender for s in self.senders):
            raise ICDError('STATE', 'only an actual registered original CAN sender may be coordinated')

    @contextmanager
    def _delegate(self, sender, *, prepare=False, closed_ok=False, cleanup=False):
        self._registered(sender)
        if self._operation_thread != threading.get_ident():
            raise ICDError('STATE', 'actual current coordinator operation required')
        owner = self.dispatcher
        detached = self.session._native_tool_coordinator is not self
        if detached:
            if not cleanup or not self._closed or not sender._closed:
                raise ICDError('STATE', 'only owned local cleanup may outlive the closed native coordinator')
            owner = self.session._dispatcher
        with ExitStack() as stack:
            if owner is not None:
                stack.enter_context(owner._operation(closed_ok=closed_ok))
            if not sender._lock.acquire(blocking=False):
                raise ICDError('STATE', 'original native CAN owner is busy')
            stack.callback(sender._lock.release)
            stack.enter_context(sender.builder._operation())
            stack.enter_context(self.session._operation(owner=owner, closed_ok=closed_ok))
            if (detached and (not self._closed or self.session._dispatcher is not owner)
                    or not detached and (self.session._native_tool_coordinator is not self
                        or self.session._dispatcher not in (None, self.dispatcher)
                        or not closed_ok and self.session._dispatcher is not self.dispatcher)):
                raise ICDError('STATE', 'coordinator no longer owns the actual source/dispatcher')
            recorder = self.session._observation_recorder
            if recorder is not None and not recorder._owns_native(self, sender):
                raise ICDError('STATE', 'original recorder does not yet own native CAN evidence')
            scope = (self, sender.builder, None if prepare else sender, threading.get_ident())
            self._active_scope = scope
            self._delegated_entry = sender.builder if prepare else sender
            self._delegated_owner, self._delegated_cleanup = owner, cleanup
            token = _scope.set(scope)
            try:
                yield
            finally:
                self._active_scope = self._delegated_entry = None
                self._delegated_owner, self._delegated_cleanup = None, False
                _scope.reset(token)

    def prepare_can(self, sender, stimulus, *, target_step, transaction_id=None):
        with self._operation(), self._delegate(sender, prepare=True):
            return sender.builder.prepare(sender.reservation, stimulus, sender.binding,
                                           target_step=target_step, transaction_id=transaction_id)

    def send_can(self, sender, plan, *, timeout=0.01):
        with self._operation(), self._delegate(sender):
            return sender.send(plan, timeout=timeout)

    def receive_can(self, sender, plan, *, timeout=0.01):
        with self._operation(), self._delegate(sender):
            return sender.receive_for(plan, timeout=timeout)

    def poll_can(self, sender, plan):
        with self._operation(), self._delegate(sender):
            return sender.poll_for(plan)

    def retire_can(self, sender, plan):
        with self._operation(closed_ok=True), self._delegate(sender, closed_ok=True, cleanup=True):
            sender.retire(plan)

    def drain_can(self, sender):
        with self._operation(), self._delegate(sender, closed_ok=True):
            if self.session._observation_recorder is not None:
                raise ICDError('STATE', 'attached original recorder owns native record draining')
            return sender.drain_records()

    def discard_can(self, sender, plan):
        with self._operation(closed_ok=True), self._delegate(sender, prepare=True, closed_ok=True, cleanup=True):
            _, token, _ = sender.builder._owned(plan)
            if token is not sender.reservation or plan.binding != sender.binding or plan.branch_id != 'CANT':
                raise ICDError('STATE', 'only this original sender may discard its actual channel plan')
            if id(plan) in sender._pending:
                raise ICDError('STATE', 'retire actual CAN attempt before discarding its feedback context')
            sender.builder.discard(plan)

    def close_can(self, sender):
        with self._operation(), self._delegate(sender, closed_ok=True):
            sender.close()

    def discard_failed_can(self, sender, failure):
        with self._operation(closed_ok=True), self._delegate(sender, prepare=True, closed_ok=True, cleanup=True):
            _, token, _ = sender.builder._owned_failure(failure)
            if token is not sender.reservation or failure.binding != sender.binding:
                raise ICDError('STATE', 'only this original sender may reclaim its failed preparation')
            sender.builder.discard_failed(failure)

    def submit(self, stimulus, *, target_step, transaction_id=None):
        with self._operation():
            return self.dispatcher.submit(stimulus, target_step=target_step, transaction_id=transaction_id)

    def poll(self):
        with self._operation():
            return self.dispatcher.poll()

    def cancel(self, header):
        with self._operation(closed_ok=True):
            self.dispatcher.cancel(header)

    def close(self):
        with self._operation(closed_ok=True):
            if self._closed:
                return
            self._closing = True
            for sender in self.senders:
                with self._delegate(sender, closed_ok=True):
                    sender.close()
            with self.dispatcher._operation(closed_ok=True), self.session._operation(owner=self.dispatcher, closed_ok=True):
                if self.session._native_tool_coordinator is not self:
                    raise ICDError('STATE', 'original coordinator attachment changed during close')
                self.session._native_tool_coordinator = None
                self._closed = True

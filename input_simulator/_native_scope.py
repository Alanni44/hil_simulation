"""Private, exact-thread delegation while original native owner locks are held."""

from contextvars import ContextVar
import threading

from icd_runtime.errors import ICDError


_scope = ContextVar('original_native_tool_owner', default=None)


def _delegated(session, *, builder=None, sender=None):
    value = _scope.get()
    if value is None:
        return False
    coordinator, selected_builder, selected_sender, thread = value
    return (coordinator._active_scope is value
            and thread == threading.get_ident() == session._operation_thread
            and (session._native_tool_coordinator is coordinator
                 or coordinator._delegated_cleanup and coordinator._closed)
            and coordinator._operation_thread == thread
            and coordinator.session is session
            and session._dispatcher in (None, coordinator._delegated_owner)
            and (builder is None or builder is selected_builder)
            and (sender is None or sender is selected_sender))


def _admit(session, *, builder=None, sender=None, cleanup=False):
    if not _delegated(session, builder=builder, sender=sender):
        return False
    coordinator = _scope.get()[0]
    if coordinator._delegated_cleanup and not cleanup:
        raise ICDError('STATE', 'local native cleanup never grants preparation or transmission')
    selected = sender if sender is not None else builder
    if coordinator._delegated_entry is not selected:
        raise ICDError('STATE', 'original delegated public entry cannot be reused or reentered')
    coordinator._delegated_entry = None
    return True

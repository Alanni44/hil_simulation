from dataclasses import FrozenInstanceError, replace
import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

from common import GatewayTest


class ToolTests(GatewayTest):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec('input_simulator.tools'),
                             'shared original-tool inventory/reservations are missing')
        from input_simulator.tools import ChannelReservations, ToolInventory
        self.Book, self.Inventory = ChannelReservations, ToolInventory

    def test_all_six_original_branches_map_only_to_frozen_api_rows(self):
        items = self.Inventory(self.contract).inspect()
        self.assertEqual([i.catalogue_id for i in items],
                         ['CANT', 'CUTIL', 'SAVVY', 'CANREPLAY', 'ETHGEN', 'ETHREPLAY'])
        self.assertEqual([i.api_row()['branch_id'] for i in items],
                         ['SIGNAL_CAN', 'CAN_UTILS', 'SAVVYCAN', 'CAN_REPLAY', 'ETHERNET_GENERATOR', 'PCAP_REPLAY'])
        for item in items:
            self.assertEqual(set(item.api_row()), {'branch_id', 'status', 'reason'})
            self.assertIn(item.status, ('UNAVAILABLE', 'UNVERIFIED'))
            self.assertFalse(item.execution_ready)
            self.assertTrue(item.pending_checks)
            self.assertLessEqual(len(item.reason), 1024)
            changed = item.api_row()
            changed['status'] = 'AVAILABLE'
            self.assertNotEqual(changed, item.api_row())

    def test_real_library_versions_and_executable_hashes_are_inspection_not_qualification(self):
        items = self.Inventory(self.contract).inspect()
        installed = {e.name: e for i in items for e in i.evidence if e.present}
        for name in ('cantools', 'python-can', 'scapy'):
            self.assertIn(name, installed)
            self.assertTrue(installed[name].version)
            self.assertTrue(installed[name].location)
        self.assertEqual(items[0].status, 'UNVERIFIED')
        self.assertEqual(items[4].status, 'UNVERIFIED')
        for e in installed.values():
            if e.kind == 'EXECUTABLE':
                self.assertTrue(Path(e.location).is_absolute())
                self.assertEqual(e.sha256, hashlib.sha256(Path(e.location).read_bytes()).hexdigest())
        with self.assertRaises(FrozenInstanceError):
            items[0].status = 'AVAILABLE'

    def test_actual_executable_bytes_are_hashed_without_launch(self):
        from input_simulator.tools import _executable
        value = _executable(sys.executable)
        self.assertTrue(value.present)
        self.assertEqual(value.sha256, hashlib.sha256(Path(value.location).read_bytes()).hexdigest())
        self.assertIsNone(value.version)
        self.assertFalse(_executable(str(Path(sys.executable).parent / 'not-installed-tool')).present)

    def test_catalogue_changes_or_missing_duplicate_unknown_branches_are_rejected(self):
        import copy
        for mutate in (lambda c: c['toolchains'].pop(),
                       lambda c: c['toolchains'].append(c['toolchains'][0]),
                       lambda c: c['toolchains'][0].update(id='OTHER'),
                       lambda c: c['toolchains'][0].update(role='OBSERVE'),
                       lambda c: c['toolchains'][0]['tools'].clear()):
            original = self.contract.catalogue
            changed = copy.deepcopy(original)
            mutate(changed)
            self.contract._catalogue = changed
            try:
                self.rejects('HASH', lambda: self.Inventory(self.contract))
            finally:
                self.contract._catalogue = original

    def test_shadow_module_cannot_inherit_installed_distribution_version_or_execute(self):
        with tempfile.TemporaryDirectory() as td:
            marker = Path(td) / 'executed'
            (Path(td) / 'cantools.py').write_text("raise RuntimeError('must not import')", encoding='utf-8')
            previous = sys.modules.pop('cantools', None)
            sys.path.insert(0, td)
            try:
                evidence = self.Inventory(self.contract).inspect()[0].evidence[0]
                self.assertFalse(evidence.present)
                self.assertIsNone(evidence.version)
                self.assertNotIn('cantools', sys.modules)
                self.assertFalse(marker.exists())
            finally:
                sys.path.remove(td)
                if previous is not None:
                    sys.modules['cantools'] = previous

    def test_observer_never_holds_sender_reservation(self):
        b = self.Book()
        observer = b.reserve('watch', 'SAVVY', ('can0',), mode='OBSERVE')
        send = b.reserve('send', 'CANT', ('can0',), mode='SEND')
        self.assertFalse(observer.authorized_to_transmit)
        self.assertFalse(send.authorized_to_transmit)
        self.assertEqual(b.reservations, (observer, send))
        b.release(observer)
        self.rejects('STATE', lambda: b.reserve('next', 'CANREPLAY', ('can0',), mode='SEND'))
        b.release(send)
        self.assertEqual(b.reservations, ())

    def test_multichannel_conflict_is_atomic_across_branches(self):
        b = self.Book()
        first = b.reserve('first', 'CUTIL', ('can0',), mode='SEND')
        self.rejects('STATE', lambda: b.reserve('blocked', 'CANREPLAY', ('can1', 'can0'), mode='SEND'))
        second = b.reserve('free', 'CANT', ('can1',), mode='SEND')
        self.assertEqual(b.reservations, (first, second))
        b.release(first)
        self.rejects('STATE', lambda: b.reserve('third', 'CANREPLAY', ('can1',), mode='SEND'))
        b.release(second)

    def test_tokens_are_opaque_and_release_is_not_by_equal_fields(self):
        b, other = self.Book(), self.Book()
        token = b.reserve('run', 'ETHGEN', ('eth0',), mode='SEND')
        self.rejects('STATE', lambda: b.release(replace(token)))
        self.rejects('STATE', lambda: other.release(token))
        b.release(token)
        replacement = b.reserve('run', 'ETHGEN', ('eth0',), mode='SEND')
        self.rejects('STATE', lambda: b.release(token))
        self.assertEqual(b.reservations, (replacement,))
        b.release(replacement)

    def test_capacity_and_duplicate_run_cannot_evict_active_owner(self):
        b = self.Book(capacity=1)
        token = b.reserve('run', 'CANT', ('can0',), mode='SEND')
        self.rejects('STATE', lambda: b.reserve('run', 'CUTIL', ('can1',), mode='OBSERVE'))
        self.rejects('BUFFER_FULL', lambda: b.reserve('other', 'CUTIL', ('can1',), mode='OBSERVE'))
        self.assertEqual(b.reservations, (token,))
        b.release(token)

    def test_strict_ids_interfaces_modes_and_limits(self):
        for cap in (True, 0, 65, 1.0):
            self.rejects('CAPACITY', lambda: self.Book(capacity=cap))
        b = self.Book()
        for args in (('', 'CANT', ('can0',), 'SEND'),
                     ('run', 'OTHER', ('can0',), 'SEND'),
                     ('run', 'CANT', ['can0'], 'SEND'),
                     ('run', 'CANT', (), 'SEND'),
                     ('run', 'CANT', ('can0', 'can0'), 'SEND'),
                     ('run', 'CANT', ('can0;evil',), 'SEND'),
                     ('run', 'CANT', ('can0',), 'PROBE')):
            self.rejects('SCHEMA', lambda: b.reserve(*args[:3], mode=args[3]))
        self.assertEqual(b.reservations, ())


if __name__ == '__main__':
    unittest.main()

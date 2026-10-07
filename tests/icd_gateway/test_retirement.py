from dataclasses import replace

from common import GatewayTest, message
from test_model_bindings import declared_runtime


class RetirementTests(GatewayTest):
    def create(self, **receiver_options):
        from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
        from icd_gateway.model_bindings import ModelBindings
        from icd_gateway.model_queue import ModelQueue
        from icd_gateway.receiver import Receiver
        self.links = [PeerBinding("ETH_0", "UDP", f"127.0.0.1:{36300+i}") for i in range(2)]
        self.opens = [message(1), message(1)]
        for index, opening in enumerate(self.opens):
            opening["payload"]["identity"]["source_id"] = f"retirement-{index}"
            opening["payload"]["nonce_hex"] = f"{index:032x}"
        grants = [SourceGrant(o["payload"]["identity"], ("STIMULUS",), (link,))
                  for o, link in zip(self.opens, self.links)]
        self.registry = SessionRegistry(self.contract, grants)
        self.receiver = Receiver(self.contract, self.registry, **receiver_options)
        self.sids = [self.deliver(o, index=i)[0]["payload"]["session_id"]
                     for i, o in enumerate(self.opens)]
        mapping = ModelBindings(self.contract, "quadrotor_hil", declared_runtime(self.contract, "quadrotor_hil"))
        self.queue = ModelQueue(self.contract, self.registry, [mapping])

    def deliver(self, value, *, index=0, now=0):
        replies = ()
        for packet in self.receiver.wire.encode(value, "UDP"):
            replies = self.receiver.receive(packet, self.links[index], now_ns=now)
        return replies

    def pending(self, *, index=0, mid=10, sequence=2, target=5, now=0):
        value = message(mid)
        value["header"].update(session_id=self.sids[index], sequence=sequence,
                               transaction_id=sequence, target_step=target)
        self.registry.accept(value, self.links[index], now_ns=now)
        return self.queue.enqueue(value, state="RUNNING", now_ns=now), value

    def test_retirement_releases_only_its_owned_queue_and_retains_original_input(self):
        self.create()
        pending, value = self.pending()
        other, _ = self.pending(index=1, mid=11)
        self.assertEqual(self.registry.retire(self.sids[0]), (pending,))
        self.assertEqual(self.queue.count, 1)
        self.assertIn(self.sids[1], self.registry.session_ids)
        self.rejects("STALE_SESSION", lambda: self.registry.require_admitted(value, now_ns=0))
        self.assertEqual(self.registry.retire(self.sids[0]), ())
        self.assertEqual(self.registry.retire(self.sids[1]), (other,))
        self.assertEqual(self.queue.stored_bytes, 0)

    def test_retirement_identity_is_strict_and_cannot_delete_another_session(self):
        self.create()
        self.pending()
        for sid in (True, False, 0, -1, 2**32, float(self.sids[0]), str(self.sids[0]), None):
            self.rejects("SCHEMA", lambda sid=sid: self.registry.retire(sid))
        self.assertEqual(self.registry.active_count, 2)
        self.assertEqual(self.queue.count, 1)
        self.assertEqual(self.registry.retire(0xffffffff), ())

    def test_retired_feedback_is_retained_but_cannot_admit_retry_or_open_again(self):
        self.create()
        value = message(3)
        value["header"].update(session_id=self.sids[0], sequence=2)
        replies = self.deliver(value)
        cache_count = self.registry.cache_count
        self.registry.retire(self.sids[0])
        self.assertEqual(self.registry.cache_count, cache_count)
        self.rejects("STALE_SESSION", lambda: self.deliver(value))
        reply = self.deliver(self.opens[0])[0]
        self.assertEqual(reply["payload"]["error"], "STALE_SESSION")
        self.assertEqual(self.registry.active_count, 1)
        self.assertEqual(replies[-1]["payload"]["stage"], "FAILED")

    def test_registry_shutdown_returns_discarded_inputs_and_is_permanent(self):
        self.create()
        pending, _ = self.pending()
        self.assertEqual(self.registry.close(), (pending,))
        self.assertEqual(self.registry.close(), ())
        self.assertEqual(self.registry.active_count, 0)
        self.assertEqual(self.registry.cache_count, 0)
        opening = message(1)
        opening["payload"]["identity"] = self.opens[0]["payload"]["identity"]
        self.rejects("STATE", lambda: self.registry.accept(opening, self.links[0], now_ns=0))
        self.rejects("STATE", lambda: self.registry.retire(self.sids[0]))
        self.rejects("STATE", lambda: self.registry.expire_model_inputs(now_ns=0))

    def test_idle_queue_maintenance_preserves_original_rejections_and_other_session(self):
        self.create()
        pending, _ = self.pending()
        self.registry.revoke(self.sids[0])
        rejected = self.registry.expire_model_inputs(now_ns=0)
        self.assertEqual([(r.pending, r.error) for r in rejected], [(pending, "STALE_SESSION")])
        self.assertEqual(self.registry.expire_model_inputs(now_ns=0), ())
        self.assertIn(self.sids[1], self.registry.session_ids)
        replacement, _ = self.pending(index=1)
        self.assertEqual(self.queue.count, 1)
        self.assertNotEqual(pending.key, replacement.key)

    def partial(self, *, index=0):
        value = message(3)
        value["header"].update(session_id=self.sids[index], sequence=20)
        packets = self.receiver.wire.encode(value, "UDP")
        self.assertGreater(len(packets), 1)
        self.assertEqual(self.receiver.receive(packets[0], self.links[index], now_ns=0), ())
        return packets

    def test_receiver_retirement_releases_only_named_fragments_and_queue(self):
        self.create()
        pending, _ = self.pending()
        other, _ = self.pending(index=1, mid=11)
        self.partial()
        self.partial(index=1)
        self.assertEqual(self.receiver.assembler.pending_count, 2)
        self.assertEqual(self.receiver.retire_session(self.sids[0]), (pending,))
        self.assertEqual(self.receiver.assembler.pending_count, 1)
        self.assertEqual(self.queue.count, 1)
        self.assertEqual(self.receiver.retire_session(self.sids[0]), ())
        self.assertEqual(self.receiver.retire_session(self.sids[1]), (other,))
        self.assertEqual(self.receiver.assembler.reserved_bytes, 0)

    def test_receiver_idle_expiry_releases_queue_without_a_model_step(self):
        self.create()
        pending, _ = self.pending()
        heartbeat = message(2)
        heartbeat["header"].update(session_id=self.sids[1], sequence=2)
        self.registry.accept(heartbeat, self.links[1], now_ns=999_000_000)
        result = self.receiver.tick(now_ns=1_000_000_000)
        self.assertEqual(result.expired_sessions, (self.sids[0],))
        self.assertEqual([(r.pending, r.error) for r in result.rejected_inputs], [(pending, "STALE_SESSION")])
        self.assertEqual(self.queue.count, 0)
        self.assertEqual(self.queue.stored_bytes, 0)
        self.assertIn(self.sids[1], self.registry.session_ids)
        self.assertEqual(self.receiver.drain_maintenance(), result)
        self.assertEqual(self.receiver.tick(now_ns=1_000_000_000).rejected_inputs, ())
        with self.assertRaises(AttributeError):
            result.expired_sessions = ()
        fresh, _ = self.pending(index=1, sequence=3, now=1_000_000_000)
        self.assertEqual(self.queue.count, 1)
        self.assertEqual(fresh.target_step, 5)

    def test_idle_revoke_releases_fragments_even_without_pending_model_input(self):
        self.create()
        self.partial()
        self.partial(index=1)
        self.registry.revoke(self.sids[0])
        result = self.receiver.tick(now_ns=1)
        self.assertEqual(result.expired_sessions, ())
        self.assertEqual(result.rejected_inputs, ())
        self.assertEqual(self.receiver.assembler.pending_count, 1)
        self.assertIn(self.sids[1], self.registry.session_ids)

    def test_receiver_close_clears_revoked_fragments_and_returns_all_original_inputs(self):
        self.create()
        pending, _ = self.pending()
        self.partial()
        self.registry.revoke(self.sids[0])
        self.assertEqual(self.receiver.close(), (pending,))
        self.assertEqual(self.receiver.assembler.pending_count, 0)
        self.assertEqual(self.receiver.assembler.reserved_bytes, 0)
        self.assertEqual(self.receiver.close(), ())
        self.rejects("STATE", lambda: self.receiver.retire_session(self.sids[1]))
        self.rejects("STATE", lambda: self.receiver.tick(now_ns=1))

    def test_retirement_preserves_model_step_and_does_not_reclaim_old_admission(self):
        self.create()
        self.queue.begin_step("quadrotor_hil", 1, state="RUNNING", now_ns=0)
        pending, _ = self.pending(target=2)
        self.receiver.retire_session(self.sids[0])
        fresh, _ = self.pending(index=1, target=2)
        result = self.queue.begin_step("quadrotor_hil", 2, state="RUNNING", now_ns=0)
        self.assertEqual(result.ready, (fresh,))
        self.assertNotIn(pending, result.ready)
        self.rejects("OUT_OF_ORDER", lambda: self.queue.begin_step("quadrotor_hil", 1, state="RUNNING", now_ns=0))

    def test_wire_cleanup_without_consumers_is_failure_and_not_local_retirement(self):
        self.create()
        for mid in (37, 38):
            value = message(mid)
            value["header"].update(session_id=self.sids[0], sequence=mid)
            replies = self.deliver(value)
            self.assertEqual([r["payload"]["stage"] for r in replies], ["RECEIVED", "FAILED"])
            self.assertEqual(replies[-1]["payload"]["error"], "TARGET_MISSING" if mid == 37 else "UNSUPPORTED")
            self.assertTrue(all(r["payload"]["probe_id"] == 0 for r in replies))
            self.assertIn(self.sids[0], self.registry.session_ids)
        self.assertEqual(self.deliver(value), replies)

    def test_reassembler_inactive_filter_is_strict_and_clear_preserves_clock(self):
        self.create()
        self.partial()
        for live in ([self.sids[0]], (0,), (True,), (-1,), (2**32,), ("1",), None):
            self.rejects("SCHEMA", lambda live=live: self.receiver.assembler.discard_inactive_sessions(live))
        self.assertEqual(self.receiver.assembler.pending_count, 1)
        self.receiver.assembler.expire(now_ns=100_000_000)
        self.assertEqual(self.receiver.assembler.terminal_count, 1)
        self.receiver.assembler.clear()
        self.assertEqual(self.receiver.assembler.terminal_count, 0)
        self.assertEqual(self.receiver.assembler.reserved_bytes, 0)
        self.rejects("SCHEMA", lambda: self.receiver.assembler.expire(now_ns=0))

    def test_registry_without_model_queue_retirement_and_maintenance_still_work(self):
        from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
        opening = message(1)
        link = PeerBinding("ETH_0", "UDP", "127.0.0.1:36302")
        registry = SessionRegistry(self.contract, [SourceGrant(opening["payload"]["identity"], ("STIMULUS",), (link,))])
        sid = registry.accept(opening, link, now_ns=0).session_id
        self.assertEqual(registry.expire_model_inputs(now_ns=1), ())
        self.assertEqual(registry.retire(sid), ())
        self.assertEqual(registry.close(), ())

    def test_implicit_ingress_maintenance_keeps_original_rejection_until_drained(self):
        self.create()
        pending, _ = self.pending()
        heartbeat = message(2)
        heartbeat["header"].update(session_id=self.sids[1], sequence=2)
        self.registry.accept(heartbeat, self.links[1], now_ns=999_000_000)
        heartbeat["header"]["sequence"] = 3
        self.deliver(heartbeat, index=1, now=1_000_000_000)
        self.assertEqual(self.queue.count, 0)
        first = self.receiver.tick(now_ns=1_000_000_000)
        self.assertEqual(first.expired_sessions, (self.sids[0],))
        self.assertEqual([(r.pending, r.error) for r in first.rejected_inputs], [(pending, "STALE_SESSION")])
        self.assertEqual(self.receiver.tick(now_ns=1_000_000_000), first)
        self.assertEqual(self.receiver.drain_maintenance(), first)
        self.assertEqual(self.receiver.drain_maintenance().rejected_inputs, ())

    def test_failed_maintenance_clock_preflight_does_not_delete_any_resource(self):
        for component in ("assembler", "queue"):
            self.create()
            pending, _ = self.pending()
            if component == "assembler":
                self.receiver.assembler.expire(now_ns=2_000_000_000)
            else:
                self.queue.preview_expiry(self.registry.session_ids, now_ns=2_000_000_000)
                self.queue._clock(2_000_000_000)
            self.rejects("SCHEMA", lambda: self.receiver.tick(now_ns=1_000_000_000))
            self.assertEqual(self.registry.active_count, 2)
            self.assertEqual(self.queue.count, 1)
            result = self.receiver.tick(now_ns=2_000_000_000)
            self.assertEqual([(r.pending, r.error) for r in result.rejected_inputs], [(pending, "STALE_SESSION")])

    def test_maintenance_mailbox_full_refuses_deletion_until_prior_records_drained(self):
        self.create(maintenance_input_capacity=1)
        first, _ = self.pending()
        self.registry.revoke(self.sids[0])
        self.receiver.tick(now_ns=1)
        second, _ = self.pending(index=1, now=1)
        self.registry.revoke(self.sids[1])
        self.rejects("BUFFER_FULL", lambda: self.receiver.tick(now_ns=2))
        self.assertEqual(self.queue.count, 1)
        self.assertEqual(self.receiver.drain_maintenance().rejected_inputs[0].pending, first)
        self.assertEqual(self.receiver.tick(now_ns=2).rejected_inputs[0].pending, second)
        self.assertEqual(self.queue.count, 0)

    def test_shutdown_inputs_survive_implicit_close_and_can_be_drained_once(self):
        self.create()
        pending, _ = self.pending()
        self.receiver.close()
        closed = self.receiver.drain_shutdown()
        self.assertEqual(closed.closed_sessions, tuple(self.sids))
        self.assertEqual(closed.discarded_inputs, (pending,))
        self.assertEqual(self.receiver.drain_shutdown().discarded_inputs, ())
        with self.assertRaises(AttributeError):
            closed.discarded_inputs = ()

    def test_maintenance_preview_is_read_only_and_its_sessions_are_strict(self):
        self.create()
        pending, _ = self.pending()
        expired, rejected = self.registry.preview_maintenance(now_ns=2_000_000_000)
        self.assertEqual(expired, tuple(self.sids))
        self.assertEqual(rejected[0].pending, pending)
        self.assertEqual(self.registry.active_count, 2)
        self.assertEqual(self.queue.count, 1)
        self.assertEqual(self.receiver.tick(now_ns=0).expired_sessions, ())
        for live in ([self.sids[0]], (0,), (True,), (2**32,), None):
            self.rejects("SCHEMA", lambda live=live: self.queue.preview_expiry(live, now_ns=0))
        self.assertEqual(self.queue.count, 1)

    def test_maintenance_capacity_is_local_strict_and_cannot_expand_protocol_limits(self):
        self.create()
        from icd_gateway.receiver import Receiver
        for capacity in (True, 0, -1, 4097, 1.0, "1", None):
            self.rejects("CAPACITY", lambda capacity=capacity: Receiver(
                self.contract, self.registry, maintenance_input_capacity=capacity))
        self.assertEqual(self.registry.active_count, 2)

    def test_shutdown_keeps_prior_maintenance_separate_from_remaining_queue(self):
        self.create()
        expired, _ = self.pending()
        self.registry.revoke(self.sids[0])
        self.receiver.tick(now_ns=1)
        remaining, _ = self.pending(index=1, now=1)
        self.receiver.close()
        self.assertEqual(self.receiver.drain_maintenance().rejected_inputs[0].pending, expired)
        shutdown = self.receiver.drain_shutdown()
        self.assertEqual(shutdown.closed_sessions, (self.sids[1],))
        self.assertEqual(shutdown.discarded_inputs, (remaining,))

    def test_inactive_cleanup_preserves_pending_pre_session_zero_until_shutdown(self):
        self.create()
        opening = message(1)
        for field in ("run_id", "source_id", "vehicle_id", "scenario_id"):
            opening["payload"]["identity"][field] = "\u4e2d" * 128
        packets = self.receiver.wire.encode(opening, "UDP")
        self.assertGreater(len(packets), 1)
        self.receiver.receive(packets[0], self.links[0], now_ns=0)
        self.receiver.assembler.discard_inactive_sessions(())
        self.assertEqual(self.receiver.assembler.pending_count, 1)
        self.receiver.close()
        self.assertEqual(self.receiver.assembler.reserved_bytes, 0)


class CleanupGuardTests(GatewayTest):
    def create(self):
        from icd_gateway.semantic_guards import SemanticGuards, ModelView
        self.guards = SemanticGuards(self.contract)
        self.view = ModelView("quadrotor_hil", "PAUSED", 10, 600000, "NONE", False, True)

    def cleanup(self, mid=37):
        value = message(mid)
        value["header"]["target_step"] = 10
        return value

    def test_both_messages_require_all_nine_operations_and_no_success_is_claimed(self):
        self.create()
        fields = set(message(37)["payload"])
        self.assertEqual(len(fields), 9)
        for mid in (37, 38):
            value = self.cleanup(mid)
            decision = self.guards.cleanup(value, self.view)
            self.assertEqual(set(decision.operations), fields)
            self.assertEqual(len(decision.operations), 9)
            self.assertEqual(decision.session_id, value["header"]["session_id"])
            self.assertEqual(decision.target_step, 10)
            self.assertEqual(decision.reason, "NORMAL" if mid == 38 else None)
            self.assertFalse(hasattr(decision, "applied_step"))
            self.assertFalse(hasattr(decision, "probe_id"))
            with self.assertRaises(AttributeError):
                decision.operations = ()
            value["payload"].clear()
            self.assertEqual(set(decision.operations), fields)

    def test_false_missing_extra_and_non_boolean_cleanup_fields_are_rejected(self):
        self.create()
        for mid in (37, 38):
            for field in message(37)["payload"]:
                for invalid in (False, 1, None, "true", "MISSING"):
                    value = self.cleanup(mid)
                    payload = value["payload"] if mid == 37 else value["payload"]["cleanup"]
                    if invalid == "MISSING":
                        del payload[field]
                    else:
                        payload[field] = invalid
                    self.rejects("SCHEMA", lambda value=value: self.guards.cleanup(value, self.view))
            value = self.cleanup(mid)
            payload = value["payload"] if mid == 37 else value["payload"]["cleanup"]
            payload["partial_success"] = True
            self.rejects("SCHEMA", lambda: self.guards.cleanup(value, self.view))

    def test_cleanup_accepts_safety_boundary_in_all_states_including_failed(self):
        self.create()
        for state in ("CONFIGURED", "PAUSED", "STOPPED", "FAILED", "RUNNING"):
            for mid in (37, 38):
                value = self.cleanup(mid)
                value["header"]["target_step"] = 11 if state == "RUNNING" else 10
                decision = self.guards.cleanup(value, replace(self.view, state=state, configured_once=False))
                self.assertEqual(len(decision.operations), 9)

    def test_model_cleanup_running_and_frozen_targets_obey_actual_boundary(self):
        self.create()
        value = self.cleanup()
        running = replace(self.view, state="RUNNING")
        self.rejects("LATE", lambda: self.guards.cleanup(value, running))
        value["header"]["target_step"] = 1011
        self.rejects("RANGE", lambda: self.guards.cleanup(value, running))
        value["header"]["target_step"] = 11
        self.rejects("STATE", lambda: self.guards.cleanup(value, self.view))
        value["header"]["target_step"] = 1010
        self.assertEqual(self.guards.cleanup(value, running).target_step, 1010)
        self.rejects("RANGE", lambda: self.guards.cleanup(value, replace(running, max_duration_steps=1000)))

    def test_session_close_uses_actual_service_boundary_not_future_or_late_header_target(self):
        self.create()
        self.assertEqual(self.contract.entry(38)["application"], "SERVICE_BOUNDARY")
        for state in ("RUNNING", "PAUSED", "FAILED"):
            view = replace(self.view, state=state)
            for target in (0, 10, 1011, 600001):
                value = self.cleanup(38)
                value["header"]["target_step"] = target
                self.assertEqual(self.guards.cleanup(value, view).target_step, view.model_step)

    def test_session_close_preserves_each_explicit_reason_and_rejects_other_messages(self):
        self.create()
        for reason in ("NORMAL", "ABORT", "RESET", "REPLACE_SOURCE"):
            value = self.cleanup(38)
            value["payload"]["reason"] = reason
            self.assertEqual(self.guards.cleanup(value, self.view).reason, reason)
        self.rejects("UNSUPPORTED", lambda: self.guards.cleanup(message(3), self.view))
        self.rejects("SCHEMA", lambda: self.guards.cleanup({}, self.view))
        self.rejects("TARGET_MISSING", lambda: self.guards.cleanup(self.cleanup(), None))
        self.rejects("MODEL", lambda: self.guards.cleanup(self.cleanup(), replace(self.view, model_id="absent")))


if __name__ == "__main__":
    import unittest
    unittest.main()

import hashlib
import importlib.util

from common import GatewayTest, message
from test_model_bindings import declared_runtime


class QueueTests(GatewayTest):
    def create(self, *, second_writer=False):
        from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
        from icd_gateway.model_bindings import ModelBindings
        from icd_gateway.model_queue import ModelQueue
        models = ["quadrotor_hil", "multirotor_6_hil", "fixed_wing_hil"]
        if second_writer:
            models.append("quadrotor_hil")
        grants, opens = [], []
        self.links = []
        for index, model in enumerate(models):
            link = PeerBinding("ETH_0", "UDP", f"127.0.0.1:{36200 + index}")
            value = message(1)
            value["payload"]["identity"].update(model_id=model, source_id=f"source-{index}")
            value["payload"].update(roles=["STIMULUS", "CONTROLLER"], nonce_hex=f"{index:032x}")
            self.links.append(link)
            grants.append(SourceGrant(value["payload"]["identity"], ("STIMULUS", "CONTROLLER"), (link,)))
            opens.append(value)
        self.registry = SessionRegistry(self.contract, grants)
        self.sids = [self.registry.accept(value, link, now_ns=0).session_id
                     for value, link in zip(opens, self.links)]
        self.sequence = [1] * len(models)
        mappings = [ModelBindings(self.contract, model, declared_runtime(self.contract, model))
                    for model in models[:3]]
        self.queue = ModelQueue(self.contract, self.registry, mappings)

    def admitted(self, mid=10, *, step=1, index=0, now=0, transaction=None):
        value = message(mid)
        self.sequence[index] += 1
        value["header"].update(session_id=self.sids[index], sequence=self.sequence[index],
                               target_step=step, transaction_id=transaction or self.sequence[index])
        self.registry.accept(value, self.links[index], now_ns=now)
        return value

    def enqueue(self, value, now=0, **kwargs):
        return self.queue.enqueue(value, state="RUNNING", now_ns=now, **kwargs)

    def step(self, step=1, now=1_000_000, model="quadrotor_hil"):
        return self.queue.begin_step(model, step, state="RUNNING", now_ns=now)

    def test_model_queue_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("icd_gateway.model_queue"))

    def test_original_admission_receiving_time_not_retry_time_is_returned(self):
        self.create()
        value = self.admitted(now=123)
        self.assertEqual(self.registry.require_admitted(value, now_ns=999), 123)
        changed = message(10)
        changed["header"] = value["header"].copy()
        changed["payload"]["wind_n_mps"] = 1
        self.rejects("DUPLICATE", lambda: self.registry.require_admitted(changed, now_ns=999))
        unknown = message(10)
        unknown["header"].update(session_id=self.sids[0], sequence=500)
        self.rejects("OUT_OF_ORDER", lambda: self.registry.require_admitted(unknown, now_ns=999))
        self.registry.revoke(self.sids[0])
        self.rejects("STALE_SESSION", lambda: self.registry.require_admitted(value, now_ns=999))

    def test_failed_admission_cannot_be_queued(self):
        self.create()
        value = self.admitted()
        reply = message(130)
        reply["header"].update(session_id=self.sids[0], transaction_id=value["header"]["transaction_id"])
        reply["payload"].update(stage="FAILED", error="TARGET_MISSING", probe_id=0,
                                request_message_id=10, request_sequence=value["header"]["sequence"])
        self.registry.record_response(value, (reply,), now_ns=0)
        self.rejects("STATE", lambda: self.enqueue(value))
        self.assertEqual(self.queue.count, 0)

    def test_pending_is_immutable_full_message_and_is_not_application_evidence(self):
        self.create()
        value = self.admitted(mid=11)
        pending = self.enqueue(value)
        original = pending.message_json
        value["payload"]["motor_1_failed"] = True
        self.assertEqual(pending.message_json, original)
        self.assertEqual(pending.sha256, hashlib.sha256(original).hexdigest())
        self.assertEqual(pending.key, (self.sids[0], 2))
        self.assertEqual(len(pending.values), len(message(11)["payload"]))
        self.assertFalse(hasattr(pending, "probe_id"))
        self.assertFalse(hasattr(pending, "applied_step"))
        batch = self.step()
        self.assertEqual(batch.ready, (pending,))
        self.assertEqual(batch.rejected, ())
        self.assertEqual(self.queue.count, 0)
        self.assertEqual(self.queue.stored_bytes, 0)
        with self.assertRaises(AttributeError):
            pending.target_step = 2

    def test_queue_capacity_is_4096_globally_without_overwrite(self):
        self.create()
        first = None
        for index, mids in ((0, (10, 11, 17)), (1, (10, 12))):
            for mid in mids:
                for step in range(1, 1001):
                    value = self.admitted(mid=mid, step=step, index=index)
                    if self.queue.count == 4096:
                        self.rejects("BUFFER_FULL", lambda: self.enqueue(value))
                        self.assertGreater(self.queue.stored_bytes, 0)
                        self.assertEqual(self.queue.count, 4096)
                        batch = self.step()
                        self.assertEqual(batch.ready[0], first)
                        return
                    pending = self.enqueue(value)
                    if first is None:
                        first = pending
        self.fail("did not exercise the frozen4096-message bound")

    def test_target_ahead_late_and_run_duration_bounds(self):
        self.create()
        for step, code in ((0, "LATE"), (1001, "RANGE"), (86400001, "RANGE")):
            value = self.admitted(step=step)
            self.rejects(code, lambda value=value: self.enqueue(value))
        self.enqueue(self.admitted(step=1000))
        self.step()
        self.rejects("LATE", lambda: self.enqueue(self.admitted(step=1, now=1_000_000), now=1_000_000))

    def test_paused_and_service_consumers_cannot_enter_running_model_queue(self):
        self.create()
        value = self.admitted()
        for state in ("PAUSED", "CONFIGURED", "STOPPED", "unknown"):
            self.rejects("STATE", lambda state=state: self.queue.enqueue(value, state=state, now_ns=0))
        for mid in (3, 5, 24, 25, 39, 45):
            value = self.admitted(mid=mid)
            self.rejects("TARGET_MISSING", lambda value=value: self.enqueue(value))

    def test_only_exact_next_step_can_release_no_late_catchup(self):
        self.create()
        pending = self.enqueue(self.admitted(step=2))
        for step in (0, 2, 1000):
            self.rejects("OUT_OF_ORDER", lambda step=step: self.step(step, now=0))
        self.assertEqual(self.step().ready, ())
        self.assertEqual(self.step(2, now=2_000_000).ready, (pending,))
        self.rejects("OUT_OF_ORDER", lambda: self.step(2, now=2_000_000))

    def test_same_target_overlap_is_rejected_not_last_write_wins(self):
        self.create()
        first = self.enqueue(self.admitted(transaction=7))
        second = self.admitted(transaction=7)
        self.rejects("CONTROL_OWNER", lambda: self.enqueue(second))
        self.assertEqual(self.queue.count, 1)
        fault = self.enqueue(self.admitted(mid=11, transaction=7))
        self.assertEqual(self.step().ready, (first, fault))

    def test_lane_alias_cannot_be_enabled_concurrently(self):
        self.create()
        self.enqueue(self.admitted(mid=7), control_source="PX4_SITL", input_lane="FLIGHT_CONTROL")
        value = self.admitted(mid=14, step=2)
        self.rejects("CONTROL_OWNER", lambda: self.enqueue(value, control_source="PX4_SITL", input_lane="ACTUATOR"))
        self.assertEqual(self.queue.count, 1)

    def test_cross_session_writer_conflict_and_whole_snapshot_rollback(self):
        self.create(second_writer=True)
        first = self.enqueue(self.admitted())
        conflict = self.admitted(index=3, step=2)
        self.rejects("CONTROL_OWNER", lambda: self.enqueue(conflict))
        self.assertEqual(self.queue.count, 1)
        self.assertEqual(self.queue.discard_session(self.sids[0]), (first,))
        self.assertEqual(self.enqueue(conflict).key[0], self.sids[3])

    def test_controller_source_lane_model_and_stimulus_metadata_are_strict(self):
        self.create()
        value = self.admitted(mid=7)
        for source, lane in ((None, None), ("NONE", "FLIGHT_CONTROL"), ("PX4_SITL", "ACTUATOR"),
                             ("PX4_SITL", "INTERNAL_CONTROLLER"), ("unknown", "FLIGHT_CONTROL")):
            self.rejects("CONTROL_OWNER", lambda source=source, lane=lane:
                         self.enqueue(value, control_source=source, input_lane=lane))
        hex_value = self.admitted(mid=8, index=1)
        self.rejects("CONTROL_OWNER", lambda: self.enqueue(hex_value, control_source="DEMO_MISSION", input_lane="FLIGHT_CONTROL"))
        stimulus = self.admitted()
        self.rejects("CONTROL_OWNER", lambda: self.enqueue(stimulus, control_source="PX4_SITL", input_lane="ACTUATOR"))
        self.assertEqual(self.queue.count, 0)

    def test_100ms_control_age_uses_first_receive_even_with_fresh_heartbeat(self):
        self.create()
        value = self.admitted(mid=7)
        pending = self.enqueue(value, now=99_000_000, control_source="PX4_SITL", input_lane="FLIGHT_CONTROL")
        self.admitted(mid=2, now=99_000_000)
        batch = self.step(now=100_000_000)
        self.assertEqual(batch.ready, ())
        self.assertEqual([(r.pending, r.error) for r in batch.rejected], [(pending, "EXPIRED")])
        self.assertIn(self.sids[0], self.registry.session_ids)

    def test_control_age_below_deadline_can_release_but_no_safety_is_claimed(self):
        self.create()
        pending = self.enqueue(self.admitted(mid=14), control_source="PHYSICAL_UUT", input_lane="ACTUATOR")
        self.assertEqual(self.step(now=99_999_999).ready, (pending,))
        self.assertFalse(hasattr(self.queue, "actuator_safe"))

    def test_expired_before_enqueue_control_is_not_reserved(self):
        self.create()
        value = self.admitted(mid=7)
        self.rejects("EXPIRED", lambda: self.enqueue(value, now=100_000_000, control_source="PX4_SITL", input_lane="FLIGHT_CONTROL"))
        self.assertEqual(self.queue.count, 0)

    def test_session_expiry_and_external_revoke_purge_pending_inputs(self):
        for expired in (False, True):
            self.create()
            pending = self.enqueue(self.admitted())
            now = 1_000_000_000 if expired else 0
            if not expired:
                self.registry.revoke(self.sids[0])
            batch = self.step(now=now)
            self.assertEqual(batch.ready, ())
            self.assertEqual([(r.pending, r.error) for r in batch.rejected], [(pending, "STALE_SESSION")])
            self.assertEqual(self.queue.count, 0)

    def test_duplicate_or_cleared_admission_cannot_enter_queue_twice(self):
        self.create()
        value = self.admitted(step=2)
        pending = self.enqueue(value)
        self.rejects("DUPLICATE", lambda: self.enqueue(value))
        self.assertEqual(self.queue.clear(), (pending,))
        self.rejects("DUPLICATE", lambda: self.enqueue(value))
        fresh = self.admitted(step=2)
        self.enqueue(fresh)

    def test_clear_preserves_model_step_close_refuses_use_and_clocks_do_not_rewind(self):
        self.create()
        self.step()
        pending = self.enqueue(self.admitted(step=2, now=1_000_000), now=1_000_000)
        self.rejects("SCHEMA", lambda: self.step(2, now=0))
        self.assertEqual(self.queue.clear(), (pending,))
        self.rejects("LATE", lambda: self.enqueue(self.admitted(step=1, now=1_000_000), now=1_000_000))
        self.queue.close()
        self.assertEqual(self.queue.count, 0)
        self.assertEqual(self.queue.stored_bytes, 0)
        self.rejects("STATE", lambda: self.step(2, now=1_000_000))
        self.rejects("STATE", lambda: self.enqueue(message(10), now=1_000_000))

    def test_wrong_registry_model_and_unadmitted_input_are_not_queued(self):
        self.create()
        value = message(10)
        value["header"].update(session_id=self.sids[0], sequence=500, target_step=1)
        self.rejects("OUT_OF_ORDER", lambda: self.enqueue(value))
        value = self.admitted()
        value["payload"]["wind_n_mps"] = 0.2
        self.rejects("DUPLICATE", lambda: self.enqueue(value))
        value = self.admitted(mid=7)
        value["message_id"] = 8
        value["payload"]["motor_command"] += [0, 0]
        self.rejects("MODEL", lambda: self.enqueue(value, control_source="PX4_SITL", input_lane="FLIGHT_CONTROL"))

    def test_registry_has_one_global_queue_even_for_disjoint_model_sets(self):
        self.create()
        from icd_gateway.model_bindings import ModelBindings
        from icd_gateway.model_queue import ModelQueue
        mappings = [ModelBindings(self.contract, "quadrotor_hil", declared_runtime(self.contract, "quadrotor_hil"))]
        self.rejects("STATE", lambda: ModelQueue(self.contract, self.registry, mappings))
        value = self.admitted()
        self.enqueue(value)
        self.queue.close()
        self.rejects("STATE", lambda: ModelQueue(self.contract, self.registry, mappings))

    def test_closed_queue_cannot_reset_step_history_for_still_live_sessions(self):
        self.create()
        from icd_gateway.model_bindings import ModelBindings
        from icd_gateway.model_queue import ModelQueue
        self.step()
        self.queue.close()
        mappings = [ModelBindings(self.contract, "quadrotor_hil", declared_runtime(self.contract, "quadrotor_hil"))]
        self.rejects("STATE", lambda: ModelQueue(self.contract, self.registry, mappings))
        self.assertIn(self.sids[0], self.registry.session_ids)

    def test_registry_shutdown_also_closes_its_owned_queue(self):
        self.create()
        self.enqueue(self.admitted())
        self.registry.close()
        self.assertEqual(self.queue.count, 0)
        self.assertEqual(self.queue.stored_bytes, 0)
        self.rejects("STATE", lambda: self.step(now=0))

    def test_idle_expiry_returns_rejections_and_removes_writer_reservations(self):
        self.create(second_writer=True)
        pending = self.enqueue(self.admitted(step=1000))
        self.registry.revoke(self.sids[0])
        rejections = self.queue.expire(now_ns=0)
        self.assertEqual([(r.pending, r.error) for r in rejections], [(pending, "STALE_SESSION")])
        self.assertEqual(self.queue.stored_bytes, 0)
        self.enqueue(self.admitted(index=3, step=1000))

    def test_missing_or_duplicate_model_mapping_refuses_construction(self):
        self.create()
        from icd_gateway.model_bindings import ModelBindings
        from icd_gateway.model_queue import ModelQueue
        mapping = ModelBindings(self.contract, "quadrotor_hil", declared_runtime(self.contract, "quadrotor_hil"))
        self.rejects("MODEL", lambda: ModelQueue(self.contract, self.registry, []))
        self.rejects("MODEL", lambda: ModelQueue(self.contract, self.registry, [mapping, mapping]))

    def test_invalid_boundary_state_model_range_and_clock_never_release(self):
        self.create()
        self.enqueue(self.admitted())
        for step in (True, 1.0, -1, 86400001):
            self.rejects("RANGE", lambda step=step: self.step(step, now=0))
        self.rejects("MODEL", lambda: self.step(model="unknown", now=0))
        self.rejects("STATE", lambda: self.queue.begin_step("quadrotor_hil", 1, state="PAUSED", now_ns=0))
        for now in (True, -1, 1.0):
            self.rejects("SCHEMA", lambda now=now: self.step(now=now))
        self.assertEqual(self.queue.count, 1)

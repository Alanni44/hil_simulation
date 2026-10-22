#!/usr/bin/env python3
"""Serialized model lifecycle used by the Spring V0.3 business endpoint.

The WebSocket receipt means a lifecycle request was accepted.  Starting and
stopping the model remains local work, deliberately separate from that receipt.
"""
from __future__ import absolute_import

import os
import secrets
import subprocess
import threading
import time

from config_loader import CONFIG
from core_client import core_request
from mission_file import load_mission
from shared import state_cache
from shared.logger import get_logger

logger = get_logger('model_runtime')
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ModelRuntime(object):
    def __init__(self, settings=None, request_core=None, popen=None):
        self.settings = dict(settings if settings is not None else CONFIG.get('model_runtime', {}))
        self.request_core = request_core or core_request
        self.popen = popen or subprocess.Popen
        self._lock = threading.Lock()
        self._operation_lock = threading.Lock()
        self._process = None
        self._verified_executable = None
        self._state = 'STOPPED'

    def register_deployed(self, executable, process=None):
        """Adopt the executable verified by the separate management boundary."""
        with self._lock:
            self._verified_executable = executable
            self._process = process
            self._state = 'RUNNING' if process is not None and process.poll() is None else 'STOPPED'

    def request(self, action):
        """Atomically decide whether an action can be accepted."""
        with self._lock:
            if action == 'START':
                if self._state != 'STOPPED':
                    return False, 'model is {}'.format(self._state.lower())
                reason = self._start_precondition()
                if reason:
                    return False, reason
                self._state = 'STARTING'
                return True, 'accepted'
            if action == 'STOP':
                # START has not completed its controller/mission handoff.  A
                # caller can retry after it receives state data; this avoids a
                # STOP racing an unowned process.
                if self._state == 'STARTING':
                    return False, 'model startup is in progress; retry STOP when running'
                if self._state != 'RUNNING':
                    return False, 'model is not running'
                self._state = 'STOPPING'
                return True, 'accepted'
        return False, 'unsupported action'

    def execute(self, action):
        """Perform previously accepted work; failures are retained in logs."""
        with self._operation_lock:
            try:
                if action == 'START':
                    self._start()
                else:
                    self._stop()
            except Exception as exc:
                logger.exception('%s failed', action)
                with self._lock:
                    self._state = 'STOPPED'
                self._cleanup_process()
                return False, str(exc)
        return True, 'completed'

    def state(self):
        with self._lock:
            return self._state

    def _start_precondition(self):
        if self.settings.get('control_mode', 'builtin_mission') != 'builtin_mission':
            return 'configured control_mode is unavailable'
        mode = self.settings.get('execution_mode', 'development')
        if mode == 'development':
            executable = self._executable_path()
            if not isinstance(executable, str) or not executable:
                return 'model_runtime.executable_path is not configured'
            executable = self._absolute(executable)
            if not os.path.isfile(executable) or not os.access(executable, os.X_OK):
                return 'configured model executable is unavailable'
        elif mode == 'systemd':
            unit = self.settings.get('systemd_unit')
            if not isinstance(unit, str) or not unit.endswith('.service') or '/' in unit:
                return 'model_runtime.systemd_unit is invalid'
        else:
            return 'configured execution_mode is unavailable'
        mission = self.settings.get('mission_path', 'missions/z_mission.json')
        try:
            load_mission(self._absolute(mission))
        except Exception as exc:
            return 'configured mission is invalid: {}'.format(exc)
        return None

    def _start(self):
        mission = load_mission(self._absolute(self.settings.get('mission_path', 'missions/z_mission.json')))
        state_cache.reset_for_new_run()
        if self.settings.get('execution_mode', 'development') == 'systemd':
            subprocess.check_call(['systemctl', 'start', self.settings['systemd_unit']])
            self._process = None
        else:
            executable = self._absolute(self._executable_path())
            log_path = self._absolute(self.settings.get('runtime_log', 'runtime/spring-model.log'))
            parent = os.path.dirname(log_path)
            if not os.path.isdir(parent):
                os.makedirs(parent)
            log = open(log_path, 'a')
            try:
                self._process = self.popen([executable], stdout=log, stderr=subprocess.STDOUT,
                                           close_fds=True, env=dict(os.environ, HIL_ALLOW_NONRT='1'))
            finally:
                log.close()
            if self._process.poll() is not None:
                raise RuntimeError('model process exited immediately')
        # A state packet is emitted only after the C core has created its
        # command worker.  Waiting for it avoids sending a UDP command during
        # the Popen-to-bind window, where datagrams are silently lost.
        self._wait_for_core_ready()
        status = self._require_core('get_hil_status', {})
        fields = status.get('fields') if isinstance(status, dict) else None
        if not isinstance(fields, dict):
            raise RuntimeError('C core did not return a HIL capability receipt')
        if (fields.get('initial_state_abi') is not True
                or fields.get('full_configuration_abi') is not True):
            raise RuntimeError('C core lacks the verified RunConfigure ABI')
        if fields.get('lifecycle') != 'CONFIGURED' or fields.get('control_source') != 'none':
            raise RuntimeError('C core must be CONFIGURED with no control source before START')
        # The first circle owns complete configuration.  This legacy Spring
        # execution path may only perform the second-circle transition; it
        # cannot initialise a model merely by launching its process.
        self._require_core('select_control_source', {'source': 'demo_mission'})
        self._require_core('load_mission', mission)
        self._require_core('start', {})
        self._wait_for_fresh_samples()
        with self._lock:
            self._state = 'RUNNING'

    def _stop(self):
        if self.settings.get('execution_mode', 'development') == 'systemd':
            subprocess.check_call(['systemctl', 'stop', self.settings['systemd_unit']])
            state_cache.reset_for_new_run()
            with self._lock:
                self._state = 'STOPPED'
            return
        process = self._process
        if process is None or process.poll() is not None:
            raise RuntimeError('managed model process is not running')
        process.terminate()
        try:
            process.wait(timeout=float(self.settings.get('stop_timeout_s', 10)))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        self._process = None
        state_cache.reset_for_new_run()
        with self._lock:
            self._state = 'STOPPED'

    def _require_core(self, cmd, params):
        attempts = int(self.settings.get('command_retry_attempts', 3))
        delay = float(self.settings.get('command_retry_delay_s', 0.1))
        if attempts < 1 or delay < 0:
            raise RuntimeError('command retry settings are invalid')
        request = {'request_id': 'spring-runtime-{}'.format(secrets.token_hex(12)),
                   'cmd': cmd, 'params': params}
        receipt = None
        for attempt in range(attempts):
            receipt = self.request_core(dict(request))
            if receipt.get('accepted'):
                return receipt
            # A semantic C-core rejection must not be retried.  Only retry a
            # missing local UDP receipt after the core-ready barrier.
            reason = str(receipt.get('reason', 'unknown reason'))
            if not reason.startswith('C core receipt failed') or attempt + 1 == attempts:
                break
            time.sleep(delay)
        raise RuntimeError('{} rejected: {}'.format(cmd, receipt.get('reason', 'unknown reason')))

    def _wait_for_core_ready(self):
        """Wait for one fresh source frame before issuing UDP control."""
        timeout = float(self.settings.get('core_ready_timeout_s', 3))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            sample = state_cache.get_normalized_state()
            if sample is not None and not state_cache.is_stale(
                    float(self.settings.get('state_max_age_s', 0.5))):
                return
            if (self.settings.get('execution_mode', 'development') != 'systemd'
                    and (self._process is None or self._process.poll() is not None)):
                raise RuntimeError('model process exited before command endpoint became ready')
            time.sleep(0.02)
        raise RuntimeError('timed out waiting for C-core command endpoint readiness')

    def _wait_for_fresh_samples(self):
        required = int(self.settings.get('ready_sample_count', 3))
        timeout = float(self.settings.get('startup_timeout_s', 20))
        if required < 1:
            raise RuntimeError('ready_sample_count must be positive')
        deadline = time.monotonic() + timeout
        prior = None
        count = 0
        while time.monotonic() < deadline:
            sample = state_cache.get_normalized_state()
            if sample and not state_cache.is_stale(float(self.settings.get('state_max_age_s', 0.5))):
                marker = (sample['sequence'], sample['sim_time_s'])
                if marker != prior:
                    count += 1
                    prior = marker
                    if count >= required:
                        return
            if (self.settings.get('execution_mode', 'development') != 'systemd'
                    and (self._process is None or self._process.poll() is not None)):
                raise RuntimeError('model process exited before publishing state')
            time.sleep(0.02)
        raise RuntimeError('timed out waiting for fresh model state')

    def _cleanup_process(self):
        if self.settings.get('execution_mode', 'development') == 'systemd':
            try:
                subprocess.call(['systemctl', 'stop', self.settings['systemd_unit']])
            except OSError:
                pass
            state_cache.reset_for_new_run()
            return
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        state_cache.reset_for_new_run()

    @staticmethod
    def _absolute(path):
        return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)

    def _executable_path(self):
        return self.settings.get('executable_path') or self._verified_executable or ''


# One process-wide owner prevents the management and Spring endpoints from
# independently starting a second model process.
MODEL_RUNTIME = ModelRuntime()

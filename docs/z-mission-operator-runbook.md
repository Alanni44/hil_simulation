# Real UE4 Z-Mission Operator Runbook

This workflow is for the Ubuntu 18.04 RT target running MATLAB R2018b
generated code, GCC 7.x, and Python 3.6.9. It starts the explicit model
executable first and then `python_services/debug_main.py`. It does not start
`python_services/main.py` or any WebSocket service.

## 1. Local deterministic protocol check

From the repository root on any development machine:

```bash
python3 scripts/mini_ue4_sim.py --self-test
```

Success prints `LOCAL SIMULATOR PASSED` and writes the ignored transcript to
`runtime/z_debug/mini_ue4_transcript.json`. This checks the strict local
fixture: `hello -> accepted ACK -> mission_plan -> accepted ACK -> 50 Hz
vehicle_state -> optional mission_end -> accepted ACK`, including exact V2
state fields and message ordering.

`LOCAL SIMULATOR PASSED` does **not** mean the real UE4 target was contacted.
The self-test opens no network connection.

## 2. Target prerequisites and model artifact

Run these commands from the repository root on the Ubuntu target before any
real-target start. Every command must exit zero:

```bash
set -euo pipefail
grep -q '^VERSION_ID="18.04"$' /etc/os-release
uname -a | grep -Eqi 'PREEMPT[ _-]?RT'
test "$(gcc -dumpfullversion -dumpversion | cut -d. -f1)" = "7"
gcc -dumpfullversion -dumpversion
python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:3] == (3, 6, 9) else 1)'
/usr/local/MATLAB/R2018b/bin/matlab -nodisplay -nosplash -nodesktop -r \
  "assert(strcmp(version('-release'),'2018b'));disp(version);exit(0)"
```

Provision the repository's pinned Python requirement, then validate the
imports used by the no-WebSocket debug entry point:

```bash
python3 -m pip install --requirement requirements.txt
PYTHONPATH=python_services python3 -c \
  'import yaml, debug_main; debug_main._Runtime(); print(yaml.__version__)'
```

The supported repository build creates the Z-mission ERT/GCC artifact and
prints its executable path on its final output line:

```bash
MODEL_EXECUTABLE="$(bash scripts/build_quadrotor_demo.sh | tail -n 1)"
MODEL_EXECUTABLE="$(readlink -f -- "$MODEL_EXECUTABLE")"
case "$MODEL_EXECUTABLE" in /*) ;; *) echo "not an absolute path" >&2; exit 2;; esac
test -f "$MODEL_EXECUTABLE"
test -x "$MODEL_EXECUTABLE"
printf 'validated model executable: %s\n' "$MODEL_EXECUTABLE"
```

`scripts/build_quadrotor_demo.sh` itself rejects a non-Ubuntu-18.04-RT host
and a missing MATLAB R2018b executable. Do not substitute an artifact copied
from Windows. If an already-built target artifact is supplied instead, run
the `readlink`, absolute-path, `-f`, and `-x` validation commands above with
its path assigned to `MODEL_EXECUTABLE`.

Finally, `config.yaml` must resolve `debug_ue4_tcp` to exactly
`192.168.100.172:5000`.

## 3. Start the real-target run

Run one of these exact commands from the repository root:

```bash
chmod +x scripts/start_z_debug.sh scripts/stop_z_debug.sh
./scripts/start_z_debug.sh "$MODEL_EXECUTABLE"
```

or use the validated environment variable:

```bash
HIL_Z_MODEL_EXECUTABLE="$MODEL_EXECUTABLE" ./scripts/start_z_debug.sh
```

The script preflights every required path and the configured target before it
launches anything. It starts the model, verifies that it remains alive, and
then starts the terminal-only debug service. PID records and redirected logs
are limited to ignored `runtime/z_debug/`.

The real-target evidence threshold is stronger than the local check. Only
after the debug log/dashboard reports accepted `hello` and `mission_plan`
ACKs from `192.168.100.172:5000` may the operator record:

```text
REAL UE4 ACKNOWLEDGED: hello and mission_plan accepted by 192.168.100.172:5000
```

The start script itself does not print or claim that result.

## 4. Stop the run

```bash
./scripts/stop_z_debug.sh
```

The stop script checks each recorded PID against `/proc/<pid>/exe` and the
recorded command before sending SIGTERM. It never uses name-pattern cleanup.
Running it again is safe and prints `No recorded Z debug run`.

## 5. Failed handshake

If the dashboard/log remains at `connecting`, reports `hello acknowledgement
failed`, or reports `mission_plan acknowledgement failed`, no state-streaming
claim is valid. Stop the run, then inspect:

```bash
tail -n 100 runtime/z_debug/debug.log
tail -n 100 runtime/z_debug/model.log
```

Confirm that the real UE4-side bridge is listening on
`192.168.100.172:5000`, the network route/firewall permits the TCP connection,
and its ACK has `accepted=true` with both `ref_type` and `ref_seq` matching the
request. A rejected, mismatched, timed-out, or missing ACK must be treated as a
failed real-target verification.

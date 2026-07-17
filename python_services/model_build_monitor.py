#!/usr/bin/env python3
import os
import json
import time
import subprocess
from shared.logger import get_logger
from config_loader import CONFIG

logger = get_logger('build_monitor')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASK_FILE = CONFIG['model_build']['task_file']
RESULT_FILE = CONFIG['model_build']['result_file']
SIGNAL_FILE = CONFIG['model_build']['signal_file']
TIMEOUT = CONFIG['model_build']['timeout']

def start_build_monitor():
    logger.info("Build monitor started, waiting for tasks...")
    processed = set()

    while True:
        try:
            if not os.path.exists(TASK_FILE):
                time.sleep(2)
                continue

            with open(TASK_FILE, 'r') as f:
                task = json.load(f)

            task_id = task.get('task_id', '')
            if task_id in processed or task.get('status') != 'pending':
                time.sleep(2)
                continue

            logger.info(f"Found task: {task_id}")
            task['status'] = 'processing'
            with open(TASK_FILE, 'w') as f:
                json.dump(task, f, indent=2)

            success = execute_matlab_build(task)

            task['status'] = 'completed' if success else 'failed'
            with open(TASK_FILE, 'w') as f:
                json.dump(task, f, indent=2)

            processed.add(task_id)
            logger.info(f"Task {task_id}: {task['status']}")

        except json.JSONDecodeError:
            time.sleep(2)
        except Exception as e:
            logger.error(f"Monitor error: {e}")
            time.sleep(5)

def execute_matlab_build(task):
    try:
        cmd = ['matlab', '-batch', f"build_script('{TASK_FILE}','{RESULT_FILE}')"]
        logger.info(f"Running: {' '.join(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT,
                                cwd=os.path.dirname(BASE_DIR))

        if result.stdout:
            logger.info(f"MATLAB output: {result.stdout[:500]}...")
        if result.stderr:
            logger.warning(f"MATLAB stderr: {result.stderr[:500]}...")

        if os.path.exists(RESULT_FILE):
            with open(RESULT_FILE, 'r') as f:
                build_result = json.load(f)
            if build_result.get('code') == 0:
                so_path = build_result.get('so_path')
                logger.info(f"Build success: {so_path}")
                with open(SIGNAL_FILE, 'w') as f:
                    json.dump({'so_path': so_path, 'model_name': build_result.get('model_name'),
                               'timestamp': build_result.get('timestamp')}, f)
                return True
            else:
                logger.error(f"Build failed: {build_result.get('message')}")
                return False
        else:
            logger.error("Result file not found")
            return False

    except subprocess.TimeoutExpired:
        logger.error("MATLAB timeout")
        return False
    except Exception as e:
        logger.error(f"MATLAB error: {e}")
        return False

if __name__ == '__main__':
    start_build_monitor()
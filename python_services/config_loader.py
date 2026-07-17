#!/usr/bin/env python3
import os
import yaml

CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')

def load_config():
    if not os.path.exists(CONFIG_PATH):
        default = {
            'local_udp': {'command_port': 9997, 'status_port': 9998},
            'tcp_services': {'init_port': 9997, 'tune_port': 8888, 'upload_port': 9996},
            'udp_forward': {'target_ip': '192.168.1.100', 'target_port': 9999, 'send_hz': 10},
            'ue4_tcp': {'port': 8889, 'send_hz': 10},
            'model_build': {
                'matlab_script': 'matlab_scripts/build_script.m',
                'upload_dir': 'models/uploads',
                'output_dir': 'models/generated',
                'libs_dir': 'models/libs',
                'task_file': '/tmp/model_build_task.json',
                'result_file': '/tmp/model_build_result.json',
                'signal_file': '/tmp/model_ready.signal',
                'timeout': 600
            },
            'logging': {'level': 'INFO', 'file': 'logs/hil.log'}
        }
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, 'w') as f:
            yaml.dump(default, f, default_flow_style=False)
        return default
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)

CONFIG = load_config()
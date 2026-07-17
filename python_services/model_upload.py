#!/usr/bin/env python3
import os
import json
import socket
from datetime import datetime
from shared.logger import get_logger
from config_loader import CONFIG

logger = get_logger('model_upload')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, CONFIG['model_build']['upload_dir'])
OUTPUT_DIR = os.path.join(BASE_DIR, CONFIG['model_build']['output_dir'])
LIBS_DIR = os.path.join(BASE_DIR, CONFIG['model_build']['libs_dir'])
TASK_FILE = CONFIG['model_build']['task_file']

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(LIBS_DIR, exist_ok=True)

def start_upload_server():
    port = CONFIG['tcp_services']['upload_port']
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', port))
    server.listen(5)
    logger.info(f"Upload server listening on {port}")

    while True:
        try:
            client, addr = server.accept()
            data = b''
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                data += chunk
            if data:
                handle_upload(data, addr)
                client.send(b'{"code":0,"msg":"Upload accepted"}')
            client.close()
        except Exception as e:
            logger.error(f"Upload error: {e}")

def handle_upload(data, addr):
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        model_name = f'model_{timestamp}'
        slx_path = os.path.join(UPLOAD_DIR, f'{model_name}.slx')
        with open(slx_path, 'wb') as f:
            f.write(data)
        logger.info(f"Saved: {slx_path} from {addr}")

        task = {
            'task_id': f'task_{timestamp}',
            'model_name': model_name,
            'slx_path': slx_path,
            'output_dir': os.path.join(OUTPUT_DIR, model_name),
            'lib_name': f'libmodel_{timestamp}',
            'created_at': timestamp,
            'status': 'pending'
        }
        with open(TASK_FILE, 'w') as f:
            json.dump(task, f, indent=2)
        logger.info(f"Task created: {task['task_id']}")
    except Exception as e:
        logger.error(f"Handle upload failed: {e}")
        raise

if __name__ == '__main__':
    start_upload_server()
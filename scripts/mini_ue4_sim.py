#!/usr/bin/env python3
# Minimal V2.0 ACK responder for UE4 bridge handshake during integration tests.
import json, socket, struct, sys

HOST, PORT = '0.0.0.0', 5000
print('Mini-UE4 (V2.0) :{}'.format(PORT))

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind((HOST, PORT))
srv.listen(1)
srv.settimeout(60)

try:    cli, addr = srv.accept(); print('connected {}'.format(addr))
except socket.timeout: print('timeout'); srv.close(); sys.exit(1)

def recv(s, t=0.5):
    s.settimeout(t)
    try:
        h = b''
        while len(h) < 4:
            c = s.recv(4 - len(h))
            if not c: return None
            h += c
        n = struct.unpack('>I', h)[0]
        if n > 1048576: return None
        b = b''
        while len(b) < n:
            c = s.recv(n - len(b))
            if not c: return None
            b += c
        return json.loads(b.decode('utf-8'))
    except socket.timeout: return None
    except: return None

def send(s, d):
    body = json.dumps(d).encode()
    s.sendall(struct.pack('>I', len(body)) + body)

nst = 0
try:
    while True:
        m = recv(cli, 1.0)
        if not m: nst = 0; continue
        tp = m.get('type',''); sq = m.get('seq', 0)
        if tp == 'hello':
            print('[HELLO] role={} rate={}hz'.format(
                m.get('data',{}).get('role','?'),
                m.get('data',{}).get('state_rate_hz','?')))
            send(cli, {'protocol_version':'2.0','type':'ack','seq':1,'vehicle_id':'Drone1',
                       'data':{'ref_seq':sq,'ref_type':'hello','accepted':True}})
        elif tp == 'mission_plan':
            wps = m.get('data',{}).get('waypoints',[])
            print('[MISSION_PLAN] id={} n={}'.format(m.get('data',{}).get('mission_id','?'), len(wps)))
            send(cli, {'protocol_version':'2.0','type':'ack','seq':sq+1,'vehicle_id':'Drone1',
                       'data':{'ref_seq':sq,'ref_type':'mission_plan','accepted':True}})
        elif tp == 'vehicle_state':
            nst += 1
            if nst <= 3:
                p = m.get('data',{}).get('position',{})
                print('[STATE#{}] t={:.2f} pos=({:.1f},{:.1f},{:.1f}) fs={}'.format(
                    nst, m.get('data',{}).get('sim_time',0),
                    p.get('x',0), p.get('y',0), p.get('height',0),
                    m.get('data',{}).get('flight_state','?')))
            elif nst == 4: print('[STATE] ...')
            elif nst % 200 == 0: print('[STATE] ... {}'.format(nst))
        elif tp == 'simulation_event':
            print('[EVENT] {}'.format(m.get('data',{}).get('event','?')))
            send(cli, {'protocol_version':'2.0','type':'ack','seq':sq+1,'vehicle_id':'Drone1',
                       'data':{'ref_seq':sq,'ref_type':'simulation_event','accepted':True}})
except KeyboardInterrupt: pass
except Exception as e: print('err: {}'.format(e))
finally: cli.close(); srv.close()

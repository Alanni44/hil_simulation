/* Non-real-time V3 TCP client.  It owns reconnect/ACK work on a separate
 * thread; the 1 ms model thread only replaces a small latest-state snapshot. */
#include "fixed_wing_v3_tcp.h"
#include "model_rt_wrapper.h"
#include "model_contract.h"

#include <arpa/inet.h>
#include <errno.h>
#include <json-c/json.h>
#include <math.h>
#include <netdb.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/ioctl.h>
#include <sys/time.h>
#include <netinet/tcp.h>
#include <unistd.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#ifndef HIL_FIXED_WING_V3_TCP
#define HIL_FIXED_WING_V3_TCP 0
#endif

#if HIL_FIXED_WING_V3_TCP

#define V3_MAX_FRAME (1024U * 1024U)
#define V3_MISSION_ID_MAX 128U
typedef struct {
    pthread_mutex_t lock;
    volatile sig_atomic_t running;
    int state_valid, mission_valid, event_pending;
    unsigned mission_generation;
    FlightStateV3_t state;
    char mission_id[V3_MISSION_ID_MAX], event_name[20], event_mission_id[V3_MISSION_ID_MAX];
    MissionWaypoint waypoints[MISSION_CONTROLLER_MAX_WAYPOINTS];
    unsigned waypoint_count;
} V3Client;
static V3Client client = {PTHREAD_MUTEX_INITIALIZER, 0, 0, 0, 0};
static pthread_t client_thread;

static int send_all(int fd, const void* bytes, size_t size) {
    const char* p = (const char*)bytes;
    while (size) { ssize_t n = send(fd, p, size, 0); if (n <= 0) return 0; p += n; size -= (size_t)n; }
    return 1;
}
static int recv_all(int fd, void* bytes, size_t size) {
    char* p = (char*)bytes;
    while (size) { ssize_t n = recv(fd, p, size, 0); if (n <= 0) return 0; p += n; size -= (size_t)n; }
    return 1;
}
static int send_json(int fd, struct json_object* message) {
    const char* text = json_object_to_json_string_ext(message, JSON_C_TO_STRING_PLAIN);
    uint32_t length = (uint32_t)strlen(text), network = htonl(length);
    return length <= V3_MAX_FRAME && send_all(fd, &network, sizeof(network)) && send_all(fd, text, length);
}
static struct json_object* recv_json(int fd) {
    uint32_t network, length; char* body; struct json_object* result;
    if (!recv_all(fd, &network, sizeof(network))) return NULL;
    length = ntohl(network); if (length > V3_MAX_FRAME) return NULL;
    body = (char*)malloc((size_t)length + 1U); if (!body) return NULL;
    if (!recv_all(fd, body, length)) { free(body); return NULL; }
    body[length] = '\0'; result = json_tokener_parse(body); free(body); return result;
}
static struct json_object* envelope(const char* type, uint64_t seq) {
    struct json_object* root = json_object_new_object();
    json_object_object_add(root, "protocol_version", json_object_new_string("3.0"));
    json_object_object_add(root, "type", json_object_new_string(type));
    json_object_object_add(root, "seq", json_object_new_int64((int64_t)seq));
    json_object_object_add(root, "vehicle_id", json_object_new_string("FixedWing01"));
    return root;
}
static int accepted_ack(struct json_object* value, const char* ref_type, uint64_t ref_seq) {
    struct json_object *type = NULL, *data = NULL, *accepted = NULL, *seq = NULL, *ref = NULL;
    int ok = value && json_object_object_get_ex(value,"type",&type) && json_object_object_get_ex(value,"data",&data) &&
        json_object_object_get_ex(data,"accepted",&accepted) && json_object_object_get_ex(data,"ref_type",&ref) &&
        json_object_object_get_ex(data,"ref_seq",&seq) && !strcmp(json_object_get_string(type),"ack") &&
        json_object_get_boolean(accepted) && !strcmp(json_object_get_string(ref),ref_type) &&
        (uint64_t)json_object_get_int64(seq) == ref_seq;
    return ok;
}
static void rpy_from_quaternion(const FlightStateV3_t* s, double* roll, double* pitch, double* yaw) {
    const double qw=s->q_w,qx=s->q_x,qy=s->q_y,qz=s->q_z;
    double sinp = 2.0*(qw*qy-qz*qx);
    *roll = -atan2(2.0*(qw*qx+qy*qz),1.0-2.0*(qx*qx+qy*qy));
    *pitch = -(fabs(sinp)>=1.0 ? copysign(M_PI/2.0,sinp) : asin(sinp));
    *yaw = atan2(2.0*(qw*qz+qx*qy),1.0-2.0*(qy*qy+qz*qz));
}
static void add_num(struct json_object* o, const char* n, double v) { json_object_object_add(o,n,json_object_new_double(v)); }
static int aerodynamics(const FlightStateV3_t* s, double* tas, double* alpha, double* beta) {
    const double qw=s->q_w,qx=s->q_x,qy=s->q_y,qz=s->q_z;
    const double north=s->vn_mps-s->wind_n_mps,east=s->ve_mps-s->wind_e_mps,down=s->vd_mps-s->wind_d_mps;
    const double u=(1-2*(qy*qy+qz*qz))*north + 2*(qx*qy+qz*qw)*east + 2*(qx*qz-qy*qw)*down;
    const double v=2*(qx*qy-qz*qw)*north + (1-2*(qx*qx+qz*qz))*east + 2*(qy*qz+qx*qw)*down;
    const double w=2*(qx*qz+qy*qw)*north + 2*(qy*qz-qx*qw)*east + (1-2*(qx*qx+qy*qy))*down;
    *tas=sqrt(u*u+v*v+w*w); if(*tas < s->tas_min_mps) return 0;
    *alpha=atan2(w,u); *beta=asin(fmax(-1.0,fmin(1.0,v / *tas))); return 1;
}
static struct json_object* state_message(const FlightStateV3_t* s, const char* mission_id, uint64_t seq) {
    double roll,pitch,yaw,tas,alpha,beta; struct json_object *root=envelope("vehicle_state",seq),*data=json_object_new_object(),*o;
    rpy_from_quaternion(s,&roll,&pitch,&yaw);
    json_object_object_add(data,"mission_id",json_object_new_string(mission_id)); add_num(data,"sim_time",s->sim_time_s);
    o=json_object_new_object(); add_num(o,"x",s->north_m);add_num(o,"y",s->east_m);add_num(o,"height",-s->down_m);json_object_object_add(data,"position",o);
    o=json_object_new_object(); add_num(o,"roll",roll);add_num(o,"pitch",pitch);add_num(o,"yaw",yaw);json_object_object_add(data,"attitude",o);
    o=json_object_new_object(); add_num(o,"vx",s->vn_mps);add_num(o,"vy",s->ve_mps);add_num(o,"vz",-s->vd_mps);json_object_object_add(data,"velocity",o);
    o=json_object_new_object(); add_num(o,"ax",s->ax_mps2);add_num(o,"ay",s->ay_mps2);add_num(o,"az",-s->az_mps2);json_object_object_add(data,"acceleration",o);
    o=json_object_new_object(); add_num(o,"p",s->p_radps);add_num(o,"q",s->q_radps);add_num(o,"r",s->r_radps);json_object_object_add(data,"angular_velocity",o);
    o=json_object_new_object(); add_num(o,"p_dot",s->p_dot_radps2);add_num(o,"q_dot",s->q_dot_radps2);add_num(o,"r_dot",s->r_dot_radps2);json_object_object_add(data,"angular_acceleration",o);
    if(aerodynamics(s,&tas,&alpha,&beta)){o=json_object_new_object();add_num(o,"airspeed",tas);add_num(o,"angle_of_attack",alpha);add_num(o,"sideslip_angle",beta);json_object_object_add(data,"aerodynamics",o);}
    o=json_object_new_object(); add_num(o,"throttle",s->throttle);
    if (s->control_surface_valid) { add_num(o,"aileron",s->aileron_rad);add_num(o,"elevator",s->elevator_rad);add_num(o,"rudder",s->rudder_rad); }
    json_object_object_add(data,"control",o);
    json_object_object_add(data,"flight_state",json_object_new_string((const char*[]){"ready","taking_off","flying","landing","landed","fault"}[s->flight_phase <= 5 ? s->flight_phase : 5]));
    json_object_object_add(root,"data",data); return root;
}
static int send_low_rate(int fd, struct json_object* root, const char* type, uint64_t seq) {
    struct json_object* reply; int ok = send_json(fd,root); json_object_put(root); if (!ok) return 0;
    reply=recv_json(fd); ok=accepted_ack(reply,type,seq); if (reply) json_object_put(reply); return ok;
}
static int connect_server(void) {
    const char* host = getenv("HIL_V3_TCP_HOST");
    const char* port = getenv("HIL_V3_TCP_PORT");
    struct addrinfo hints, *info = NULL, *it;
    int fd = -1;
    int one = 1;
    if (!host || !*host) host = "127.0.0.1";
    if (!port || !*port) port = "5000";
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(host,port,&hints,&info)!=0) return -1;
    for (it = info; it; it = it->ai_next) {
        fd = socket(it->ai_family, it->ai_socktype, it->ai_protocol);
        if (fd >= 0 && connect(fd, it->ai_addr, it->ai_addrlen) == 0) break;
        if (fd >= 0) close(fd);
        fd = -1;
    }
    freeaddrinfo(info);
    if (fd >= 0) {
        struct timeval tv = {1, 0};
        setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
    }
    return fd;
}
static int send_hello(int fd, uint64_t* seq) { struct json_object *r=envelope("hello",++*seq),*d=json_object_new_object();
    json_object_object_add(d,"role",json_object_new_string("simulink_fixedwing_state_source"));json_object_object_add(d,"state_rate_hz",json_object_new_int(50));json_object_object_add(d,"coordinate_convention",json_object_new_string("x_forward_y_right_height_up"));json_object_object_add(d,"body_frame",json_object_new_string("FRD"));json_object_object_add(d,"angle_unit",json_object_new_string("rad"));json_object_object_add(r,"data",d);return send_low_rate(fd,r,"hello",*seq); }
static int send_mission(int fd, const char* id, const MissionWaypoint* points, unsigned count, uint64_t* seq) { unsigned i; struct json_object *r=envelope("mission_plan",++*seq),*d=json_object_new_object(),*a=json_object_new_array();
    for(i=0;i<count;i++){struct json_object*w=json_object_new_object();char name[16];snprintf(name,sizeof(name),"P%u",i+1U);json_object_object_add(w,"id",json_object_new_string(name));add_num(w,"x",points[i].north_m);add_num(w,"y",points[i].east_m);add_num(w,"height",-points[i].down_m);add_num(w,"target_speed",points[i].speed_mps);json_object_array_add(a,w);} json_object_object_add(d,"mission_id",json_object_new_string(id));json_object_object_add(d,"replace_previous",json_object_new_boolean(1));json_object_object_add(d,"waypoints",a);json_object_object_add(r,"data",d);return send_low_rate(fd,r,"mission_plan",*seq); }
static int send_event(int fd,const char* event,const char* id,uint64_t*seq){struct json_object*r=envelope("simulation_event",++*seq),*d=json_object_new_object();json_object_object_add(d,"event",json_object_new_string(event));if(id&&*id)json_object_object_add(d,"mission_id",json_object_new_string(id));json_object_object_add(r,"data",d);return send_low_rate(fd,r,"simulation_event",*seq);}
static int consume_server_error(int fd) {
    char header[4]; int available = 0; uint32_t length; char* body; struct json_object *message, *data = NULL, *type = NULL;
    if (ioctl(fd, FIONREAD, &available) != 0) return 0;
    if (available == 0) return 1;
    if (available < (int)sizeof(header) || recv(fd, header, sizeof(header), MSG_PEEK) != (ssize_t)sizeof(header)) return 1;
    memcpy(&length, header, sizeof(length)); length = ntohl(length);
    if (length > V3_MAX_FRAME || available < (int)(sizeof(header) + length)) return length <= V3_MAX_FRAME;
    if (!recv_all(fd, header, sizeof(header))) return 0;
    body = (char*)malloc((size_t)length + 1U); if (!body) return 0;
    if (!recv_all(fd, body, length)) { free(body); return 0; }
    body[length] = '\0'; message = json_tokener_parse(body); free(body);
    if (!message) return 0;
    if (json_object_object_get_ex(message, "type", &type) && json_object_object_get_ex(message, "data", &data) &&
        !strcmp(json_object_get_string(type), "error"))
        fprintf(stderr, "[HIL] V3 Bridge error: %s\n", json_object_to_json_string_ext(data, JSON_C_TO_STRING_PLAIN));
    json_object_put(message); return 1;
}
static void* worker(void* ignored) {
    (void)ignored;
    while (client.running) {
        int fd = connect_server();
        uint64_t seq = 0;
        unsigned sent_generation = 0;
        if (fd < 0) { usleep(500000); continue; }
        if (!send_hello(fd, &seq)) { close(fd); continue; }
        while (client.running) {
            FlightStateV3_t state_snapshot;
            char id[V3_MISSION_ID_MAX], event[20], event_id[V3_MISSION_ID_MAX];
            MissionWaypoint points[MISSION_CONTROLLER_MAX_WAYPOINTS];
            unsigned waypoint_count, generation;
            int has_state, has_mission, has_event;
            pthread_mutex_lock(&client.lock);
            has_state = client.state_valid;
            has_mission = client.mission_valid;
            has_event = client.event_pending;
            generation = client.mission_generation;
            if (has_state) state_snapshot = client.state;
            if (has_mission) {
                strncpy(id, client.mission_id, sizeof(id)); id[sizeof(id)-1] = '\0';
                waypoint_count = client.waypoint_count;
                memcpy(points, client.waypoints, waypoint_count * sizeof(points[0]));
            }
            if (has_event) {
                strncpy(event, client.event_name, sizeof(event)); event[sizeof(event)-1] = '\0';
                strncpy(event_id, client.event_mission_id, sizeof(event_id)); event_id[sizeof(event_id)-1] = '\0';
                client.event_pending = 0;
            }
            pthread_mutex_unlock(&client.lock);
            if (has_event && !send_event(fd, event, event_id, &seq)) break;
            if (!has_mission) { usleep(20000); continue; }
            if (generation != sent_generation) {
                if (!send_mission(fd, id, points, waypoint_count, &seq)) break;
                sent_generation = generation;
            }
            if (has_state) {
                struct json_object* state_json = state_message(&state_snapshot, id, ++seq);
                int ok = send_json(fd, state_json);
                json_object_put(state_json);
                if (!ok) break;
            }
            if (!consume_server_error(fd)) break;
            usleep(20000);
        }
        close(fd);
        usleep(200000);
    }
    return NULL;
}
int fixed_wing_v3_tcp_start(void){if(client.running)return 1;client.running=1;return pthread_create(&client_thread,NULL,worker,NULL)==0;}
void fixed_wing_v3_tcp_publish_state(const FlightStateV3_t* state){if(!state)return;pthread_mutex_lock(&client.lock);client.state=*state;client.state_valid=1;pthread_mutex_unlock(&client.lock);}
void fixed_wing_v3_tcp_set_mission(const char* id,const MissionWaypoint* p,unsigned n){if(!id||!p||n<2||n>MISSION_CONTROLLER_MAX_WAYPOINTS)return;pthread_mutex_lock(&client.lock);strncpy(client.mission_id,id,sizeof(client.mission_id)-1);client.mission_id[sizeof(client.mission_id)-1]='\0';memcpy(client.waypoints,p,n*sizeof(p[0]));client.waypoint_count=n;client.mission_valid=1;client.mission_generation++;pthread_mutex_unlock(&client.lock);}
void fixed_wing_v3_tcp_clear_mission(void){pthread_mutex_lock(&client.lock);client.mission_id[0]='\0';client.waypoint_count=0;client.mission_valid=0;client.mission_generation++;pthread_mutex_unlock(&client.lock);}
void fixed_wing_v3_tcp_send_event(const char* event,const char* id){if(!event)return;pthread_mutex_lock(&client.lock);strncpy(client.event_name,event,sizeof(client.event_name)-1);client.event_name[sizeof(client.event_name)-1]='\0';strncpy(client.event_mission_id,id?id:"",sizeof(client.event_mission_id)-1);client.event_mission_id[sizeof(client.event_mission_id)-1]='\0';client.event_pending=1;pthread_mutex_unlock(&client.lock);}
void fixed_wing_v3_tcp_stop(void){if(!client.running)return;client.running=0;pthread_join(client_thread,NULL);}

#else
int fixed_wing_v3_tcp_start(void){return 1;} void fixed_wing_v3_tcp_publish_state(const FlightStateV3_t* s){(void)s;} void fixed_wing_v3_tcp_set_mission(const char* i,const MissionWaypoint* w,unsigned n){(void)i;(void)w;(void)n;} void fixed_wing_v3_tcp_clear_mission(void){} void fixed_wing_v3_tcp_send_event(const char* e,const char* i){(void)e;(void)i;} void fixed_wing_v3_tcp_stop(void){}
#endif

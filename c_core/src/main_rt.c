#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <sched.h>
#include <time.h>
#include <pthread.h>
#include <sys/mman.h>
#include <inttypes.h>
#include <json-c/json.h>

#include "flight_state.h"
#include "model_rt_wrapper.h"
#include "hal_stub.h"
#include "local_udp.h"

#define STEP_NS 1000000LL
#define UDP_CMD_PORT 9997
#define UDP_STATUS_PORT 9998
#define SEND_INTERVAL 50   /* 20Hz = 1000/50 */

static volatile int running = 1;
static FlightState_t current_state;
static ModelInput_t model_params;
static int model_initialized = 0;

/* ---- V2.0 waypoint queue ---- */
static struct { double x, y, height, speed; } _wp_queue[MAX_WAYPOINTS];
static int _wp_count = 0;
static int _wp_current = 0;
static int _wp_active = 0;
static char _mission_id[256] = {0};

/* ---- angular velocity calculation ---- */
static float _prev_roll = 0.0f, _prev_pitch = 0.0f, _prev_yaw = 0.0f;

void signal_handler(int sig) {
    printf("\n[Main] Received signal %d, exiting...\n", sig);
    running = 0;
}

/* ---- V2.0 flight_state derivation ---- */
static uint8_t derive_flight_state(int airborne, double pos_z, int cmd_mode, int wp_active) {
    if (cmd_mode == 1) return 1; /* taking_off */
    if (cmd_mode == 2) return 4; /* landing */
    if (cmd_mode == 3) return 3; /* hovering */
    if (!airborne && pos_z < 0.5) return 5; /* landed */
    if (!airborne && pos_z >= 0.5) return 0; /* ready (on ground) */
    if (wp_active) return 2; /* flying (waypoint mode) */
    if (airborne) return 2;  /* flying */
    return 0; /* ready */
}

/* ---- V2.0 flight_state string ---- */
static const char* flight_state_str(uint8_t fs) {
    switch (fs) {
        case 0: return "ready";
        case 1: return "taking_off";
        case 2: return "flying";
        case 3: return "hovering";
        case 4: return "landing";
        case 5: return "landed";
        case 6: return "fault";
        default: return "ready";
    }
}

static int parse_command(const char* json_str) {
    if (!json_str) return -1;
    struct json_object *root, *params_obj, *cmd_obj;
    root = json_tokener_parse(json_str);
    if (!root) return -1;

    const char* cmd = NULL;
    json_object_object_get_ex(root, "cmd", &cmd_obj);
    if (cmd_obj) cmd = json_object_get_string(cmd_obj);

    /* ---- init_sim ---- */
    if (cmd && strcmp(cmd, "init_sim") == 0) {
        json_object_object_get_ex(root, "params", &params_obj);
        if (params_obj) {
            json_object_object_foreach(params_obj, key, val) {
                if (strcmp(key, "initial_lat") == 0) model_params.init_lat = json_object_get_double(val);
                else if (strcmp(key, "initial_lon") == 0) model_params.init_lon = json_object_get_double(val);
                else if (strcmp(key, "initial_alt") == 0) model_params.init_alt = json_object_get_double(val);
                else if (strcmp(key, "initial_roll") == 0) model_params.init_roll = json_object_get_double(val);
                else if (strcmp(key, "initial_pitch") == 0) model_params.init_pitch = json_object_get_double(val);
                else if (strcmp(key, "initial_yaw") == 0) model_params.init_yaw = json_object_get_double(val);
                else if (strcmp(key, "init_x") == 0) model_params.init_x = json_object_get_double(val);
                else if (strcmp(key, "init_y") == 0) model_params.init_y = json_object_get_double(val);
                else if (strcmp(key, "min_speed") == 0) model_params.min_speed = (float)json_object_get_double(val);
                else if (strcmp(key, "max_speed") == 0) model_params.max_speed = (float)json_object_get_double(val);
                else if (strcmp(key, "min_height") == 0) model_params.min_height = (float)json_object_get_double(val);
                else if (strcmp(key, "max_height") == 0) model_params.max_height = (float)json_object_get_double(val);
            }
        }
        ModelU_t* U = model_get_input();
        if (!model_initialized && U) {
            U->lat_init = model_params.init_lat;
            U->lon_init = model_params.init_lon;
            U->alt_init = model_params.init_alt;
            U->roll_init = model_params.init_roll;
            U->pitch_init = model_params.init_pitch;
            U->yaw_init = model_params.init_yaw;
            U->init_x = model_params.init_x;
            U->init_y = model_params.init_y;
            U->min_speed = model_params.min_speed;
            U->max_speed = model_params.max_speed;
            U->min_height = model_params.min_height;
            U->max_height = model_params.max_height;
            model_initialized = 1;
            printf("[Main] Model initialized (x=%.1f,y=%.1f, spd=%.1f-%.1f, h=%.1f-%.1f)\n",
                   U->init_x, U->init_y, U->min_speed, U->max_speed, U->min_height, U->max_height);
        }
        json_object_put(root);
        return 0;
    }

    /* ---- load_mission: 后端发航点 ---- */
    if (cmd && strcmp(cmd, "load_mission") == 0) {
        json_object_object_get_ex(root, "params", &params_obj);
        if (params_obj) {
            struct json_object *wps_obj, *wp_obj;
            json_object_object_get_ex(params_obj, "mission_id", &cmd_obj);
            if (cmd_obj) {
                strncpy(_mission_id, json_object_get_string(cmd_obj), sizeof(_mission_id) - 1);
            }
            json_object_object_get_ex(params_obj, "waypoints", &wps_obj);
            int n = json_object_array_length(wps_obj);
            _wp_count = (n < MAX_WAYPOINTS) ? n : MAX_WAYPOINTS;
            for (int i = 0; i < _wp_count; i++) {
                wp_obj = json_object_array_get_idx(wps_obj, i);
                struct json_object *f;
                json_object_object_get_ex(wp_obj, "lat", &f);
                double lat = f ? json_object_get_double(f) : 39.9;
                json_object_object_get_ex(wp_obj, "lon", &f);
                double lon = f ? json_object_get_double(f) : 116.4;
                json_object_object_get_ex(wp_obj, "height", &f);
                double h = f ? json_object_get_double(f) : 50.0;
                json_object_object_get_ex(wp_obj, "speed", &f);
                double spd = f ? json_object_get_double(f) : 5.0;
                /* 经纬度 → x/y（参考初始位置） */
                _wp_queue[i].x = (lon - model_params.init_lon) / 0.00001;
                _wp_queue[i].y = (lat - model_params.init_lat) / 0.00001;
                _wp_queue[i].height = h;
                _wp_queue[i].speed = spd;
            }
            _wp_current = 0;
            _wp_active = 1;

            /* 设定第一个航点为目标 */
            ModelU_t* U = model_get_input();
            if (U && _wp_count > 0) {
                U->cmd_x = _wp_queue[0].x;
                U->cmd_y = _wp_queue[0].y;
                U->cmd_z = _wp_queue[0].height;
                U->cmd_speed = _wp_queue[0].speed;
                U->cmd_mode = 4;
            }
            printf("[Cmd] load_mission: %d waypoints, mission=%s\n", _wp_count, _mission_id);
        }
        json_object_put(root);
        return 0;
    }

    /* ---- tune ---- */
    if (cmd && strcmp(cmd, "tune") == 0) {
        ModelU_t* U = model_get_input();
        if (!U) { json_object_put(root); return -1; }
        json_object_object_get_ex(root, "params", &params_obj);
        if (params_obj) {
            json_object_object_foreach(params_obj, key, val) {
                double value = json_object_get_double(val);
                if (strcmp(key, "throttle") == 0) U->throttle = (float)value;
                else if (strcmp(key, "pitch") == 0) U->pitch_cmd = (float)value;
                else if (strcmp(key, "roll") == 0) U->roll_cmd = (float)value;
                else if (strcmp(key, "yaw") == 0) U->yaw_cmd = (float)value;
                else if (strcmp(key, "flight_mode") == 0) U->flight_mode = (int)value;
                else if (strcmp(key, "experiment_mode") == 0) U->experiment_mode = (int)value;
                else if (strcmp(key, "pid_kp_roll") == 0) U->pid_kp_roll = (float)value;
                else if (strcmp(key, "pid_ki_roll") == 0) U->pid_ki_roll = (float)value;
                else if (strcmp(key, "pid_kd_roll") == 0) U->pid_kd_roll = (float)value;
                else if (strcmp(key, "pid_kp_pitch") == 0) U->pid_kp_pitch = (float)value;
                else if (strcmp(key, "pid_ki_pitch") == 0) U->pid_ki_pitch = (float)value;
                else if (strcmp(key, "pid_kd_pitch") == 0) U->pid_kd_pitch = (float)value;
                else if (strcmp(key, "pid_kp_yaw") == 0) U->pid_kp_yaw = (float)value;
                else if (strcmp(key, "pid_ki_yaw") == 0) U->pid_ki_yaw = (float)value;
                else if (strcmp(key, "pid_kd_yaw") == 0) U->pid_kd_yaw = (float)value;
                else if (strcmp(key, "target_alt") == 0) U->target_alt = (float)value;
            }
            printf("[Tune] throttle=%.1f pitch=%.1f roll=%.1f yaw=%.1f fm=%d em=%d\n",
                   U->throttle, U->pitch_cmd, U->roll_cmd, U->yaw_cmd,
                   U->flight_mode, U->experiment_mode);
        }
        json_object_put(root);
        return 0;
    }

    /* ---- takeoff / land / hover / move_position / move_velocity ---- */
    ModelU_t* U = model_get_input();
    if (!U) {
        printf("[Cmd] Model not loaded, ignoring '%s'\n", cmd ? cmd : "null");
        json_object_put(root);
        return -1;
    }

    if (cmd && strcmp(cmd, "takeoff") == 0) {
        _wp_active = 0;
        json_object_object_get_ex(root, "params", &params_obj);
        if (params_obj) {
            json_object_object_foreach(params_obj, key, val) {
                if (strcmp(key, "height") == 0) U->cmd_z = json_object_get_double(val);
            }
        }
        if (U->cmd_z <= 0.0) U->cmd_z = 50.0;
        U->cmd_mode = 1;
        printf("[Cmd] takeoff height=%.1f\n", U->cmd_z);
    } else if (cmd && strcmp(cmd, "land") == 0) {
        _wp_active = 0;
        U->cmd_mode = 2;
        printf("[Cmd] land\n");
    } else if (cmd && strcmp(cmd, "hover") == 0) {
        _wp_active = 0;
        U->cmd_mode = 3;
        printf("[Cmd] hover\n");
    } else if (cmd && strcmp(cmd, "move_position") == 0) {
        _wp_active = 0;
        json_object_object_get_ex(root, "params", &params_obj);
        if (params_obj) {
            json_object_object_foreach(params_obj, key, val) {
                if (strcmp(key, "x") == 0) U->cmd_x = json_object_get_double(val);
                else if (strcmp(key, "y") == 0) U->cmd_y = json_object_get_double(val);
                else if (strcmp(key, "height") == 0) U->cmd_z = json_object_get_double(val);
                else if (strcmp(key, "speed") == 0) U->cmd_speed = json_object_get_double(val);
            }
            U->cmd_mode = 4;
            printf("[Cmd] move_position: (%.1f, %.1f, %.1f) spd=%.1f\n",
                   U->cmd_x, U->cmd_y, U->cmd_z, U->cmd_speed);
        }
    } else if (cmd && strcmp(cmd, "move_velocity") == 0) {
        _wp_active = 0;
        json_object_object_get_ex(root, "params", &params_obj);
        if (params_obj) {
            json_object_object_foreach(params_obj, key, val) {
                if (strcmp(key, "vx") == 0) U->cmd_x = json_object_get_double(val);
                else if (strcmp(key, "vy") == 0) U->cmd_y = json_object_get_double(val);
                else if (strcmp(key, "vz") == 0) U->cmd_z = json_object_get_double(val);
                else if (strcmp(key, "duration") == 0) U->cmd_duration = json_object_get_double(val);
            }
            U->cmd_mode = 5;
            printf("[Cmd] move_velocity: (%.1f, %.1f, %.1f) dur=%.2f\n",
                   U->cmd_x, U->cmd_y, U->cmd_z, U->cmd_duration);
        }
    } else if (cmd && strcmp(cmd, "get_state") == 0) {
        printf("[Cmd] get_state\n");
    }
    json_object_put(root);
    return 0;
}

void* command_thread(void* arg) {
    char buffer[4096];
    while (running) {
        int n = udp_recv_command(buffer, sizeof(buffer));
        if (n > 0) parse_command(buffer);
        usleep(10000);
    }
    return NULL;
}

int main(int argc, char** argv) {
    printf("=== HIL Real-Time Core Starting ===\n");

    struct sched_param param = { .sched_priority = 99 };
    if (sched_setscheduler(0, SCHED_FIFO, &param) == -1)
        perror("sched_setscheduler (run with sudo)");

    if (mlockall(MCL_CURRENT | MCL_FUTURE) == -1)
        perror("mlockall");

    hal_system_init();

    if (udp_init(UDP_CMD_PORT, UDP_STATUS_PORT) != 0) {
        fprintf(stderr, "[Error] UDP init failed\n");
        return -1;
    }

    model_initialize();
    model_initialized = 1;

    pthread_t cmd_thread_id;
    pthread_create(&cmd_thread_id, NULL, command_thread, NULL);

    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);

    struct timespec next_time;
    clock_gettime(CLOCK_MONOTONIC, &next_time);
    uint64_t step_count = 0;
    printf("[Main] Starting 1ms loop...\n");

    while (running) {
        next_time.tv_nsec += STEP_NS;
        if (next_time.tv_nsec >= 1000000000) {
            next_time.tv_nsec -= 1000000000;
            next_time.tv_sec += 1;
        }
        clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next_time, NULL);

        step_count++;

        if (step_count % 1000 == 0) {
            model_apply_pending_update(&argc, argv);
            if (model_is_loaded()) {
                model_initialized = 1;
            }
        }

        if (model_is_loaded() && model_initialized) {
            model_step();

            ModelY_t y;
            model_get_output(&y);

            /* ---- waypoint queue: check if reached current, advance ---- */
            if (_wp_active && _wp_count > 0 && _wp_current < _wp_count) {
                double dx = y.pos_x - _wp_queue[_wp_current].x;
                double dy = y.pos_y - _wp_queue[_wp_current].y;
                double dz = y.pos_z - _wp_queue[_wp_current].height;
                if ((dx*dx + dy*dy + dz*dz) < 1.0) { /* within 1m → reached */
                    _wp_current++;
                    ModelU_t* U = model_get_input();
                    if (U && _wp_current < _wp_count) {
                        U->cmd_x = _wp_queue[_wp_current].x;
                        U->cmd_y = _wp_queue[_wp_current].y;
                        U->cmd_z = _wp_queue[_wp_current].height;
                        U->cmd_speed = _wp_queue[_wp_current].speed;
                        U->cmd_mode = 4;
                        printf("[Waypoint] %d/%d reached, next: (%.1f,%.1f,%.1f)\n",
                               _wp_current, _wp_count, U->cmd_x, U->cmd_y, U->cmd_z);
                    } else {
                        _wp_active = 0;
                        printf("[Waypoint] All %d waypoints completed\n", _wp_count);
                    }
                }
            }

            current_state.version = 1;
            current_state.timestamp_us = step_count * 1000;
            current_state.pos_x = y.pos_x;
            current_state.pos_y = y.pos_y;
            current_state.pos_z = y.pos_z;
            current_state.lat = y.lat;
            current_state.lon = y.lon;
            current_state.alt = y.alt;
            current_state.roll = y.roll;
            current_state.pitch = y.pitch;
            current_state.yaw = y.yaw;
            current_state.vel_x = y.vel_x;
            current_state.vel_y = y.vel_y;
            current_state.vel_z = y.vel_z;
            current_state.acc_x = y.acc_x;
            current_state.acc_y = y.acc_y;
            current_state.acc_z = y.acc_z;

            /* ---- angular velocity: diff of attitude / 100ms ---- */
            if (step_count % SEND_INTERVAL == 0) {
                float dt = SEND_INTERVAL * 0.001f;  /* 100ms */
                if (dt > 0.0f) {
                    current_state.ang_vel_p = (y.roll - _prev_roll) / dt;
                    current_state.ang_vel_q = (y.pitch - _prev_pitch) / dt;
                    current_state.ang_vel_r = (y.yaw - _prev_yaw) / dt;
                }
                _prev_roll = y.roll;
                _prev_pitch = y.pitch;
                _prev_yaw = y.yaw;

                /* ---- V2.0 flight_state ---- */
                ModelU_t* U = model_get_input();
                int cmd_mode = U ? U->cmd_mode : 0;
                current_state.flight_state = derive_flight_state(
                    y.airborne, y.pos_z, cmd_mode, _wp_active);
            }

            current_state.battery_voltage = 24.5f;
            current_state.motor_speed_0 = 5000.0f;
            current_state.motor_speed_1 = 4800.0f;
            current_state.motor_speed_2 = 5200.0f;
            current_state.motor_speed_3 = 4900.0f;
            current_state.status_word = y.airborne ? 1 : 0;
            current_state.mission_id = 1;
            current_state.waypoint_index = _wp_active ? _wp_current : 0;
            current_state.flight_phase = 2;

            if (step_count % SEND_INTERVAL == 0) {
                udp_send_status(&current_state);
                hal_refmem_write(&current_state, sizeof(FlightState_t));
                hal_telemetry_send(&current_state, sizeof(FlightState_t));
            }
        }

        if (step_count % 1000 == 0 && model_is_loaded()) {
            printf("[Main] Step: %" PRIu64 ", Pos: (%.1f, %.1f, %.1f), Alt: %.1f, FS: %s\n",
                   step_count,
                   current_state.pos_x, current_state.pos_y, current_state.pos_z,
                   current_state.alt, flight_state_str(current_state.flight_state));
        }
    }

    model_terminate();
    hal_system_deinit();
    udp_close();
    pthread_cancel(cmd_thread_id);
    pthread_join(cmd_thread_id, NULL);

    printf("=== HIL Real-Time Core Stopped ===\n");
    return 0;
}

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <sched.h>
#include <time.h>
#include <pthread.h>
#include <json-c/json.h>

#include "flight_state.h"
#include "model_loader.h"
#include "hal_stub.h"
#include "local_udp.h"

#define STEP_NS 1000000LL
#define UDP_CMD_PORT 9997
#define UDP_STATUS_PORT 9998
#define SEND_INTERVAL 100

static volatile int running = 1;
static FlightState_t current_state;
static ModelInput_t model_params;
static int model_initialized = 0;

void signal_handler(int sig) {
    printf("\n[Main] Received signal %d, exiting...\n", sig);
    running = 0;
}

static int parse_command(const char* json_str) {
    if (!json_str) return -1;
    struct json_object *root, *params_obj, *cmd_obj;
    root = json_tokener_parse(json_str);
    if (!root) return -1;

    const char* cmd = NULL;
    json_object_object_get_ex(root, "cmd", &cmd_obj);
    if (cmd_obj) cmd = json_object_get_string(cmd_obj);

    ModelLoader_U_t* U = model_get_input();

    if (cmd && strcmp(cmd, "INIT") == 0) {
        json_object_object_get_ex(root, "params", &params_obj);
        if (params_obj) {
            json_object_object_foreach(params_obj, key, val) {
                if (strcmp(key, "initial_lat") == 0) model_params.init_lat = json_object_get_double(val);
                else if (strcmp(key, "initial_lon") == 0) model_params.init_lon = json_object_get_double(val);
                else if (strcmp(key, "initial_alt") == 0) model_params.init_alt = json_object_get_double(val);
                else if (strcmp(key, "initial_roll") == 0) model_params.init_roll = json_object_get_double(val);
                else if (strcmp(key, "initial_pitch") == 0) model_params.init_pitch = json_object_get_double(val);
                else if (strcmp(key, "initial_yaw") == 0) model_params.init_yaw = json_object_get_double(val);
            }
        }
        if (!model_initialized && U) {
            U->lat_init = model_params.init_lat;
            U->lon_init = model_params.init_lon;
            U->alt_init = model_params.init_alt;
            U->roll_init = model_params.init_roll;
            U->pitch_init = model_params.init_pitch;
            U->yaw_init = model_params.init_yaw;
            model_initialized = 1;
            printf("[Main] Model initialized with params\n");
        }
    } else if (cmd && strcmp(cmd, "takeoff") == 0) {
        if (U) { U->cmd_mode = 1; }
        printf("[Cmd] takeoff\n");
    } else if (cmd && strcmp(cmd, "land") == 0) {
        if (U) { U->cmd_mode = 2; }
        printf("[Cmd] land\n");
    } else if (cmd && strcmp(cmd, "hover") == 0) {
        if (U) { U->cmd_mode = 3; }
        printf("[Cmd] hover\n");
    } else if (cmd && strcmp(cmd, "move_position") == 0) {
        json_object_object_get_ex(root, "params", &params_obj);
        if (params_obj && U) {
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
        json_object_object_get_ex(root, "params", &params_obj);
        if (params_obj && U) {
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
        // get_state is handled by state UDP stream; no model input change needed
        printf("[Cmd] get_state (no-op on C side)\n");
    } else if (cmd && strcmp(cmd, "TUNE") == 0) {
        json_object_object_get_ex(root, "params", &params_obj);
        if (params_obj && U) {
            json_object_object_foreach(params_obj, key, val) {
                double value = json_object_get_double(val);
                if (strcmp(key, "pid_kp_roll") == 0) U->pid_kp_roll = value;
                else if (strcmp(key, "pid_ki_roll") == 0) U->pid_ki_roll = value;
                else if (strcmp(key, "pid_kd_roll") == 0) U->pid_kd_roll = value;
                else if (strcmp(key, "target_alt") == 0) U->target_alt = value;
                printf("[Param] %s = %.4f (immediate)\n", key, value);
            }
        }
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

    // 加载默认模型
    if (model_load("models/libs/libmodel_default.so") == 0) {
        model_initialized = 1;
    }

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

        // 每秒检查新模型
        if (step_count % 1000 == 0) {
            model_check_for_update();
            model_apply_pending_update();
            if (model_is_loaded()) {
                model_initialized = 1;
            }
        }

        if (model_is_loaded() && model_initialized) {
            model_step_call();

            ModelLoader_Y_t y;
            model_get_output(&y);

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
            current_state.battery_voltage = 24.5f;
            current_state.motor_speed_0 = 5000.0f;
            current_state.motor_speed_1 = 4800.0f;
            current_state.motor_speed_2 = 5200.0f;
            current_state.motor_speed_3 = 4900.0f;
            current_state.status_word = 0x07;
            current_state.mission_id = 1;
            current_state.waypoint_index = 0;
            current_state.flight_phase = 2;

            if (step_count % SEND_INTERVAL == 0) {
                udp_send_status(&current_state);
                hal_refmem_write(&current_state, sizeof(FlightState_t));
                hal_telemetry_send(&current_state, sizeof(FlightState_t));
            }
        }

        if (step_count % 1000 == 0 && model_is_loaded()) {
            printf("[Main] Step: %llu, Pos: (%.1f, %.1f, %.1f), Alt: %.1f\n",
                   step_count,
                   current_state.pos_x, current_state.pos_y, current_state.pos_z,
                   current_state.alt);
        }
    }

    model_unload();
    hal_system_deinit();
    udp_close();
    pthread_cancel(cmd_thread_id);
    pthread_join(cmd_thread_id, NULL);

    printf("=== HIL Real-Time Core Stopped ===\n");
    return 0;
}
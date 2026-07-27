/* Contract-bound 1 ms HIL runtime.  All model semantics originate in the
 * generated model_contract.h; there is no string-to-offset or inferred port
 * access path. */
#include <math.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <json-c/json.h>

#include "flight_state.h"
#include "local_udp.h"
#include "model_rt_wrapper.h"
#include "model_contract.h"

#define STEP_NS 1000000L
#define UDP_CMD_PORT 9997
#define UDP_STATUS_PORT 9998
#define SEND_INTERVAL 20U
#define REQUEST_ID_MAX 96

static volatile sig_atomic_t running = 1;
static volatile int lifecycle = HIL_RUNNING;
static FlightState_t state;
static uint64_t sequence = 0;
static double sim_time_s = 0.0;

typedef struct {
    ModelU_t input;
    unsigned generation;
} InputSnapshot;
static InputSnapshot pending_live;
static InputSnapshot pending_reset;
static ModelU_t active_input;
static ModelU_t initial_input;
static unsigned applied_live_generation = 0;
static pthread_mutex_t command_lock = PTHREAD_MUTEX_INITIALIZER;

typedef struct {
    int pending;
    int event;
    char request_id[REQUEST_ID_MAX];
    struct sockaddr_in sender;
} LifecycleRequest;
static LifecycleRequest lifecycle_request;

static void on_signal(int ignored) { (void)ignored; running = 0; }

static const char* lifecycle_name(int value) {
    switch (value) {
    case HIL_RUNNING: return "RUNNING";
    case HIL_PAUSED: return "PAUSED";
    case HIL_RESETTING: return "RESETTING";
    case HIL_ENDED: return "ENDED";
    default: return "INVALID";
    }
}

static int phase_mask(int value) { return 1 << value; }

static void send_receipt(const struct sockaddr_in* sender, const char* request_id,
                         int accepted, const char* reason, uint64_t effective_sequence,
                         struct json_object* fields) {
    struct json_object* response = json_object_new_object();
    char* encoded;
    json_object_object_add(response, "request_id", json_object_new_string(request_id ? request_id : ""));
    json_object_object_add(response, "accepted", json_object_new_boolean(accepted));
    json_object_object_add(response, "reason", json_object_new_string(reason ? reason : ""));
    json_object_object_add(response, "effective_sequence", json_object_new_int64((int64_t)effective_sequence));
    json_object_object_add(response, "lifecycle", json_object_new_string(lifecycle_name(lifecycle)));
    if (fields) json_object_object_add(response, "fields", fields);
    encoded = (char*)json_object_to_json_string_ext(response, JSON_C_TO_STRING_PLAIN);
    udp_send_receipt(encoded, sender);
    json_object_put(response);
}

static int valid_number(struct json_object* value, double* number, int* bool_value) {
    enum json_type type;
    if (!value || !number) return 0;
    type = json_object_get_type(value);
    if (type == json_type_boolean) {
        *number = json_object_get_boolean(value) ? 1.0 : 0.0;
        if (bool_value) *bool_value = 1;
        return 1;
    }
    if (type != json_type_int && type != json_type_double) return 0;
    *number = json_object_get_double(value);
    if (bool_value) *bool_value = 0;
    return isfinite(*number);
}

static const HilParameterSpec* find_parameter(const char* name) {
    unsigned i;
    for (i = 0; i < HIL_PARAMETER_COUNT; ++i)
        if (!strcmp(HIL_PARAMETER_SPECS[i].name, name)) return &HIL_PARAMETER_SPECS[i];
    return NULL;
}

static int state_is_valid(const FlightState_t* candidate) {
    const float norm = sqrtf(candidate->q_w * candidate->q_w + candidate->q_x * candidate->q_x +
                             candidate->q_y * candidate->q_y + candidate->q_z * candidate->q_z);
    if (!isfinite(candidate->sim_time_s) || !isfinite(candidate->north_m) ||
        !isfinite(candidate->east_m) || !isfinite(candidate->down_m) ||
        !isfinite(candidate->vn_mps) || !isfinite(candidate->ve_mps) || !isfinite(candidate->vd_mps) ||
        !isfinite(candidate->q_w) || !isfinite(candidate->q_x) || !isfinite(candidate->q_y) ||
        !isfinite(candidate->q_z) || !isfinite(candidate->p_radps) || !isfinite(candidate->q_radps) ||
        !isfinite(candidate->r_radps)) return 0;
    return norm > 0.0f && fabsf(norm - 1.0f) <= 0.02f && candidate->airborne <= 1;
}

static void populate_state(void) {
    ModelY_t output;
    FlightState_t candidate;
    model_get_output(&output);
    memset(&candidate, 0, sizeof(candidate));
    candidate.version = FLIGHT_STATE_VERSION;
    candidate.sequence = sequence;
    candidate.sim_time_s = sim_time_s;
    candidate.north_m = MODEL_READ_north_m(&output);
    candidate.east_m = MODEL_READ_east_m(&output);
    candidate.down_m = MODEL_READ_down_m(&output);
    candidate.vn_mps = MODEL_READ_vn_mps(&output);
    candidate.ve_mps = MODEL_READ_ve_mps(&output);
    candidate.vd_mps = MODEL_READ_vd_mps(&output);
    candidate.q_w = MODEL_READ_q_w(&output);
    candidate.q_x = MODEL_READ_q_x(&output);
    candidate.q_y = MODEL_READ_q_y(&output);
    candidate.q_z = MODEL_READ_q_z(&output);
    candidate.p_radps = MODEL_READ_p_radps(&output);
    candidate.q_radps = MODEL_READ_q_radps(&output);
    candidate.r_radps = MODEL_READ_r_radps(&output);
    candidate.airborne = MODEL_READ_airborne(&output) ? 1 : 0;
    candidate.lifecycle = (uint8_t)lifecycle;
    if (state_is_valid(&candidate)) state = candidate;
    else fprintf(stderr, "[HIL] rejected invalid generated state at sequence %llu\n", (unsigned long long)sequence);
}

static void queue_lifecycle(int event, const char* request_id, const struct sockaddr_in* sender) {
    pthread_mutex_lock(&command_lock);
    lifecycle_request.pending = 1;
    lifecycle_request.event = event;
    strncpy(lifecycle_request.request_id, request_id, sizeof(lifecycle_request.request_id) - 1);
    lifecycle_request.request_id[sizeof(lifecycle_request.request_id) - 1] = '\0';
    lifecycle_request.sender = *sender;
    pthread_mutex_unlock(&command_lock);
}

static void apply_lifecycle_request(void) {
    LifecycleRequest request;
    int valid = 1;
    pthread_mutex_lock(&command_lock);
    if (!lifecycle_request.pending) { pthread_mutex_unlock(&command_lock); return; }
    request = lifecycle_request;
    lifecycle_request.pending = 0;
    pthread_mutex_unlock(&command_lock);

    if (request.event == HIL_PAUSED) {
        if (lifecycle != HIL_RUNNING) valid = 0; else lifecycle = HIL_PAUSED;
    } else if (request.event == HIL_RUNNING) {
        if (lifecycle != HIL_PAUSED) valid = 0; else lifecycle = HIL_RUNNING;
    } else if (request.event == HIL_ENDED) {
        if (lifecycle != HIL_RUNNING && lifecycle != HIL_PAUSED) valid = 0; else lifecycle = HIL_ENDED;
    } else if (request.event == HIL_RESETTING) {
        if (lifecycle != HIL_PAUSED && lifecycle != HIL_ENDED && lifecycle != HIL_RUNNING) valid = 0;
        else {
            lifecycle = HIL_RESETTING;
            model_terminate();
            model_initialize();
            active_input = initial_input;
            if (pending_reset.generation) active_input = pending_reset.input;
            *model_get_input() = active_input;
            pending_live.input = active_input;
            pending_live.generation++;
            pending_reset.generation = 0;
            lifecycle = HIL_RUNNING;
            populate_state();
        }
    } else valid = 0;
    send_receipt(&request.sender, request.request_id, valid,
                 valid ? "applied" : "invalid lifecycle transition", sequence, NULL);
}

static void apply_live_update(void) {
    InputSnapshot snapshot;
    pthread_mutex_lock(&command_lock);
    snapshot = pending_live;
    pthread_mutex_unlock(&command_lock);
    if (snapshot.generation != applied_live_generation) {
        active_input = snapshot.input;
        *model_get_input() = active_input;
        applied_live_generation = snapshot.generation;
    }
}

static void parse_tune(struct json_object* root, const char* request_id,
                       const struct sockaddr_in* sender) {
    struct json_object *params = NULL;
    struct json_object* field_results = json_object_new_object();
    ModelU_t live_candidate, reset_candidate;
    int ok = 1, has_live = 0, has_reset = 0;
    if (!json_object_object_get_ex(root, "params", &params) ||
        json_object_get_type(params) != json_type_object || json_object_object_length(params) == 0) {
        send_receipt(sender, request_id, 0, "params must be a non-empty object", sequence, field_results); return;
    }
    pthread_mutex_lock(&command_lock);
    live_candidate = pending_live.input;
    reset_candidate = pending_reset.generation ? pending_reset.input : active_input;
    json_object_object_foreach(params, name, value) {
        const HilParameterSpec* spec = find_parameter(name);
        double number = 0.0; int was_bool = 0; const char* reason = "accepted";
        struct json_object* detail = json_object_new_object();
        if (!spec) { ok = 0; reason = "unknown parameter"; }
        else if (spec->klass == HIL_PARAM_READONLY) { ok = 0; reason = "readonly"; }
        else if (!(hil_contract_phase_mask(name) & phase_mask(lifecycle))) { ok = 0; reason = "not allowed in lifecycle"; }
        else if (!valid_number(value, &number, &was_bool)) { ok = 0; reason = "value must be finite scalar or boolean"; }
        else if (spec->is_bool != was_bool) { ok = 0; reason = "parameter type mismatch"; }
        else if (number < spec->min_value || number > spec->max_value) { ok = 0; reason = "value outside contract range"; }
        else if (spec->klass == HIL_PARAM_LIVE) { has_live = 1; if (!hil_contract_set_parameter(&live_candidate, name, number)) { ok = 0; reason = "generated setter unavailable"; } }
        else { has_reset = 1; if (!hil_contract_set_parameter(&reset_candidate, name, number)) { ok = 0; reason = "generated setter unavailable"; } }
        json_object_object_add(detail, "accepted", json_object_new_boolean(!strcmp(reason, "accepted")));
        json_object_object_add(detail, "reason", json_object_new_string(reason));
        json_object_object_add(field_results, name, detail);
    }
    if (ok) {
        if (has_live) { pending_live.input = live_candidate; pending_live.generation++; }
        if (has_reset) { pending_reset.input = reset_candidate; pending_reset.generation++; }
    }
    pthread_mutex_unlock(&command_lock);
    send_receipt(sender, request_id, ok, ok ? "accepted" : "atomic parameter group rejected",
                 ok && has_live ? sequence + 1U : sequence, field_results);
}

static void parse_command(const char* text, const struct sockaddr_in* sender) {
    struct json_object *root, *request, *cmd;
    const char *request_id, *command;
    root = json_tokener_parse(text);
    if (!root || json_object_get_type(root) != json_type_object) { send_receipt(sender, "", 0, "invalid JSON object", sequence, NULL); if (root) json_object_put(root); return; }
    if (!json_object_object_get_ex(root, "request_id", &request) || json_object_get_type(request) != json_type_string ||
        !json_object_object_get_ex(root, "cmd", &cmd) || json_object_get_type(cmd) != json_type_string) {
        send_receipt(sender, "", 0, "request_id and cmd are required", sequence, NULL); json_object_put(root); return;
    }
    request_id = json_object_get_string(request); command = json_object_get_string(cmd);
    if (!strcmp(command, "tune")) parse_tune(root, request_id, sender);
    else if (!strcmp(command, "pause")) queue_lifecycle(HIL_PAUSED, request_id, sender);
    else if (!strcmp(command, "resume")) queue_lifecycle(HIL_RUNNING, request_id, sender);
    else if (!strcmp(command, "reset")) queue_lifecycle(HIL_RESETTING, request_id, sender);
    else if (!strcmp(command, "mission_end")) queue_lifecycle(HIL_ENDED, request_id, sender);
    else send_receipt(sender, request_id, 0, "unsupported command for this contract", sequence, NULL);
    json_object_put(root);
}

static void* command_thread(void* ignored) {
    char buffer[65536]; struct sockaddr_in sender; (void)ignored;
    while (running) if (udp_recv_command(buffer, sizeof(buffer), &sender) > 0) parse_command(buffer, &sender);
    return NULL;
}

int main(void) {
    pthread_t command_worker; struct timespec next; unsigned send_counter = 0;
    signal(SIGINT, on_signal); signal(SIGTERM, on_signal);
    if (udp_init(UDP_CMD_PORT, UDP_STATUS_PORT) != 0) { fprintf(stderr, "UDP initialization failed\n"); return 1; }
    model_initialize();
    initial_input = *model_get_input();
    hil_contract_apply_defaults(&initial_input);
    active_input = initial_input;
    *model_get_input() = active_input;
    pending_live.input = active_input; pending_reset.input = active_input;
    populate_state();
    if (pthread_create(&command_worker, NULL, command_thread, NULL) != 0) { model_terminate(); udp_close(); return 1; }
    clock_gettime(CLOCK_MONOTONIC, &next);
    while (running) {
        next.tv_nsec += STEP_NS; if (next.tv_nsec >= 1000000000L) { next.tv_sec++; next.tv_nsec -= 1000000000L; }
        apply_lifecycle_request();
        if (lifecycle == HIL_RUNNING) {
            apply_live_update();
            model_step(); sequence++; sim_time_s += 0.001; populate_state();
        } else { state.lifecycle = (uint8_t)lifecycle; }
        if (++send_counter >= SEND_INTERVAL) { udp_send_status(&state); udp_send_monitor(&state); send_counter = 0; }
        clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL);
    }
    pthread_join(command_worker, NULL); model_terminate(); udp_close(); return 0;
}

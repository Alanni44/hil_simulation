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
#include "mission_controller.h"
#include "model_rt_wrapper.h"
#include "model_contract.h"
#include "realtime.h"

#define STEP_NS 1000000L
#define UDP_CMD_PORT 9997
#define UDP_STATUS_PORT 9998
#define SEND_INTERVAL 20U
#define REQUEST_ID_MAX 96
#define MISSION_ID_MAX 128
#define MAX_INPUT_VALUE_COUNT 16U

static volatile sig_atomic_t running = 1;
static volatile int lifecycle = HIL_RUNNING;
static FlightState_t state;
static int have_valid_state = 0;
static uint64_t sequence = 0;
static double sim_time_s = 0.0;

typedef struct {
    ModelU_t input;
    HilParameterValues parameters;
    unsigned generation;
} InputSnapshot;
static InputSnapshot pending_live;
static InputSnapshot pending_reset;
static ModelU_t active_input;
static ModelU_t initial_input;
static HilParameterValues active_parameters;
static HilParameterValues initial_parameters;
static unsigned applied_live_generation = 0;
static pthread_mutex_t command_lock = PTHREAD_MUTEX_INITIALIZER;

/* A reset-only write has no truthful effective sequence until reset reaches
 * the next model-step boundary.  Preserve its command identity so C can send
 * a second, final receipt with that actual sequence. */
typedef struct {
    int pending;
    uint64_t parameter_mask;
    char request_id[REQUEST_ID_MAX];
    struct sockaddr_in sender;
} PendingResetReceipt;
static PendingResetReceipt pending_reset_receipt;

typedef struct {
    int active;
    MissionWaypoint waypoints[MISSION_CONTROLLER_MAX_WAYPOINTS];
    unsigned waypoint_count;
    double completion_radius_m;
    unsigned generation;
    char mission_id[MISSION_ID_MAX];
} MissionMetadata;
static MissionMetadata mission;
static unsigned applied_mission_generation = 0;

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

static void add_input_result(struct json_object* results, const char* name,
                             int accepted, const char* reason) {
    struct json_object* detail = json_object_new_object();
    json_object_object_add(detail, "accepted", json_object_new_boolean(accepted));
    json_object_object_add(detail, "reason", json_object_new_string(reason));
    json_object_object_add(results, name, detail);
}

static int parse_input_value(struct json_object* value, const HilInputSpec* spec,
                             double* values) {
    unsigned index;
    if (spec->dimension > MAX_INPUT_VALUE_COUNT) return 0;
    if (spec->dimension == 1) {
        int was_bool = 0;
        if (!valid_number(value, &values[0], &was_bool) || was_bool != spec->is_bool) return 0;
    } else {
        if (!value || json_object_get_type(value) != json_type_array ||
            json_object_array_length(value) != spec->dimension) return 0;
        for (index = 0; index < spec->dimension; ++index) {
            int was_bool = 0;
            if (!valid_number(json_object_array_get_idx(value, index), &values[index], &was_bool) ||
                was_bool != spec->is_bool) return 0;
        }
    }
    for (index = 0; index < spec->dimension; ++index)
        if (values[index] < spec->min_value || values[index] > spec->max_value) return 0;
    return 1;
}

static void parse_set_inputs(struct json_object* root, const char* request_id,
                             const struct sockaddr_in* sender) {
    struct json_object* params = NULL;
    struct json_object* results = json_object_new_object();
    ModelU_t candidate;
    int ok = 1;
    int seen = 0;
    if (!json_object_object_get_ex(root, "params", &params) ||
        json_object_get_type(params) != json_type_object || json_object_object_length(params) == 0) {
        send_receipt(sender, request_id, 0, "params must be a non-empty input-group object", sequence, results);
        return;
    }
    pthread_mutex_lock(&command_lock);
    candidate = pending_live.input;
    json_object_object_foreach(params, group_name, group_value) {
        if (strcmp(group_name, "flight_control") && strcmp(group_name, "environment") && strcmp(group_name, "fault")) {
            add_input_result(results, group_name, 0, "unknown input group"); ok = 0; continue;
        }
        if (json_object_get_type(group_value) != json_type_object || json_object_object_length(group_value) == 0) {
            add_input_result(results, group_name, 0, "input group must be a non-empty object"); ok = 0; continue;
        }
        json_object_object_foreach(group_value, input_name, input_value) {
            char full_name[256];
            const HilInputSpec* spec;
            double values[MAX_INPUT_VALUE_COUNT];
            snprintf(full_name, sizeof(full_name), "%s.%s", group_name, input_name);
            spec = hil_contract_find_input(full_name);
            if (!spec) { add_input_result(results, full_name, 0, "undeclared input"); ok = 0; continue; }
            if (!parse_input_value(input_value, spec, values)) {
                add_input_result(results, full_name, 0, "type, dimension or range violates contract"); ok = 0; continue;
            }
            if (!hil_contract_set_input(&candidate, full_name, values, spec->dimension)) {
                add_input_result(results, full_name, 0, "generated input setter unavailable"); ok = 0; continue;
            }
            add_input_result(results, full_name, 1, "accepted"); seen = 1;
        }
    }
    if (ok && seen) { pending_live.input = candidate; pending_live.generation++; }
    pthread_mutex_unlock(&command_lock);
    send_receipt(sender, request_id, ok && seen,
                 ok && seen ? "accepted" : "atomic input group rejected",
                 ok && seen ? sequence + 1U : sequence, results);
}

static int parse_mission_waypoint(struct json_object* waypoint,
                                  MissionWaypoint* parsed) {
    const char* required[] = {"north_m", "east_m", "down_m", "speed_mps"};
    double values[4];
    unsigned index;
    if (!waypoint || !parsed || json_object_get_type(waypoint) != json_type_object) return 0;
    for (index = 0; index < sizeof(required) / sizeof(required[0]); ++index) {
        struct json_object* value = NULL;
        int was_bool = 0;
        if (!json_object_object_get_ex(waypoint, required[index], &value) ||
            !valid_number(value, &values[index], &was_bool) || was_bool) return 0;
    }
    if (values[3] <= 0.0) return 0;
    parsed->north_m = values[0];
    parsed->east_m = values[1];
    parsed->down_m = values[2];
    parsed->speed_mps = values[3];
    return 1;
}

/* Mission geometry is a fixed external NED request contract.  The C
 * controller turns it into the model's declared motor input; it is never a
 * model-port inference mechanism or a UE4 protocol payload. */
static void parse_load_mission(struct json_object* root, const char* request_id,
                               const struct sockaddr_in* sender) {
    struct json_object *params = NULL, *mission_id = NULL, *waypoints = NULL;
    struct json_object *landing = NULL, *completion_radius = NULL;
    MissionWaypoint parsed[MISSION_CONTROLLER_MAX_WAYPOINTS];
    double radius;
    int radius_was_bool = 0;
    size_t count, index;
    if (!json_object_object_get_ex(root, "params", &params) ||
        json_object_get_type(params) != json_type_object ||
        !json_object_object_get_ex(params, "mission_id", &mission_id) ||
        json_object_get_type(mission_id) != json_type_string ||
        !json_object_object_get_ex(params, "waypoints", &waypoints) ||
        json_object_get_type(waypoints) != json_type_array ||
        !json_object_object_get_ex(params, "landing", &landing) ||
        !json_object_object_get_ex(params, "completion_radius_m", &completion_radius) ||
        !valid_number(completion_radius, &radius, &radius_was_bool) ||
        radius_was_bool || radius <= 0.0) {
        send_receipt(sender, request_id, 0,
                     "mission_id, positive completion radius, NED route and landing are required",
                     sequence, NULL);
        return;
    }
    count = json_object_array_length(waypoints);
    if (count < 3 || count > MISSION_CONTROLLER_MAX_ROUTE_WAYPOINTS) {
        send_receipt(sender, request_id, 0, "waypoint count is outside contract limit", sequence, NULL);
        return;
    }
    for (index = 0; index < count; ++index) {
        if (!parse_mission_waypoint(json_object_array_get_idx(waypoints, index), &parsed[index])) {
            send_receipt(sender, request_id, 0,
                         "waypoint must contain finite north_m/east_m/down_m/speed_mps and positive speed_mps",
                         sequence, NULL);
            return;
        }
    }
    if (!parse_mission_waypoint(landing, &parsed[count])) {
        send_receipt(sender, request_id, 0,
                     "landing must contain finite NED coordinates and positive speed_mps",
                     sequence, NULL);
        return;
    }
    pthread_mutex_lock(&command_lock);
    mission.active = 1;
    memcpy(mission.waypoints, parsed, (count + 1U) * sizeof(parsed[0]));
    mission.waypoint_count = (unsigned)count + 1U;
    mission.completion_radius_m = radius;
    mission.generation++;
    strncpy(mission.mission_id, json_object_get_string(mission_id), sizeof(mission.mission_id) - 1);
    mission.mission_id[sizeof(mission.mission_id) - 1] = '\0';
    pthread_mutex_unlock(&command_lock);
    send_receipt(sender, request_id, 1, "mission accepted as explicit NED route", sequence + 1U, NULL);
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
        !isfinite(candidate->r_radps) || !isfinite(candidate->ax_mps2) ||
        !isfinite(candidate->ay_mps2) || !isfinite(candidate->az_mps2)) return 0;
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
    candidate.ax_mps2 = MODEL_READ_ax_mps2(&output);
    candidate.ay_mps2 = MODEL_READ_ay_mps2(&output);
    candidate.az_mps2 = MODEL_READ_az_mps2(&output);
    candidate.airborne = MODEL_READ_airborne(&output) ? 1 : 0;
    candidate.lifecycle = (uint8_t)lifecycle;
    if (state_is_valid(&candidate)) {
        state = candidate;
        have_valid_state = 1;
    }
    else {
        fprintf(stderr, "[HIL] rejected invalid generated state at sequence %llu\n", (unsigned long long)sequence);
    }
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

static void send_reset_parameter_completion(uint64_t effective_sequence) {
    PendingResetReceipt completion;
    struct json_object* fields;
    unsigned index;
    pthread_mutex_lock(&command_lock);
    if (!pending_reset_receipt.pending) { pthread_mutex_unlock(&command_lock); return; }
    completion = pending_reset_receipt;
    pending_reset_receipt.pending = 0;
    pthread_mutex_unlock(&command_lock);
    fields = json_object_new_object();
    for (index = 0; index < HIL_PARAMETER_COUNT && index < 64U; ++index) {
        if (completion.parameter_mask & (1ULL << index)) {
            struct json_object* detail = json_object_new_object();
            json_object_object_add(detail, "accepted", json_object_new_boolean(1));
            json_object_object_add(detail, "reason", json_object_new_string("applied on reset"));
            json_object_object_add(detail, "effective_sequence", json_object_new_int64((int64_t)effective_sequence));
            json_object_object_add(fields, HIL_PARAMETER_SPECS[index].name, detail);
        }
    }
    send_receipt(&completion.sender, completion.request_id, 1,
                 "reset_only parameters applied", effective_sequence, fields);
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
        if (lifecycle != HIL_RUNNING) valid = 0;
        else lifecycle = HIL_PAUSED;
    } else if (request.event == HIL_RUNNING) {
        if (lifecycle != HIL_PAUSED) valid = 0; else lifecycle = HIL_RUNNING;
    } else if (request.event == HIL_ENDED) {
        if (lifecycle != HIL_RUNNING && lifecycle != HIL_PAUSED) valid = 0;
        else {
            lifecycle = HIL_ENDED;
            pthread_mutex_lock(&command_lock);
            mission.active = 0;
            mission.waypoint_count = 0;
            mission.mission_id[0] = '\0';
            mission.generation++;
            applied_mission_generation = mission.generation;
            pthread_mutex_unlock(&command_lock);
            mission_controller_reset();
        }
    } else if (request.event == HIL_RESETTING) {
        if (lifecycle != HIL_PAUSED && lifecycle != HIL_ENDED && lifecycle != HIL_RUNNING) valid = 0;
        else {
            lifecycle = HIL_RESETTING;
            /* Never publish a stale pre-reset state while the new model has
             * not yet emitted a valid normalized state. */
            have_valid_state = 0;
            model_terminate();
            model_initialize();
            active_input = initial_input;
            active_parameters = initial_parameters;
            if (pending_reset.generation) active_input = pending_reset.input;
            if (pending_reset.generation) active_parameters = pending_reset.parameters;
            *model_get_input() = active_input;
            hil_contract_apply_exported_globals(&active_parameters);
            pending_live.input = active_input;
            pending_live.parameters = active_parameters;
            pending_live.generation++;
            pending_reset.generation = 0;
            pthread_mutex_lock(&command_lock);
            mission.active = 0;
            mission.waypoint_count = 0;
            mission.mission_id[0] = '\0';
            mission.generation++;
            applied_mission_generation = mission.generation;
            pthread_mutex_unlock(&command_lock);
            mission_controller_reset();
            lifecycle = HIL_RUNNING;
            populate_state();
            /* The reset call occurs before this loop's model_step(); that
             * next step is the contractual parameter effect boundary. */
            send_reset_parameter_completion(sequence + 1U);
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
        active_parameters = snapshot.parameters;
        *model_get_input() = active_input;
        hil_contract_apply_exported_globals(&active_parameters);
        applied_live_generation = snapshot.generation;
    }
}

static void apply_mission_update(void) {
    MissionMetadata snapshot;
    pthread_mutex_lock(&command_lock);
    snapshot = mission;
    pthread_mutex_unlock(&command_lock);
    if (snapshot.generation == applied_mission_generation) return;
    if (snapshot.active) {
        if (!mission_controller_load(snapshot.waypoints, snapshot.waypoint_count,
                                     snapshot.completion_radius_m)) {
            fprintf(stderr, "[HIL] rejected invalid pending mission snapshot\n");
        }
    } else {
        mission_controller_reset();
    }
    applied_mission_generation = snapshot.generation;
}

static void write_motor_command(const float motor[4]) {
    double values[4];
    unsigned index;
    for (index = 0; index < 4; ++index) values[index] = motor[index];
    if (!hil_contract_set_input(&active_input, "flight_control.motor_command", values, 4U)) {
        fprintf(stderr, "[HIL] generated motor command setter unavailable\n");
        running = 0;
        return;
    }
    *model_get_input() = active_input;
}

static void zero_motor_command(void) {
    const float motor[4] = {0.0f, 0.0f, 0.0f, 0.0f};
    write_motor_command(motor);
}

/* Reset restores all ordinary model inputs to their contract defaults, while
 * retaining the current values of explicitly live parameters.  Reset-only
 * values are then layered onto this snapshot by parse_tune(). */
static int reset_snapshot_from_initial(ModelU_t* input, HilParameterValues* parameters) {
    unsigned index;
    *input = initial_input;
    *parameters = initial_parameters;
    for (index = 0; index < HIL_PARAMETER_COUNT; ++index) {
        const HilParameterSpec* spec = &HIL_PARAMETER_SPECS[index];
        if (spec->klass != HIL_PARAM_LIVE) continue;
        if (!hil_contract_set_parameter(input, parameters, spec->name,
                                        active_parameters.value[index])) return 0;
    }
    return 1;
}

static void parse_tune(struct json_object* root, const char* request_id,
                       const struct sockaddr_in* sender) {
    struct json_object *params = NULL;
    struct json_object* field_results = json_object_new_object();
    ModelU_t live_candidate, reset_candidate;
    HilParameterValues live_parameters, reset_parameters;
    int ok = 1, has_live = 0, has_reset = 0, reset_slot_busy;
    uint64_t reset_parameter_mask = 0;
    if (!json_object_object_get_ex(root, "params", &params) ||
        json_object_get_type(params) != json_type_object || json_object_object_length(params) == 0) {
        send_receipt(sender, request_id, 0, "params must be a non-empty object", sequence, field_results); return;
    }
    pthread_mutex_lock(&command_lock);
    live_candidate = pending_live.input;
    live_parameters = pending_live.parameters;
    if (pending_reset.generation) {
        reset_candidate = pending_reset.input;
        reset_parameters = pending_reset.parameters;
    } else if (!reset_snapshot_from_initial(&reset_candidate, &reset_parameters)) {
        pthread_mutex_unlock(&command_lock);
        send_receipt(sender, request_id, 0, "cannot construct reset input snapshot", sequence, field_results);
        return;
    }
    reset_slot_busy = pending_reset_receipt.pending;
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
        else if (spec->klass == HIL_PARAM_LIVE) { has_live = 1; if (!hil_contract_set_parameter(&live_candidate, &live_parameters, name, number)) { ok = 0; reason = "generated setter unavailable"; } }
        else {
            unsigned parameter_index = (unsigned)(spec - HIL_PARAMETER_SPECS);
            has_reset = 1;
            if (reset_slot_busy) { ok = 0; reason = "previous reset-only group is pending"; }
            else if (parameter_index >= 64U) { ok = 0; reason = "too many reset-only parameters"; }
            else {
                reset_parameter_mask |= 1ULL << parameter_index;
                if (!hil_contract_set_parameter(&reset_candidate, &reset_parameters, name, number)) { ok = 0; reason = "generated setter unavailable"; }
            }
        }
        json_object_object_add(detail, "accepted", json_object_new_boolean(!strcmp(reason, "accepted")));
        json_object_object_add(detail, "reason", json_object_new_string(reason));
        json_object_object_add(field_results, name, detail);
    }
    if (ok) {
        if (has_live) { pending_live.input = live_candidate; pending_live.parameters = live_parameters; pending_live.generation++; }
        if (has_reset) {
            pending_reset.input = reset_candidate; pending_reset.parameters = reset_parameters; pending_reset.generation++;
            pending_reset_receipt.pending = 1;
            pending_reset_receipt.parameter_mask = reset_parameter_mask;
            strncpy(pending_reset_receipt.request_id, request_id, sizeof(pending_reset_receipt.request_id) - 1);
            pending_reset_receipt.request_id[sizeof(pending_reset_receipt.request_id) - 1] = '\0';
            pending_reset_receipt.sender = *sender;
        }
    }
    pthread_mutex_unlock(&command_lock);
    send_receipt(sender, request_id, ok, ok ? (has_reset ? "queued for reset" : "accepted") : "atomic parameter group rejected",
                 ok && has_live ? sequence + 1U : (ok && has_reset ? 0U : sequence), field_results);
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
    else if (!strcmp(command, "set_inputs")) parse_set_inputs(root, request_id, sender);
    else if (!strcmp(command, "load_mission")) parse_load_mission(root, request_id, sender);
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
    float mission_motor[4] = {0.0f, 0.0f, 0.0f, 0.0f};
    signal(SIGINT, on_signal); signal(SIGTERM, on_signal);
    if (hil_realtime_init(90) != 0) {
        fprintf(stderr, "[HIL] SCHED_FIFO/locked memory unavailable; refusing production start\n");
        return 1;
    }
    if (udp_init(UDP_CMD_PORT, UDP_STATUS_PORT) != 0) { fprintf(stderr, "UDP initialization failed\n"); return 1; }
    model_initialize();
    initial_input = *model_get_input();
    memset(&initial_parameters, 0, sizeof(initial_parameters));
    hil_contract_apply_defaults(&initial_input, &initial_parameters);
    active_input = initial_input;
    active_parameters = initial_parameters;
    *model_get_input() = active_input;
    hil_contract_apply_exported_globals(&active_parameters);
    pending_live.input = active_input; pending_live.parameters = active_parameters;
    pending_reset.input = active_input; pending_reset.parameters = active_parameters;
    populate_state();
    if (pthread_create(&command_worker, NULL, command_thread, NULL) != 0) { model_terminate(); udp_close(); return 1; }
    clock_gettime(CLOCK_MONOTONIC, &next);
    while (running) {
        next.tv_nsec += STEP_NS; if (next.tv_nsec >= 1000000000L) { next.tv_sec++; next.tv_nsec -= 1000000000L; }
        apply_lifecycle_request();
        if (lifecycle == HIL_RUNNING) {
            apply_live_update();
            apply_mission_update();
            mission_controller_step(have_valid_state ? &state : NULL, 0.001,
                                    mission_motor);
            write_motor_command(mission_motor);
            model_step(); sequence++; sim_time_s += 0.001; populate_state();
        } else {
            zero_motor_command();
            if (have_valid_state) state.lifecycle = (uint8_t)lifecycle;
        }
        if (++send_counter >= SEND_INTERVAL) {
            if (have_valid_state) { udp_send_status(&state); udp_send_monitor(&state); }
            send_counter = 0;
        }
        clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL);
        { struct timespec now; clock_gettime(CLOCK_MONOTONIC, &now);
          { int64_t lateness = (int64_t)(now.tv_sec - next.tv_sec) * 1000000000LL + now.tv_nsec - next.tv_nsec;
            hil_realtime_record_deadline(lateness); } }
    }
    { HilRealtimeStats stats = hil_realtime_stats();
      fprintf(stderr, "[HIL] realtime samples=%llu p99_abs_lateness_ns=%lld max_abs_lateness_ns=%lld over_250us=%llu non_realtime=%d\n",
              (unsigned long long)stats.samples, (long long)stats.p99_abs_lateness_ns, (long long)stats.max_abs_lateness_ns,
              (unsigned long long)stats.over_250us, stats.non_realtime); }
    pthread_join(command_worker, NULL); model_terminate(); udp_close(); return 0;
}

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
#include "fixed_wing_v3_tcp.h"
#include "control_arbiter.h"
#include "local_udp.h"
#include "mission_controller.h"
#include "model_rt_wrapper.h"
#include "model_contract.h"
#include "realtime.h"

#ifndef HIL_MODEL_ID
#define HIL_MODEL_ID ""
#endif

/* Existing V2 generated artifacts remain deployable until their next ERT
 * rebuild.  New V3 artifacts provide the same API from build_script.m. */
#ifndef HIL_ACTUATOR_COUNT
#define HIL_ACTUATOR_COUNT 4U
typedef struct { double min_value; double max_value; double safe_value; } HilActuatorSpec;
static const HilActuatorSpec HIL_ACTUATOR_SPECS[HIL_ACTUATOR_COUNT] = {
    {0.0, 1.0, 0.0}, {0.0, 1.0, 0.0}, {0.0, 1.0, 0.0}, {0.0, 1.0, 0.0}
};
#define HIL_CONTROL_SOURCE_MASK 7U
static int hil_contract_set_actuators(ModelU_t* input, const double* values,
                                      unsigned count) {
    return hil_contract_set_input(input, "flight_control.motor_command", values, count);
}
#endif

#ifndef HIL_CONTRACT_GET_INPUT
static int hil_contract_get_input(const ModelU_t* input, const char* name,
                                  double* values, unsigned count) {
    (void)input; (void)name; (void)values; (void)count;
    return 0;
}
#endif

#ifdef HIL_CONTRACT_INITIAL_STATE
#define HIL_INITIAL_STATE_ABI_AVAILABLE 1
#else
#define HIL_INITIAL_STATE_ABI_AVAILABLE 0
#endif

/* A complete RunConfigure requires generated ExtU/parameter setters plus the
 * verified DWork initial-state mapping.  The local HIL gateway resolves
 * resource bytes before calling this loopback-only boundary. */
#define HIL_FULL_CONFIGURATION_ABI_AVAILABLE HIL_INITIAL_STATE_ABI_AVAILABLE

/* V2 generated headers do not describe V3 fixed-wing projection metadata. */
#ifndef HIL_FIXED_WING
#define HIL_FIXED_WING 0
#endif
#ifndef HIL_FIXED_WING_V3_TCP
#define HIL_FIXED_WING_V3_TCP 0
#endif
#ifndef HIL_READ_WIND_N_MPS
#define HIL_READ_WIND_N_MPS(u) (0.0)
#define HIL_READ_WIND_E_MPS(u) (0.0)
#define HIL_READ_WIND_D_MPS(u) (0.0)
#endif
#ifndef HIL_READ_THROTTLE
#define HIL_READ_THROTTLE(u) (0.0)
#endif
#ifndef HIL_READ_FAULT_ACTIVE
#define HIL_READ_FAULT_ACTIVE(u) (0)
#endif
#ifndef HIL_TAKEOFF_THROTTLE_MIN
#define HIL_TAKEOFF_THROTTLE_MIN 0.05
#endif
#ifndef HIL_LANDING_THROTTLE_MAX
#define HIL_LANDING_THROTTLE_MAX 0.05
#endif
#ifndef HIL_TAS_MIN_MPS
#define HIL_TAS_MIN_MPS 0.1
#endif
#ifndef HIL_READ_FLIGHT_PHASE_MODEL
/* A negative value means the model does not authoritatively publish a phase. */
#define HIL_READ_FLIGHT_PHASE_MODEL(y) (-1)
#endif
#ifndef HIL_READ_AILERON_RAD
#define HIL_SURFACE_OUTPUT_VALID 0
#define HIL_READ_AILERON_RAD(u,y) (0.0)
#define HIL_READ_ELEVATOR_RAD(u,y) (0.0)
#define HIL_READ_RUDDER_RAD(u,y) (0.0)
#endif

#define STEP_NS 1000000L
#define UDP_CMD_PORT 9997
#define UDP_STATUS_PORT 9998
#define SEND_INTERVAL 20U
#define REQUEST_ID_MAX 96
#define MISSION_ID_MAX 128
#define MAX_INPUT_VALUE_COUNT 32U
#define EXTERNAL_CONTROL_TIMEOUT_NS 100000000ULL
#define ICD_ENVIRONMENT_FIELD_COUNT 6U
#define ICD_FAULT_FIELD_COUNT 13U
#define ICD_ENVIRONMENT_MAX_LOOKAHEAD_STEPS 1000U
#define SENSOR_HISTORY_STEPS 1001U

static int control_source_allowed(ControlSource source) {
    return source != CONTROL_SOURCE_NONE &&
           (HIL_CONTROL_SOURCE_MASK & (1U << ((unsigned)source - 1U))) != 0U;
}

static volatile sig_atomic_t running = 1;
/* Model initialisation alone does not authorise stepping.  The process is
 * deliberately inert until a verified configuration has completed. */
static volatile int lifecycle = HIL_STOPPED;
static FlightStateV3_t state;
static int have_valid_state = 0;
static uint64_t sequence = 0;
static double sim_time_s = 0.0;
static float prior_p_radps, prior_q_radps, prior_r_radps;
static int prior_rates_valid = 0;
static int fixed_wing_has_taken_off = 0;
static FlightStateV3_t sensor_truth_history[SENSOR_HISTORY_STEPS];
static uint8_t sensor_truth_valid[SENSOR_HISTORY_STEPS];
static double sensor_loss_accumulator = 0.0;

static void zero_motor_command(void);
static void populate_state(void);
static void record_sensor_truth(void);

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
static struct json_object* configured_configuration = NULL;
static uint32_t configured_model_revision = 0;
static pthread_mutex_t command_lock = PTHREAD_MUTEX_INITIALIZER;
/* Serializes model-boundary transitions against atomic configuration. */
static pthread_mutex_t model_boundary_lock = PTHREAD_MUTEX_INITIALIZER;
static ControlArbiter control_arbiter;

/* The ICD consumer owns this one-slot, target-step transaction separately
 * from the legacy live-input command.  A terminal result is retained until a
 * later transaction replaces it, so the gateway can read a model-boundary
 * receipt rather than inferring application from a UDP accept response. */
typedef enum {
    ICD_ENVIRONMENT_EMPTY = 0,
    ICD_ENVIRONMENT_STAGED,
    ICD_ENVIRONMENT_APPLIED,
    ICD_ENVIRONMENT_REJECTED
} IcdEnvironmentState;

typedef struct {
    IcdEnvironmentState state;
    char stage_request_id[REQUEST_ID_MAX];
    char reason[64];
    uint64_t target_step;
    uint64_t deadline_ns;
    uint64_t applied_step;
    uint64_t model_revision;
    double values[ICD_ENVIRONMENT_FIELD_COUNT];
    double readback[ICD_ENVIRONMENT_FIELD_COUNT];
} IcdEnvironmentStage;

static const char* const ICD_ENVIRONMENT_FIELDS[ICD_ENVIRONMENT_FIELD_COUNT] = {
    "environment.wind_n_mps", "environment.wind_e_mps", "environment.wind_d_mps",
    "environment.pressure_pa", "environment.temperature_k", "environment.ground_height_m"
};
static IcdEnvironmentStage icd_environment;
static uint64_t icd_environment_revision = 0;

/* ID11 is an atomic fault snapshot.  It deliberately has its own target-step
 * transaction so an operator cannot mistake the legacy set_inputs receipt for
 * evidence that the generated model observed all fault fields together. */
typedef struct {
    IcdEnvironmentState state;
    char stage_request_id[REQUEST_ID_MAX];
    char reason[64];
    uint64_t target_step;
    uint64_t deadline_ns;
    uint64_t applied_step;
    uint64_t model_revision;
    double values[ICD_FAULT_FIELD_COUNT];
    double readback[ICD_FAULT_FIELD_COUNT];
} IcdFaultStage;
static const char* const ICD_FAULT_FIELDS[ICD_FAULT_FIELD_COUNT] = {
    "fault.gps_bias_n_m", "fault.gps_bias_e_m", "fault.gps_bias_d_m",
    "fault.imu_bias_p_radps", "fault.imu_bias_q_radps", "fault.imu_bias_r_radps",
    "fault.motor_1_failed", "fault.motor_2_failed", "fault.motor_3_failed",
    "fault.motor_4_failed", "fault.command_delay_ms", "fault.sensor_delay_ms",
    "fault.packet_loss_ratio"
};
static IcdFaultStage icd_fault;
static uint64_t icd_fault_revision = 0;

/* Flight-control commits are kept apart from environment staging because the
 * motor command has a final control-arbiter write later in each loop. */
typedef struct {
    IcdEnvironmentState state;
    char stage_request_id[REQUEST_ID_MAX];
    char reason[64];
    uint64_t target_step;
    uint64_t deadline_ns;
    uint64_t applied_step;
    uint64_t model_revision;
    double values[HIL_ACTUATOR_COUNT ? HIL_ACTUATOR_COUNT : 1];
    double readback[HIL_ACTUATOR_COUNT ? HIL_ACTUATOR_COUNT : 1];
} IcdFlightStage;
static IcdFlightStage icd_flight;
static uint64_t icd_flight_revision = 0;

/* Contract-driven transaction slots used by all three vehicle models.  The
 * generated registry is the authority for group membership, scalar/array
 * dimensions, boolean types and ranges.  Keeping one slot per group permits
 * a complete flight/environment/fault/parameter snapshot to share a target
 * boundary without partial writes. */
typedef enum {
    ICD_GROUP_FLIGHT_CONTROL = 0,
    ICD_GROUP_ENVIRONMENT = 1,
    ICD_GROUP_FAULT = 2,
    ICD_GROUP_PARAMETERS = 3,
    ICD_GROUP_COUNT = 4
} IcdBindingGroup;

typedef struct {
    IcdEnvironmentState state;
    char stage_request_id[REQUEST_ID_MAX];
    char reason[64];
    uint64_t target_step;
    uint64_t deadline_ns;
    uint64_t applied_step;
    uint64_t model_revision;
    unsigned field_count;
    unsigned spec_indices[HIL_INPUT_COUNT + HIL_PARAMETER_COUNT + 1U];
    unsigned dimensions[HIL_INPUT_COUNT + HIL_PARAMETER_COUNT + 1U];
    double values[HIL_INPUT_COUNT + HIL_PARAMETER_COUNT + 1U][MAX_INPUT_VALUE_COUNT];
    double readback[HIL_INPUT_COUNT + HIL_PARAMETER_COUNT + 1U][MAX_INPUT_VALUE_COUNT];
} IcdBindingStage;

static IcdBindingStage icd_binding_groups[ICD_GROUP_COUNT];
static uint64_t icd_binding_revisions[ICD_GROUP_COUNT];

/* This measures process-local command-to-status latency with CLOCK_MONOTONIC:
 * UDP command receipt -> command effective at a model boundary -> completion
 * of the first UDP state send that contains that boundary.  Commands replaced
 * before either boundary are counted as coalesced, never as low-latency wins. */
typedef enum {
    HIL_LATENCY_LIVE_INPUT = 0,
    HIL_LATENCY_MISSION = 1,
    HIL_LATENCY_LANE_COUNT = 2
} HilLatencyLane;

typedef struct {
    uint64_t accepted;
    uint64_t coalesced;
    uint64_t samples;
    uint64_t sum_ns;
    uint64_t max_ns;
    uint64_t min_ns;
    uint64_t histogram[1001]; /* 100 us buckets, final bucket >= 100 ms. */
    int awaiting_apply;
    int awaiting_output;
    unsigned generation;
    uint64_t ingress_ns;
    uint64_t applied_ns;
} CommandLatency;
static CommandLatency command_latency[HIL_LATENCY_LANE_COUNT];
static uint64_t command_ingress_ns;

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
    int target_bound;
    uint64_t target_step;
    char request_id[REQUEST_ID_MAX];
    struct sockaddr_in sender;
} LifecycleRequest;
static LifecycleRequest lifecycle_request;

static uint64_t monotonic_time_ns(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (uint64_t)now.tv_sec * 1000000000ULL + (uint64_t)now.tv_nsec;
}

/* Defaults are the deployed contract ports.  Explicit high ports keep a
 * local acceptance process isolated from a running verified deployment. */
static unsigned short configured_udp_port(const char* name, unsigned short fallback) {
    const char* text = getenv(name);
    char* end = NULL;
    unsigned long value;
    if (!text || !*text) return fallback;
    value = strtoul(text, &end, 10);
    if (!end || *end || value < 1UL || value > 65535UL) return fallback;
    return (unsigned short)value;
}

/* command_lock must be held by the caller. */
static void latency_accept_locked(HilLatencyLane lane, unsigned generation,
                                  uint64_t ingress_ns) {
    CommandLatency* latency = &command_latency[lane];
    if (latency->awaiting_apply || latency->awaiting_output) latency->coalesced++;
    latency->accepted++;
    latency->awaiting_apply = 1;
    latency->awaiting_output = 0;
    latency->generation = generation;
    latency->ingress_ns = ingress_ns;
    latency->applied_ns = 0;
}

static void latency_mark_applied(HilLatencyLane lane, unsigned generation) {
    CommandLatency* latency = &command_latency[lane];
    pthread_mutex_lock(&command_lock);
    if (latency->awaiting_apply && latency->generation == generation) {
        latency->awaiting_apply = 0;
        latency->awaiting_output = 1;
        latency->applied_ns = monotonic_time_ns();
    }
    pthread_mutex_unlock(&command_lock);
}

static uint64_t latency_percentile_ns(const CommandLatency* latency,
                                      unsigned percentile) {
    uint64_t cumulative = 0;
    const uint64_t target = (latency->samples * percentile + 99U) / 100U;
    unsigned index;
    for (index = 0; index < 1001U; ++index) {
        cumulative += latency->histogram[index];
        if (cumulative >= target) return (uint64_t)index * 100000ULL;
    }
    return 100000000ULL;
}

static void latency_record_output_completed(void) {
    uint64_t now_ns = monotonic_time_ns();
    unsigned lane;
    pthread_mutex_lock(&command_lock);
    for (lane = 0; lane < HIL_LATENCY_LANE_COUNT; ++lane) {
        CommandLatency* latency = &command_latency[lane];
        uint64_t elapsed_ns;
        unsigned bucket;
        if (!latency->awaiting_output) continue;
        elapsed_ns = now_ns - latency->ingress_ns;
        bucket = elapsed_ns / 100000ULL > 1000ULL ? 1000U :
                 (unsigned)(elapsed_ns / 100000ULL);
        latency->samples++;
        latency->sum_ns += elapsed_ns;
        if (elapsed_ns > latency->max_ns) latency->max_ns = elapsed_ns;
        if (!latency->min_ns || elapsed_ns < latency->min_ns) latency->min_ns = elapsed_ns;
        latency->histogram[bucket]++;
        latency->awaiting_output = 0;
    }
    pthread_mutex_unlock(&command_lock);
}

static void latency_report(void) {
    static const char* const lane_name[] = {"live_input", "mission"};
    unsigned lane;
    pthread_mutex_lock(&command_lock);
    for (lane = 0; lane < HIL_LATENCY_LANE_COUNT; ++lane) {
        const CommandLatency* latency = &command_latency[lane];
        const uint64_t average_ns = latency->samples ? latency->sum_ns / latency->samples : 0;
        fprintf(stderr,
                "[HIL] command_latency lane=%s accepted=%llu samples=%llu coalesced=%llu "
                "pending=%d avg_ns=%llu p50_ns=%llu p95_ns=%llu p99_ns=%llu max_ns=%llu\n",
                lane_name[lane], (unsigned long long)latency->accepted,
                (unsigned long long)latency->samples, (unsigned long long)latency->coalesced,
                latency->awaiting_apply || latency->awaiting_output,
                (unsigned long long)average_ns,
                (unsigned long long)latency_percentile_ns(latency, 50U),
                (unsigned long long)latency_percentile_ns(latency, 95U),
                (unsigned long long)latency_percentile_ns(latency, 99U),
                (unsigned long long)latency->max_ns);
    }
    pthread_mutex_unlock(&command_lock);
}

static void on_signal(int ignored) { (void)ignored; running = 0; }

static const char* lifecycle_name(int value) {
    switch (value) {
    case HIL_RUNNING: return "RUNNING";
    case HIL_PAUSED: return "PAUSED";
    case HIL_RESETTING: return "RESETTING";
    case HIL_ENDED: return "ENDED";
    case HIL_CONFIGURED: return "CONFIGURED";
    case HIL_STOPPED: return "STOPPED";
    case HIL_FAILED: return "FAILED";
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

static int json_uint64(struct json_object* value, uint64_t* parsed) {
    int64_t candidate;
    if (!value || !parsed || json_object_get_type(value) != json_type_int) return 0;
    candidate = json_object_get_int64(value);
    if (candidate < 0) return 0;
    *parsed = (uint64_t)candidate;
    return 1;
}

static const char* icd_environment_state_name(IcdEnvironmentState state_value);

static const char* icd_binding_group_name(IcdBindingGroup group) {
    static const char* const names[ICD_GROUP_COUNT] = {
        "flight_control", "environment", "fault", "parameters"
    };
    return group < ICD_GROUP_COUNT ? names[group] : NULL;
}

static int icd_binding_group_from_name(const char* name, IcdBindingGroup* group) {
    unsigned index;
    if (!name || !group) return 0;
    for (index = 0; index < ICD_GROUP_COUNT; ++index) {
        if (!strcmp(name, icd_binding_group_name((IcdBindingGroup)index))) {
            *group = (IcdBindingGroup)index;
            return 1;
        }
    }
    return 0;
}

static unsigned icd_binding_group_field_count(IcdBindingGroup group) {
    unsigned count = 0, index;
    const char* group_name = icd_binding_group_name(group);
    size_t prefix_length;
    if (!group_name) return 0;
    if (group == ICD_GROUP_PARAMETERS) return HIL_PARAMETER_COUNT;
    prefix_length = strlen(group_name);
    for (index = 0; index < HIL_INPUT_COUNT; ++index) {
        if (!strncmp(HIL_INPUT_SPECS[index].name, group_name, prefix_length) &&
            HIL_INPUT_SPECS[index].name[prefix_length] == '.') count++;
    }
    return count;
}

static struct json_object* icd_json_value(const double* values, unsigned dimension,
                                          int is_bool) {
    struct json_object* result;
    unsigned index;
    if (dimension == 1U)
        return is_bool ? json_object_new_boolean(values[0] != 0.0)
                       : json_object_new_double(values[0]);
    result = json_object_new_array();
    for (index = 0; index < dimension; ++index)
        json_object_array_add(result, is_bool ? json_object_new_boolean(values[index] != 0.0)
                                              : json_object_new_double(values[index]));
    return result;
}

static struct json_object* icd_binding_stage_fields(IcdBindingGroup group,
                                                     const IcdBindingStage* snapshot) {
    struct json_object* fields = json_object_new_object();
    struct json_object* readback = json_object_new_object();
    unsigned item;
    json_object_object_add(fields, "state",
                           json_object_new_string(icd_environment_state_name(snapshot->state)));
    json_object_object_add(fields, "stage_request_id",
                           json_object_new_string(snapshot->stage_request_id));
    json_object_object_add(fields, "group", json_object_new_string(icd_binding_group_name(group)));
    json_object_object_add(fields, "target_step", json_object_new_int64((int64_t)snapshot->target_step));
    json_object_object_add(fields, "applied_step", json_object_new_int64((int64_t)snapshot->applied_step));
    json_object_object_add(fields, "model_revision", json_object_new_int64((int64_t)snapshot->model_revision));
    json_object_object_add(fields, "reason", json_object_new_string(snapshot->reason));
    if (snapshot->state != ICD_ENVIRONMENT_APPLIED) {
        json_object_put(readback);
        return fields;
    }
    for (item = 0; item < snapshot->field_count; ++item) {
        const char* name;
        int is_bool;
        if (group == ICD_GROUP_PARAMETERS) {
            const HilParameterSpec* spec = &HIL_PARAMETER_SPECS[snapshot->spec_indices[item]];
            name = spec->name;
            is_bool = spec->is_bool;
        } else {
            const HilInputSpec* spec = &HIL_INPUT_SPECS[snapshot->spec_indices[item]];
            name = strchr(spec->name, '.') + 1;
            is_bool = spec->is_bool;
        }
        json_object_object_add(readback, name,
            icd_json_value(snapshot->readback[item], snapshot->dimensions[item], is_bool));
    }
    json_object_object_add(fields, "readback", readback);
    return fields;
}

/* Generic target-step staging for the complete frozen binding group.  It is
 * intentionally additive to the original ID7/10/11 commands so deployed
 * quadrotor clients remain compatible while the 97-binding path is shared by
 * quadrotor, six-rotor and fixed-wing targets. */
static void parse_stage_icd_group(struct json_object* root, const char* request_id,
                                  const struct sockaddr_in* sender) {
    struct json_object *params = NULL, *target = NULL, *deadline = NULL;
    struct json_object *group_value = NULL, *values = NULL;
    IcdBindingStage staged;
    IcdBindingGroup group;
    uint64_t target_step, deadline_ns;
    unsigned expected, item = 0, index;
    uint64_t now_ns = monotonic_time_ns();
    if (!json_object_object_get_ex(root, "params", &params) ||
        json_object_get_type(params) != json_type_object ||
        !json_object_object_get_ex(params, "target_step", &target) ||
        !json_object_object_get_ex(params, "deadline_ns", &deadline) ||
        !json_object_object_get_ex(params, "group", &group_value) ||
        json_object_get_type(group_value) != json_type_string ||
        !json_object_object_get_ex(params, "values", &values) ||
        json_object_get_type(values) != json_type_object ||
        !json_uint64(target, &target_step) || !json_uint64(deadline, &deadline_ns) ||
        !icd_binding_group_from_name(json_object_get_string(group_value), &group)) {
        send_receipt(sender, request_id, 0, "complete target_step, deadline_ns, group and values are required",
                     sequence, NULL);
        return;
    }
    expected = icd_binding_group_field_count(group);
    if (!expected || json_object_object_length(values) != expected ||
        lifecycle != HIL_RUNNING || deadline_ns <= now_ns || target_step <= sequence ||
        target_step > sequence + ICD_ENVIRONMENT_MAX_LOOKAHEAD_STEPS) {
        send_receipt(sender, request_id, 0, "complete binding group or admissible target is required",
                     sequence, NULL);
        return;
    }
    memset(&staged, 0, sizeof(staged));
    staged.target_step = target_step;
    staged.deadline_ns = deadline_ns;
    if (group == ICD_GROUP_PARAMETERS) {
        for (index = 0; index < HIL_PARAMETER_COUNT; ++index) {
            const HilParameterSpec* spec = &HIL_PARAMETER_SPECS[index];
            struct json_object* value = NULL;
            double number;
            int was_bool = 0;
            if (spec->klass == HIL_PARAM_READONLY ||
                !json_object_object_get_ex(values, spec->name, &value) ||
                !valid_number(value, &number, &was_bool) || was_bool != spec->is_bool ||
                number < spec->min_value || number > spec->max_value) {
                send_receipt(sender, request_id, 0, "parameter type, field set, class or range violates contract",
                             sequence, NULL);
                return;
            }
            staged.spec_indices[item] = index;
            staged.dimensions[item] = 1U;
            staged.values[item][0] = number;
            item++;
        }
    } else {
        const char* group_name = icd_binding_group_name(group);
        const size_t prefix_length = strlen(group_name);
        for (index = 0; index < HIL_INPUT_COUNT; ++index) {
            const HilInputSpec* spec = &HIL_INPUT_SPECS[index];
            struct json_object* value = NULL;
            if (strncmp(spec->name, group_name, prefix_length) || spec->name[prefix_length] != '.') continue;
            if (spec->dimension > MAX_INPUT_VALUE_COUNT ||
                !json_object_object_get_ex(values, spec->name + prefix_length + 1U, &value) ||
                !parse_input_value(value, spec, staged.values[item])) {
                send_receipt(sender, request_id, 0, "input type, field set, dimension or range violates contract",
                             sequence, NULL);
                return;
            }
            staged.spec_indices[item] = index;
            staged.dimensions[item] = spec->dimension;
            item++;
        }
    }
    if (item != expected) {
        send_receipt(sender, request_id, 0, "generated binding registry is incomplete", sequence, NULL);
        return;
    }
    staged.field_count = item;
    staged.state = ICD_ENVIRONMENT_STAGED;
    strncpy(staged.stage_request_id, request_id, sizeof(staged.stage_request_id) - 1U);
    strncpy(staged.reason, "awaiting target boundary", sizeof(staged.reason) - 1U);
    pthread_mutex_lock(&command_lock);
    if (icd_binding_groups[group].state == ICD_ENVIRONMENT_STAGED) {
        pthread_mutex_unlock(&command_lock);
        send_receipt(sender, request_id, 0, "previous ICD binding transaction is pending", sequence, NULL);
        return;
    }
    icd_binding_groups[group] = staged;
    pthread_mutex_unlock(&command_lock);
    send_receipt(sender, request_id, 1, "staged", target_step, NULL);
}

static void parse_get_icd_group_result(struct json_object* root, const char* request_id,
                                       const struct sockaddr_in* sender) {
    struct json_object *params = NULL, *stage_request = NULL, *group_value = NULL;
    IcdBindingStage snapshot;
    IcdBindingGroup group;
    if (!json_object_object_get_ex(root, "params", &params) ||
        json_object_get_type(params) != json_type_object ||
        !json_object_object_get_ex(params, "stage_request_id", &stage_request) ||
        json_object_get_type(stage_request) != json_type_string ||
        !json_object_object_get_ex(params, "group", &group_value) ||
        json_object_get_type(group_value) != json_type_string ||
        !icd_binding_group_from_name(json_object_get_string(group_value), &group)) {
        send_receipt(sender, request_id, 0, "params.group and stage_request_id are required", sequence, NULL);
        return;
    }
    pthread_mutex_lock(&command_lock);
    snapshot = icd_binding_groups[group];
    pthread_mutex_unlock(&command_lock);
    if (snapshot.state == ICD_ENVIRONMENT_EMPTY ||
        strcmp(snapshot.stage_request_id, json_object_get_string(stage_request))) {
        send_receipt(sender, request_id, 0, "unknown ICD binding transaction", sequence, NULL);
        return;
    }
    send_receipt(sender, request_id, snapshot.state != ICD_ENVIRONMENT_REJECTED,
                 snapshot.reason, snapshot.applied_step ? snapshot.applied_step : sequence,
                 icd_binding_stage_fields(group, &snapshot));
}

static void parse_get_icd_snapshot(struct json_object* root, const char* request_id,
                                   const struct sockaddr_in* sender) {
    struct json_object *params = NULL, *which = NULL;
    struct json_object* fields = json_object_new_object();
    struct json_object* inputs = json_object_new_object();
    struct json_object* groups[3];
    struct json_object* parameters = json_object_new_object();
    ModelU_t input_snapshot;
    HilParameterValues parameter_snapshot;
    const char* snapshot_name;
    unsigned index;
    groups[0] = json_object_new_object();
    groups[1] = json_object_new_object();
    groups[2] = json_object_new_object();
    if (!json_object_object_get_ex(root, "params", &params) ||
        json_object_get_type(params) != json_type_object ||
        !json_object_object_get_ex(params, "snapshot", &which) ||
        json_object_get_type(which) != json_type_string) {
        json_object_put(fields); json_object_put(inputs); json_object_put(parameters);
        for (index = 0; index < 3; ++index) json_object_put(groups[index]);
        send_receipt(sender, request_id, 0, "params.snapshot active or initial is required", sequence, NULL);
        return;
    }
    snapshot_name = json_object_get_string(which);
    pthread_mutex_lock(&command_lock);
    if (!strcmp(snapshot_name, "active")) {
        input_snapshot = active_input;
        parameter_snapshot = active_parameters;
    } else if (!strcmp(snapshot_name, "initial")) {
        input_snapshot = initial_input;
        parameter_snapshot = initial_parameters;
    } else {
        pthread_mutex_unlock(&command_lock);
        json_object_put(fields); json_object_put(inputs); json_object_put(parameters);
        for (index = 0; index < 3; ++index) json_object_put(groups[index]);
        send_receipt(sender, request_id, 0, "unknown snapshot", sequence, NULL);
        return;
    }
    pthread_mutex_unlock(&command_lock);
    for (index = 0; index < HIL_INPUT_COUNT; ++index) {
        const HilInputSpec* spec = &HIL_INPUT_SPECS[index];
        const char* dot = strchr(spec->name, '.');
        unsigned group_index;
        double values[MAX_INPUT_VALUE_COUNT];
        if (!dot || spec->dimension > MAX_INPUT_VALUE_COUNT ||
            !hil_contract_get_input(&input_snapshot, spec->name, values, spec->dimension)) {
            json_object_put(fields); json_object_put(inputs); json_object_put(parameters);
            for (group_index = 0; group_index < 3; ++group_index) json_object_put(groups[group_index]);
            send_receipt(sender, request_id, 0, "generated input getter unavailable", sequence, NULL);
            return;
        }
        if (!strncmp(spec->name, "flight_control.", strlen("flight_control."))) group_index = 0;
        else if (!strncmp(spec->name, "environment.", strlen("environment."))) group_index = 1;
        else if (!strncmp(spec->name, "fault.", strlen("fault."))) group_index = 2;
        else continue;
        json_object_object_add(groups[group_index], dot + 1,
                               icd_json_value(values, spec->dimension, spec->is_bool));
    }
    for (index = 0; index < HIL_PARAMETER_COUNT; ++index) {
        const HilParameterSpec* spec = &HIL_PARAMETER_SPECS[index];
        json_object_object_add(parameters, spec->name,
            spec->is_bool ? json_object_new_boolean(parameter_snapshot.value[index] != 0.0)
                          : json_object_new_double(parameter_snapshot.value[index]));
    }
    json_object_object_add(inputs, "flight_control", groups[0]);
    json_object_object_add(inputs, "environment", groups[1]);
    json_object_object_add(inputs, "fault", groups[2]);
    json_object_object_add(fields, "snapshot", json_object_new_string(snapshot_name));
    json_object_object_add(fields, "inputs", inputs);
    json_object_object_add(fields, "parameters", parameters);
    send_receipt(sender, request_id, 1, "generated contract snapshot", sequence, fields);
}

#if HIL_INITIAL_STATE_ABI_AVAILABLE
/* Capture the State132 projection source once.  At a configured-but-unstepped
 * boundary position/rates come directly from DWork; acceleration comes from
 * the generated ExtY initial output.  Once stepping begins the normalized
 * state capture is authoritative for all values.
 *
 * A status reply must not mix this snapshot with live globals: the 1 ms loop
 * advances `sequence` and publishes `state` together, so reading the global
 * first and the projection second can report sequence N with model_step N+1
 * and make formal lifecycle context validation fail with MODEL. */
static int ccore_capture_model_state(FlightStateV3_t* snapshot) {
    ModelY_t output;
    HilInitialState initial;
    double ground_height_m = 0.0;
    if (have_valid_state) {
        memcpy(snapshot, &state, sizeof(*snapshot));
        return 1;
    }
    memset(snapshot, 0, sizeof(*snapshot));
    pthread_mutex_lock(&command_lock);
    if (!hil_contract_get_input(&active_input, "environment.ground_height_m", &ground_height_m, 1U) ||
        !hil_contract_get_initial_state(&initial, ground_height_m)) {
        pthread_mutex_unlock(&command_lock);
        return 0;
    }
    pthread_mutex_unlock(&command_lock);
    model_get_output(&output);
    snapshot->sequence = sequence;
    snapshot->sim_time_s = sim_time_s;
    snapshot->north_m = initial.north_m; snapshot->east_m = initial.east_m; snapshot->down_m = initial.down_m;
    snapshot->vn_mps = (float)initial.vn_mps; snapshot->ve_mps = (float)initial.ve_mps; snapshot->vd_mps = (float)initial.vd_mps;
    snapshot->q_w = (float)initial.q_w; snapshot->q_x = (float)initial.q_x;
    snapshot->q_y = (float)initial.q_y; snapshot->q_z = (float)initial.q_z;
    snapshot->p_radps = (float)initial.p_radps; snapshot->q_radps = (float)initial.q_radps;
    snapshot->r_radps = (float)initial.r_radps; snapshot->airborne = (uint8_t)initial.airborne;
    snapshot->ax_mps2 = MODEL_READ_ax_mps2(&output);
    snapshot->ay_mps2 = MODEL_READ_ay_mps2(&output);
    snapshot->az_mps2 = MODEL_READ_az_mps2(&output);
    return 1;
}

/* Project an already-captured snapshot.  Callers that also report the
 * top-level sequence or simulation time must derive them from the same
 * snapshot instead of reading the live globals. */
static struct json_object* ccore_model_state_json(const FlightStateV3_t* snapshot) {
    struct json_object *payload, *position, *orientation;
    if (!snapshot) return NULL;
    payload = json_object_new_object();
    position = json_object_new_object();
    orientation = json_object_new_object();
    json_object_object_add(position, "north_m", json_object_new_double(snapshot->north_m));
    json_object_object_add(position, "east_m", json_object_new_double(snapshot->east_m));
    json_object_object_add(position, "down_m", json_object_new_double(snapshot->down_m));
    json_object_object_add(orientation, "q_w", json_object_new_double(snapshot->q_w));
    json_object_object_add(orientation, "q_x", json_object_new_double(snapshot->q_x));
    json_object_object_add(orientation, "q_y", json_object_new_double(snapshot->q_y));
    json_object_object_add(orientation, "q_z", json_object_new_double(snapshot->q_z));
    json_object_object_add(payload, "model_step", json_object_new_int64((int64_t)snapshot->sequence));
    json_object_object_add(payload, "position", position);
    json_object_object_add(payload, "vn_mps", json_object_new_double(snapshot->vn_mps));
    json_object_object_add(payload, "ve_mps", json_object_new_double(snapshot->ve_mps));
    json_object_object_add(payload, "vd_mps", json_object_new_double(snapshot->vd_mps));
    json_object_object_add(payload, "orientation", orientation);
    json_object_object_add(payload, "p_radps", json_object_new_double(snapshot->p_radps));
    json_object_object_add(payload, "q_radps", json_object_new_double(snapshot->q_radps));
    json_object_object_add(payload, "r_radps", json_object_new_double(snapshot->r_radps));
    json_object_object_add(payload, "airborne", json_object_new_boolean(snapshot->airborne));
    json_object_object_add(payload, "ax_mps2", json_object_new_double(snapshot->ax_mps2));
    json_object_object_add(payload, "ay_mps2", json_object_new_double(snapshot->ay_mps2));
    json_object_object_add(payload, "az_mps2", json_object_new_double(snapshot->az_mps2));
    /* Quadrotor ERT has no engine/fuel/hydraulic ports.  The frozen State132
     * representation uses zero/unavailable for those absent model channels. */
    json_object_object_add(payload, "engine_rpm", json_object_new_double(0.0));
    json_object_object_add(payload, "fuel_remaining_kg", json_object_new_double(0.0));
    json_object_object_add(payload, "hydraulic_pressure_pa", json_object_new_double(0.0));
    json_object_object_add(payload, "electrical_voltage_v", json_object_new_double(28.0));
    json_object_object_add(payload, "avionics_state", json_object_new_string("UNAVAILABLE"));
    return payload;
}
#endif

/* This capability report is intentionally independent of the model's output
 * packet.  A gateway must not infer support for RunConfigure merely because
 * an executable can expose/step its ExtU values. */
static void parse_get_hil_status(const char* request_id,
                                 const struct sockaddr_in* sender) {
    struct json_object* fields = json_object_new_object();
    ControlSource source;
#if HIL_INITIAL_STATE_ABI_AVAILABLE
    FlightStateV3_t projection;
    int have_projection;
#endif
    uint64_t status_sequence;
    double status_time_s;
    pthread_mutex_lock(&command_lock);
    source = control_arbiter.active_source;
    pthread_mutex_unlock(&command_lock);
    /* Capture once: the receipt sequence, simulation time and
     * model_state.model_step must describe the same model boundary even while
     * the 1 ms loop advances the live globals. */
#if HIL_INITIAL_STATE_ABI_AVAILABLE
    have_projection = ccore_capture_model_state(&projection);
    status_sequence = have_projection ? projection.sequence : sequence;
    status_time_s = have_projection ? projection.sim_time_s : sim_time_s;
#else
    status_sequence = sequence;
    status_time_s = sim_time_s;
#endif
    json_object_object_add(fields, "lifecycle", json_object_new_string(lifecycle_name(lifecycle)));
    json_object_object_add(fields, "sequence", json_object_new_int64((int64_t)status_sequence));
    json_object_object_add(fields, "sim_time_s", json_object_new_double(status_time_s));
    json_object_object_add(fields, "control_source", json_object_new_string(control_source_name(source)));
    json_object_object_add(fields, "model_loaded", json_object_new_boolean(model_is_loaded()));
    /* A generated DWork mapping makes the state boundary observable without
     * stepping.  Resource bytes are resolved by the local gateway and the C
     * command owns the model-side atomic commit. */
    json_object_object_add(fields, "initial_state_abi",
                           json_object_new_boolean(HIL_INITIAL_STATE_ABI_AVAILABLE));
    json_object_object_add(fields, "full_configuration_abi",
                           json_object_new_boolean(HIL_FULL_CONFIGURATION_ABI_AVAILABLE));
    json_object_object_add(fields, "model_revision",
                           json_object_new_int64((int64_t)configured_model_revision));
#if HIL_INITIAL_STATE_ABI_AVAILABLE
    {
        HilInitialState initial;
        double ground_height_m = 0.0;
        struct json_object* initial_json = json_object_new_object();
        struct json_object* position = json_object_new_object();
        struct json_object* orientation = json_object_new_object();
        /* The generated getter reads DWork directly.  ExtY is deliberately
         * not used here because a CONFIGURED model must not take a step just
         * to make its state observable. */
        pthread_mutex_lock(&command_lock);
        (void)hil_contract_get_input(&active_input, "environment.ground_height_m",
                                     &ground_height_m, 1U);
        if (!hil_contract_get_initial_state(&initial, ground_height_m)) {
            pthread_mutex_unlock(&command_lock);
            json_object_put(position);
            json_object_put(orientation);
            json_object_put(initial_json);
            send_receipt(sender, request_id, 0, "generated initial-state getter unavailable", status_sequence, fields);
            return;
        }
        pthread_mutex_unlock(&command_lock);
        {
            json_object_object_add(position, "north_m", json_object_new_double(initial.north_m));
            json_object_object_add(position, "east_m", json_object_new_double(initial.east_m));
            json_object_object_add(position, "down_m", json_object_new_double(initial.down_m));
            json_object_object_add(orientation, "q_w", json_object_new_double(initial.q_w));
            json_object_object_add(orientation, "q_x", json_object_new_double(initial.q_x));
            json_object_object_add(orientation, "q_y", json_object_new_double(initial.q_y));
            json_object_object_add(orientation, "q_z", json_object_new_double(initial.q_z));
            json_object_object_add(initial_json, "position", position);
            json_object_object_add(initial_json, "velocity_n_mps", json_object_new_double(initial.vn_mps));
            json_object_object_add(initial_json, "velocity_e_mps", json_object_new_double(initial.ve_mps));
            json_object_object_add(initial_json, "velocity_d_mps", json_object_new_double(initial.vd_mps));
            json_object_object_add(initial_json, "orientation", orientation);
            json_object_object_add(initial_json, "p_radps", json_object_new_double(initial.p_radps));
            json_object_object_add(initial_json, "q_radps", json_object_new_double(initial.q_radps));
            json_object_object_add(initial_json, "r_radps", json_object_new_double(initial.r_radps));
            json_object_object_add(initial_json, "airborne", json_object_new_boolean(initial.airborne));
            json_object_object_add(fields, "initial_state", initial_json);
        }
        {
            struct json_object* model_state;
            if (!have_projection) {
                send_receipt(sender, request_id, 0,
                             "generated State132 projection unavailable", status_sequence, fields);
                return;
            }
            model_state = ccore_model_state_json(&projection);
            if (!model_state) {
                send_receipt(sender, request_id, 0, "generated State132 projection unavailable", status_sequence, fields);
                return;
            }
            json_object_object_add(fields, "model_state", model_state);
        }
    }
#endif
    send_receipt(sender, request_id, 1, "HIL capability/status", status_sequence, fields);
}

static void parse_get_configuration_snapshot(const char* request_id,
                                             const struct sockaddr_in* sender) {
    struct json_object* fields;
    pthread_mutex_lock(&command_lock);
    if (!configured_configuration) {
        pthread_mutex_unlock(&command_lock);
        send_receipt(sender, request_id, 0, "no RunConfigure is applied", sequence, NULL);
        return;
    }
    fields = json_object_new_object();
    json_object_object_add(fields, "configuration", json_object_get(configured_configuration));
    json_object_object_add(fields, "model_revision",
                           json_object_new_int64((int64_t)configured_model_revision));
    pthread_mutex_unlock(&command_lock);
    send_receipt(sender, request_id, 1, "retained applied RunConfigure", sequence, fields);
}

static void parse_configure(struct json_object* root, const char* request_id,
                            const struct sockaddr_in* sender);

#if HIL_INITIAL_STATE_ABI_AVAILABLE
/* A bounded diagnostic for the generated state ABI.  It is deliberately not
 * RunConfigure: it has no resource or complete-input ownership and never
 * changes lifecycle.  Production configuration remains unavailable until the
 * complete atomic owner below it exists. */
static int parse_initial_state_value(struct json_object* value, double ground_height_m,
                                     HilInitialState* state_value) {
    struct json_object *position = NULL, *orientation = NULL, *field = NULL;
    double values[13];
    int was_bool = 0;
    const char* const names[] = {
        "velocity_n_mps", "velocity_e_mps", "velocity_d_mps",
        "p_radps", "q_radps", "r_radps"
    };
    unsigned index;
    if (!value || !state_value || json_object_get_type(value) != json_type_object ||
        !json_object_object_get_ex(value, "position", &position) ||
        !json_object_object_get_ex(value, "orientation", &orientation) ||
        json_object_get_type(position) != json_type_object ||
        json_object_get_type(orientation) != json_type_object) return 0;
#define HIL_GET_STATE_NUMBER(object, key, slot) \
    do { if (!json_object_object_get_ex((object), (key), &field) || \
             !valid_number(field, &values[(slot)], &was_bool) || was_bool) return 0; } while (0)
    HIL_GET_STATE_NUMBER(position, "north_m", 0);
    HIL_GET_STATE_NUMBER(position, "east_m", 1);
    HIL_GET_STATE_NUMBER(position, "down_m", 2);
    HIL_GET_STATE_NUMBER(orientation, "q_w", 3);
    HIL_GET_STATE_NUMBER(orientation, "q_x", 4);
    HIL_GET_STATE_NUMBER(orientation, "q_y", 5);
    HIL_GET_STATE_NUMBER(orientation, "q_z", 6);
    for (index = 0; index < 6U; ++index)
        HIL_GET_STATE_NUMBER(value, names[index], 7U + index);
#undef HIL_GET_STATE_NUMBER
    if (!json_object_object_get_ex(value, "airborne", &field) ||
        json_object_get_type(field) != json_type_boolean) return 0;
    state_value->north_m = values[0]; state_value->east_m = values[1]; state_value->down_m = values[2];
    state_value->q_w = values[3]; state_value->q_x = values[4]; state_value->q_y = values[5]; state_value->q_z = values[6];
    state_value->vn_mps = values[7]; state_value->ve_mps = values[8]; state_value->vd_mps = values[9];
    state_value->p_radps = values[10]; state_value->q_radps = values[11]; state_value->r_radps = values[12];
    state_value->airborne = json_object_get_boolean(field) ? 1 : 0;
    {
        const double norm = sqrt(state_value->q_w * state_value->q_w + state_value->q_x * state_value->q_x +
                                 state_value->q_y * state_value->q_y + state_value->q_z * state_value->q_z);
        const double ground_down = -ground_height_m;
        const int on_ground = fabs(state_value->down_m - ground_down) <= 1e-6;
        if (!isfinite(norm) || fabs(norm - 1.0) > 1e-6 || state_value->down_m > ground_down + 1e-6 ||
            state_value->airborne == on_ground) return 0;
    }
    return 1;
}

static void parse_set_model_initial_state(struct json_object* root, const char* request_id,
                                          const struct sockaddr_in* sender) {
    struct json_object *params = NULL, *state_value = NULL, *ground_value = NULL;
    HilInitialState candidate;
    double ground_height_m;
    int was_bool = 0;
    if (!json_object_object_get_ex(root, "params", &params) || json_object_get_type(params) != json_type_object ||
        !json_object_object_get_ex(params, "initial_state", &state_value) ||
        !json_object_object_get_ex(params, "ground_height_m", &ground_value) ||
        !valid_number(ground_value, &ground_height_m, &was_bool) || was_bool ||
        !parse_initial_state_value(state_value, ground_height_m, &candidate)) {
        send_receipt(sender, request_id, 0, "strict complete initial state and ground height are required", sequence, NULL);
        return;
    }
    pthread_mutex_lock(&command_lock);
    {
        double actual_ground_height_m = 0.0;
        const int same_ground = hil_contract_get_input(&active_input, "environment.ground_height_m",
                                                       &actual_ground_height_m, 1U) &&
                                fabs(actual_ground_height_m - ground_height_m) <= 1e-9;
        if (lifecycle != HIL_STOPPED || !same_ground || !hil_contract_set_initial_state(&candidate)) {
            pthread_mutex_unlock(&command_lock);
            send_receipt(sender, request_id, 0,
                         "initial state requires STOPPED model and matching active ground input", sequence, NULL);
            return;
        }
    }
    pthread_mutex_unlock(&command_lock);
    send_receipt(sender, request_id, 1, "generated initial state applied; full RunConfigure remains unavailable",
                 sequence, NULL);
}

static int parse_model_input_snapshot(struct json_object* inputs, ModelU_t* input,
                                      HilParameterValues* parameters) {
    static const char* const groups[] = {"flight_control", "environment", "fault"};
    unsigned group, index;
    if (!inputs || !input || !parameters || json_object_get_type(inputs) != json_type_object) return 0;
    for (group = 0; group < 3U; ++group) {
        struct json_object* object = NULL;
        unsigned expected = 0;
        const size_t prefix = strlen(groups[group]);
        if (!json_object_object_get_ex(inputs, groups[group], &object) ||
            json_object_get_type(object) != json_type_object) return 0;
        for (index = 0; index < HIL_INPUT_COUNT; ++index) {
            const HilInputSpec* spec = &HIL_INPUT_SPECS[index];
            struct json_object* value = NULL;
            double values[MAX_INPUT_VALUE_COUNT];
            if (strncmp(spec->name, groups[group], prefix) || spec->name[prefix] != '.') continue;
            expected++;
            if (spec->dimension > MAX_INPUT_VALUE_COUNT ||
                !json_object_object_get_ex(object, spec->name + prefix + 1U, &value) ||
                !parse_input_value(value, spec, values) ||
                !hil_contract_set_input(input, spec->name, values, spec->dimension)) return 0;
        }
        if (!expected || json_object_object_length(object) != expected) return 0;
    }
    {
        struct json_object* object = NULL;
        if (!json_object_object_get_ex(inputs, "parameters", &object) ||
            json_object_get_type(object) != json_type_object ||
            json_object_object_length(object) != HIL_PARAMETER_COUNT) return 0;
        for (index = 0; index < HIL_PARAMETER_COUNT; ++index) {
            const HilParameterSpec* spec = &HIL_PARAMETER_SPECS[index];
            struct json_object* value = NULL;
            double number = 0.0;
            int was_bool = 0;
            if (spec->klass == HIL_PARAM_READONLY ||
                !json_object_object_get_ex(object, spec->name, &value) ||
                !valid_number(value, &number, &was_bool) || was_bool != spec->is_bool ||
                number < spec->min_value || number > spec->max_value ||
                !hil_contract_set_parameter(input, parameters, spec->name, number)) return 0;
        }
    }
    return 1;
}

static void parse_prepare_model_snapshot(struct json_object* root, const char* request_id,
                                         const struct sockaddr_in* sender) {
    struct json_object *params = NULL, *state_value = NULL, *inputs = NULL, *model_id = NULL;
    ModelU_t candidate_input;
    HilParameterValues candidate_parameters;
    HilInitialState candidate_state;
    double ground_height_m = 0.0;
    int was_bool = 0;
    if (!json_object_object_get_ex(root, "params", &params) || json_object_get_type(params) != json_type_object ||
        !json_object_object_get_ex(params, "initial_state", &state_value) ||
        !json_object_object_get_ex(params, "initial_inputs", &inputs) ||
        json_object_get_type(inputs) != json_type_object ||
        !json_object_object_get_ex(inputs, "model_id", &model_id) ||
        json_object_get_type(model_id) != json_type_string || strcmp(json_object_get_string(model_id), HIL_MODEL_ID)) {
        send_receipt(sender, request_id, 0, "complete matching model initial state and inputs are required", sequence, NULL);
        return;
    }
    candidate_input = initial_input;
    candidate_parameters = initial_parameters;
    if (!parse_model_input_snapshot(inputs, &candidate_input, &candidate_parameters) ||
        !hil_contract_get_input(&candidate_input, "environment.ground_height_m", &ground_height_m, 1U) ||
        !isfinite(ground_height_m) || !parse_initial_state_value(state_value, ground_height_m, &candidate_state)) {
        send_receipt(sender, request_id, 0, "complete model-bound initial snapshot violates generated contract", sequence, NULL);
        return;
    }
    pthread_mutex_lock(&command_lock);
    if (lifecycle != HIL_STOPPED) {
        pthread_mutex_unlock(&command_lock);
        send_receipt(sender, request_id, 0, "model snapshot preparation requires STOPPED", sequence, NULL);
        return;
    }
    /* This is one stopped-model safety boundary: discard prior DWork before
     * applying the complete input/parameter/state candidate.  The old state
     * must not remain observable while the replacement model initializes. */
    have_valid_state = 0;
    model_terminate();
    model_initialize();
    active_input = candidate_input;
    initial_input = candidate_input;
    active_parameters = candidate_parameters;
    initial_parameters = candidate_parameters;
    *model_get_input() = active_input;
    hil_contract_apply_exported_globals(&active_parameters);
    if (!hil_contract_set_initial_state(&candidate_state)) {
        lifecycle = HIL_FAILED;
        pthread_mutex_unlock(&command_lock);
        send_receipt(sender, request_id, 0, "generated initial-state setter failed", sequence, NULL);
        return;
    }
    pending_live.input = active_input;
    pending_live.parameters = active_parameters;
    pending_live.generation++;
    pending_reset.generation = 0;
    control_arbiter_clear(&control_arbiter);
    sequence = 0;
    sim_time_s = 0.0;
    prior_rates_valid = 0;
    fixed_wing_has_taken_off = 0;
    memset(sensor_truth_valid, 0, sizeof(sensor_truth_valid));
    sensor_loss_accumulator = 0.0;
    /* Refresh the State132 projection so its model_step matches the reset
     * sequence instead of retaining the pre-reinitialization step. */
    populate_state();
    record_sensor_truth();
    pthread_mutex_unlock(&command_lock);
    send_receipt(sender, request_id, 1,
                 "model-bound snapshot applied; full RunConfigure remains unavailable", sequence, NULL);
}

/* The gateway has already validated the frozen ID3 message and resolved its
 * owned resource bytes.  C revalidates the model-bound subset and the
 * resource fact before touching the generated model, then retains the exact
 * accepted configuration as the owner of non-ExtU configuration fields. */
static int parse_resource_context(struct json_object* value, struct json_object* configuration,
                                  double expected_ground_down) {
    struct json_object *terrain = NULL, *obstacle = NULL, *ground = NULL;
    struct json_object *configured_terrain = NULL, *configured_obstacle = NULL;
    double ground_down;
    int was_bool = 0;
    if (!value || !configuration || json_object_get_type(value) != json_type_object ||
        json_object_object_length(value) != 3 ||
        !json_object_object_get_ex(value, "terrain_sha256", &terrain) ||
        !json_object_object_get_ex(value, "obstacle_sha256", &obstacle) ||
        !json_object_object_get_ex(value, "ground_down", &ground) ||
        !json_object_object_get_ex(configuration, "terrain_resource_sha256", &configured_terrain) ||
        !json_object_object_get_ex(configuration, "obstacle_resource_sha256", &configured_obstacle) ||
        !valid_number(ground, &ground_down, &was_bool) || was_bool ||
        fabs(ground_down - expected_ground_down) > 1e-6 ||
        json_object_get_type(terrain) != json_object_get_type(configured_terrain) ||
        json_object_get_type(obstacle) != json_object_get_type(configured_obstacle)) return 0;
    if (json_object_get_type(terrain) != json_type_null && json_object_get_type(terrain) != json_type_string) return 0;
    if (json_object_get_type(obstacle) != json_type_null && json_object_get_type(obstacle) != json_type_string) return 0;
    if (json_object_get_type(terrain) == json_type_string &&
        (strcmp(json_object_get_string(terrain), json_object_get_string(configured_terrain)) ||
         strlen(json_object_get_string(terrain)) != 64U)) return 0;
    if (json_object_get_type(obstacle) == json_type_string &&
        (strcmp(json_object_get_string(obstacle), json_object_get_string(configured_obstacle)) ||
         strlen(json_object_get_string(obstacle)) != 64U)) return 0;
    return 1;
}

static void parse_configure(struct json_object* root, const char* request_id,
                            const struct sockaddr_in* sender) {
    struct json_object *params = NULL, *configuration = NULL, *inputs = NULL, *state_value = NULL;
    struct json_object *model_id = NULL, *input_model_id = NULL, *step_us = NULL, *resources = NULL;
    struct json_object *expected_boundary = NULL, *expected_lifecycle = NULL;
    struct json_object *expected_step = NULL, *expected_revision = NULL, *expected_source = NULL;
    uint64_t expected_step_value = 0, expected_revision_value = 0;
    const char* expected_source_name = NULL;
    ModelU_t candidate_input;
    HilParameterValues candidate_parameters;
    HilInitialState candidate_state;
    double ground_height_m = 0.0;
    double motor[HIL_MAX_ACTUATORS];
    unsigned index;
    int safe_motors = 1;
    if (!HIL_FULL_CONFIGURATION_ABI_AVAILABLE) {
        send_receipt(sender, request_id, 0, "generated full configuration ABI unavailable", sequence, NULL);
        return;
    }
    if (!json_object_object_get_ex(root, "params", &params) || json_object_get_type(params) != json_type_object ||
        json_object_object_length(params) != 3 ||
        !json_object_object_get_ex(params, "configuration", &configuration) ||
        !json_object_object_get_ex(params, "resource_context", &resources) ||
        !json_object_object_get_ex(params, "expected_boundary", &expected_boundary) ||
        json_object_get_type(expected_boundary) != json_type_object ||
        json_object_object_length(expected_boundary) != 4 ||
        !json_object_object_get_ex(expected_boundary, "lifecycle", &expected_lifecycle) ||
        json_object_get_type(expected_lifecycle) != json_type_string ||
        strcmp(json_object_get_string(expected_lifecycle), "STOPPED") ||
        !json_object_object_get_ex(expected_boundary, "model_step", &expected_step) ||
        !json_uint64(expected_step, &expected_step_value) || expected_step_value > UINT32_MAX ||
        !json_object_object_get_ex(expected_boundary, "model_revision", &expected_revision) ||
        !json_uint64(expected_revision, &expected_revision_value) || expected_revision_value > UINT32_MAX ||
        !json_object_object_get_ex(expected_boundary, "control_source", &expected_source) ||
        json_object_get_type(expected_source) != json_type_string ||
        !(expected_source_name = json_object_get_string(expected_source)) ||
        json_object_get_type(configuration) != json_type_object ||
        !json_object_object_get_ex(configuration, "model_id", &model_id) ||
        json_object_get_type(model_id) != json_type_string || strcmp(json_object_get_string(model_id), HIL_MODEL_ID) ||
        !json_object_object_get_ex(configuration, "step_us", &step_us) ||
        json_object_get_type(step_us) != json_type_int || json_object_get_int64(step_us) != 1000 ||
        !json_object_object_get_ex(configuration, "initial_inputs", &inputs) ||
        json_object_get_type(inputs) != json_type_object ||
        !json_object_object_get_ex(inputs, "model_id", &input_model_id) ||
        json_object_get_type(input_model_id) != json_type_string || strcmp(json_object_get_string(input_model_id), HIL_MODEL_ID) ||
        !json_object_object_get_ex(configuration, "initial_state", &state_value)) {
        send_receipt(sender, request_id, 0, "complete matching RunConfigure and resolved resources are required", sequence, NULL);
        return;
    }
    /* The confirmed Run policy requires a fresh model boundary for every configuration. */
    if (expected_step_value != 0U) {
        send_receipt(sender, request_id, 0, "RunConfigure requires model_step zero for a new Run", sequence, NULL);
        return;
    }
    candidate_input = initial_input;
    candidate_parameters = initial_parameters;
    if (!parse_model_input_snapshot(inputs, &candidate_input, &candidate_parameters) ||
        !hil_contract_get_input(&candidate_input, "environment.ground_height_m", &ground_height_m, 1U) ||
        !parse_initial_state_value(state_value, ground_height_m, &candidate_state) ||
        !parse_resource_context(resources, configuration, -ground_height_m) ||
        !hil_contract_get_input(&candidate_input, "flight_control.motor_command", motor, HIL_ACTUATOR_COUNT)) {
        send_receipt(sender, request_id, 0, "RunConfigure violates generated model/resource contract", sequence, NULL);
        return;
    }
    for (index = 0; index < HIL_ACTUATOR_COUNT; ++index)
        if (fabs(motor[index] - HIL_ACTUATOR_SPECS[index].safe_value) > 1e-9) safe_motors = 0;
    if (!safe_motors || configured_model_revision == UINT32_MAX) {
        send_receipt(sender, request_id, 0, "RunConfigure initial control is unsafe or revision is exhausted", sequence, NULL);
        return;
    }
    pthread_mutex_lock(&model_boundary_lock);
    pthread_mutex_lock(&command_lock);
    if (lifecycle_request.pending || lifecycle != HIL_STOPPED || sequence != expected_step_value ||
        configured_model_revision != expected_revision_value ||
        strcmp(control_source_name(control_arbiter.active_source), expected_source_name)) {
        pthread_mutex_unlock(&command_lock);
        pthread_mutex_unlock(&model_boundary_lock);
        send_receipt(sender, request_id, 0,
                     "RunConfigure actual lifecycle/step/revision/control boundary changed", sequence, NULL);
        return;
    }
    /* Do not publish a stale pre-configure state while the replacement model
     * initializes or if the new initial state cannot form a valid sample. */
    have_valid_state = 0;
    model_terminate();
    model_initialize();
    active_input = candidate_input;
    initial_input = candidate_input;
    active_parameters = candidate_parameters;
    initial_parameters = candidate_parameters;
    *model_get_input() = active_input;
    hil_contract_apply_exported_globals(&active_parameters);
    if (!hil_contract_set_initial_state(&candidate_state)) {
        lifecycle = HIL_FAILED;
        pthread_mutex_unlock(&command_lock);
        pthread_mutex_unlock(&model_boundary_lock);
        send_receipt(sender, request_id, 0, "generated initial-state setter failed", sequence, NULL);
        return;
    }
    if (configured_configuration) json_object_put(configured_configuration);
    configured_configuration = json_object_get(configuration);
    configured_model_revision++;
    pending_live.input = active_input;
    pending_live.parameters = active_parameters;
    pending_live.generation++;
    pending_reset.generation = 0;
    control_arbiter_clear(&control_arbiter);
    sequence = 0;
    sim_time_s = 0.0;
    prior_rates_valid = 0;
    fixed_wing_has_taken_off = 0;
    memset(sensor_truth_valid, 0, sizeof(sensor_truth_valid));
    sensor_loss_accumulator = 0.0;
    lifecycle = HIL_CONFIGURED;
    /* A configured boundary must expose a State132 projection whose
     * model_step equals the reset sequence.  Without this refresh the
     * previous run's step remains cached and lifecycle context validation
     * rejects the next formal START with MODEL. */
    populate_state();
    record_sensor_truth();
    pthread_mutex_unlock(&command_lock);
    zero_motor_command();
    pthread_mutex_unlock(&model_boundary_lock);
    {
        struct json_object* fields = json_object_new_object();
        json_object_object_add(fields, "configuration", json_object_get(configured_configuration));
        json_object_object_add(fields, "model_revision",
                               json_object_new_int64((int64_t)configured_model_revision));
        send_receipt(sender, request_id, 1, "RunConfigure applied at safe configured boundary", sequence, fields);
    }
}
#else
static void parse_configure(struct json_object* root, const char* request_id,
                            const struct sockaddr_in* sender) {
    (void)root;
    send_receipt(sender, request_id, 0, "generated initial-state ABI unavailable; RunConfigure is refused",
                 sequence, NULL);
}
#endif

static const char* icd_environment_state_name(IcdEnvironmentState state_value) {
    switch (state_value) {
    case ICD_ENVIRONMENT_STAGED: return "STAGED";
    case ICD_ENVIRONMENT_APPLIED: return "APPLIED";
    case ICD_ENVIRONMENT_REJECTED: return "REJECTED";
    default: return "UNKNOWN";
    }
}

static struct json_object* icd_environment_fields(const IcdEnvironmentStage* snapshot) {
    struct json_object* fields = json_object_new_object();
    struct json_object* readback = json_object_new_object();
    unsigned index;
    json_object_object_add(fields, "state",
                           json_object_new_string(icd_environment_state_name(snapshot->state)));
    json_object_object_add(fields, "stage_request_id",
                           json_object_new_string(snapshot->stage_request_id));
    json_object_object_add(fields, "target_step",
                           json_object_new_int64((int64_t)snapshot->target_step));
    json_object_object_add(fields, "applied_step",
                           json_object_new_int64((int64_t)snapshot->applied_step));
    json_object_object_add(fields, "model_revision",
                           json_object_new_int64((int64_t)snapshot->model_revision));
    json_object_object_add(fields, "reason", json_object_new_string(snapshot->reason));
    if (snapshot->state == ICD_ENVIRONMENT_APPLIED) {
        for (index = 0; index < ICD_ENVIRONMENT_FIELD_COUNT; ++index)
            json_object_object_add(readback, ICD_ENVIRONMENT_FIELDS[index] + strlen("environment."),
                                   json_object_new_double(snapshot->readback[index]));
        json_object_object_add(fields, "readback", readback);
    } else {
        json_object_put(readback);
    }
    return fields;
}

/* Strict bridge command used only by the 3.6 ModelConsumer for ID10.  It
 * requires the complete frozen Environment snapshot and does not alter the
 * generated ModelU until the requested model-step boundary. */
static void parse_stage_icd_environment(struct json_object* root, const char* request_id,
                                        const struct sockaddr_in* sender) {
    struct json_object *params = NULL, *target = NULL, *deadline = NULL, *environment = NULL;
    IcdEnvironmentStage staged;
    uint64_t now_ns = monotonic_time_ns();
    unsigned index;
    if (!json_object_object_get_ex(root, "params", &params) ||
        json_object_get_type(params) != json_type_object ||
        !json_object_object_get_ex(params, "target_step", &target) ||
        !json_object_object_get_ex(params, "deadline_ns", &deadline) ||
        !json_object_object_get_ex(params, "environment", &environment) ||
        json_object_get_type(environment) != json_type_object ||
        !json_uint64(target, &staged.target_step) || !json_uint64(deadline, &staged.deadline_ns) ||
        json_object_object_length(environment) != ICD_ENVIRONMENT_FIELD_COUNT) {
        send_receipt(sender, request_id, 0, "complete target_step, deadline_ns and environment are required",
                     sequence, NULL);
        return;
    }
    if (lifecycle != HIL_RUNNING || staged.deadline_ns <= now_ns ||
        staged.target_step <= sequence ||
        staged.target_step > sequence + ICD_ENVIRONMENT_MAX_LOOKAHEAD_STEPS) {
        send_receipt(sender, request_id, 0, "target or lifecycle is not admissible", sequence, NULL);
        return;
    }
    memset(&staged, 0, sizeof(staged));
    /* json values were read before memset; recover the two scalar values. */
    json_uint64(target, &staged.target_step);
    json_uint64(deadline, &staged.deadline_ns);
    for (index = 0; index < ICD_ENVIRONMENT_FIELD_COUNT; ++index) {
        const HilInputSpec* spec = hil_contract_find_input(ICD_ENVIRONMENT_FIELDS[index]);
        struct json_object* value = NULL;
        if (!spec || !json_object_object_get_ex(environment,
                                                 ICD_ENVIRONMENT_FIELDS[index] + strlen("environment."),
                                                 &value) ||
            !parse_input_value(value, spec, &staged.values[index])) {
            send_receipt(sender, request_id, 0, "environment type, field set or range violates contract",
                         sequence, NULL);
            return;
        }
    }
    staged.state = ICD_ENVIRONMENT_STAGED;
    strncpy(staged.stage_request_id, request_id, sizeof(staged.stage_request_id) - 1U);
    strncpy(staged.reason, "awaiting target boundary", sizeof(staged.reason) - 1U);
    pthread_mutex_lock(&command_lock);
    if (icd_environment.state == ICD_ENVIRONMENT_STAGED) {
        pthread_mutex_unlock(&command_lock);
        send_receipt(sender, request_id, 0, "previous ICD environment transaction is pending", sequence, NULL);
        return;
    }
    icd_environment = staged;
    pthread_mutex_unlock(&command_lock);
    send_receipt(sender, request_id, 1, "staged", staged.target_step, NULL);
}

static void parse_get_icd_environment_result(struct json_object* root, const char* request_id,
                                             const struct sockaddr_in* sender) {
    struct json_object *params = NULL, *stage_request = NULL;
    IcdEnvironmentStage snapshot;
    if (!json_object_object_get_ex(root, "params", &params) ||
        json_object_get_type(params) != json_type_object ||
        !json_object_object_get_ex(params, "stage_request_id", &stage_request) ||
        json_object_get_type(stage_request) != json_type_string) {
        send_receipt(sender, request_id, 0, "params.stage_request_id is required", sequence, NULL);
        return;
    }
    pthread_mutex_lock(&command_lock);
    snapshot = icd_environment;
    pthread_mutex_unlock(&command_lock);
    if (snapshot.state == ICD_ENVIRONMENT_EMPTY ||
        strcmp(snapshot.stage_request_id, json_object_get_string(stage_request))) {
        send_receipt(sender, request_id, 0, "unknown ICD environment transaction", sequence, NULL);
        return;
    }
    send_receipt(sender, request_id, snapshot.state != ICD_ENVIRONMENT_REJECTED,
                 snapshot.reason, snapshot.applied_step ? snapshot.applied_step : sequence,
                 icd_environment_fields(&snapshot));
}

static struct json_object* icd_fault_fields(const IcdFaultStage* snapshot) {
    struct json_object* fields = json_object_new_object();
    struct json_object* readback = json_object_new_object();
    unsigned index;
    json_object_object_add(fields, "state",
                           json_object_new_string(icd_environment_state_name(snapshot->state)));
    json_object_object_add(fields, "stage_request_id",
                           json_object_new_string(snapshot->stage_request_id));
    json_object_object_add(fields, "target_step",
                           json_object_new_int64((int64_t)snapshot->target_step));
    json_object_object_add(fields, "applied_step",
                           json_object_new_int64((int64_t)snapshot->applied_step));
    json_object_object_add(fields, "model_revision",
                           json_object_new_int64((int64_t)snapshot->model_revision));
    json_object_object_add(fields, "reason", json_object_new_string(snapshot->reason));
    if (snapshot->state == ICD_ENVIRONMENT_APPLIED) {
        for (index = 0; index < ICD_FAULT_FIELD_COUNT; ++index) {
            const HilInputSpec* spec = hil_contract_find_input(ICD_FAULT_FIELDS[index]);
            const char* name = ICD_FAULT_FIELDS[index] + strlen("fault.");
            json_object_object_add(readback, name,
                spec && spec->is_bool ? json_object_new_boolean(snapshot->readback[index] != 0.0)
                                     : json_object_new_double(snapshot->readback[index]));
        }
        json_object_object_add(fields, "readback", readback);
    } else {
        json_object_put(readback);
    }
    return fields;
}

/* The generated contract provides the only setters used here.  A value is
 * marked APPLIED only after every declared ID11 field was written on the
 * model thread at the requested boundary. */
static void parse_stage_icd_fault(struct json_object* root, const char* request_id,
                                  const struct sockaddr_in* sender) {
    struct json_object *params = NULL, *target = NULL, *deadline = NULL, *fault = NULL;
    IcdFaultStage staged;
    uint64_t now_ns = monotonic_time_ns();
    unsigned index;
    if (!json_object_object_get_ex(root, "params", &params) ||
        json_object_get_type(params) != json_type_object ||
        !json_object_object_get_ex(params, "target_step", &target) ||
        !json_object_object_get_ex(params, "deadline_ns", &deadline) ||
        !json_object_object_get_ex(params, "fault", &fault) ||
        json_object_get_type(fault) != json_type_object ||
        !json_uint64(target, &staged.target_step) || !json_uint64(deadline, &staged.deadline_ns) ||
        json_object_object_length(fault) != ICD_FAULT_FIELD_COUNT) {
        send_receipt(sender, request_id, 0, "complete target_step, deadline_ns and fault are required",
                     sequence, NULL);
        return;
    }
    if (lifecycle != HIL_RUNNING || staged.deadline_ns <= now_ns ||
        staged.target_step <= sequence ||
        staged.target_step > sequence + ICD_ENVIRONMENT_MAX_LOOKAHEAD_STEPS) {
        send_receipt(sender, request_id, 0, "target or lifecycle is not admissible", sequence, NULL);
        return;
    }
    memset(&staged, 0, sizeof(staged));
    json_uint64(target, &staged.target_step);
    json_uint64(deadline, &staged.deadline_ns);
    for (index = 0; index < ICD_FAULT_FIELD_COUNT; ++index) {
        const HilInputSpec* spec = hil_contract_find_input(ICD_FAULT_FIELDS[index]);
        struct json_object* value = NULL;
        if (!spec || !json_object_object_get_ex(fault, ICD_FAULT_FIELDS[index] + strlen("fault."), &value) ||
            !parse_input_value(value, spec, &staged.values[index])) {
            send_receipt(sender, request_id, 0, "fault type, field set or range violates contract",
                         sequence, NULL);
            return;
        }
    }
    staged.state = ICD_ENVIRONMENT_STAGED;
    strncpy(staged.stage_request_id, request_id, sizeof(staged.stage_request_id) - 1U);
    strncpy(staged.reason, "awaiting target boundary", sizeof(staged.reason) - 1U);
    pthread_mutex_lock(&command_lock);
    if (icd_fault.state == ICD_ENVIRONMENT_STAGED) {
        pthread_mutex_unlock(&command_lock);
        send_receipt(sender, request_id, 0, "previous ICD fault transaction is pending", sequence, NULL);
        return;
    }
    icd_fault = staged;
    pthread_mutex_unlock(&command_lock);
    send_receipt(sender, request_id, 1, "staged", staged.target_step, NULL);
}

static void parse_get_icd_fault_result(struct json_object* root, const char* request_id,
                                       const struct sockaddr_in* sender) {
    struct json_object *params = NULL, *stage_request = NULL;
    IcdFaultStage snapshot;
    if (!json_object_object_get_ex(root, "params", &params) ||
        json_object_get_type(params) != json_type_object ||
        !json_object_object_get_ex(params, "stage_request_id", &stage_request) ||
        json_object_get_type(stage_request) != json_type_string) {
        send_receipt(sender, request_id, 0, "params.stage_request_id is required", sequence, NULL);
        return;
    }
    pthread_mutex_lock(&command_lock);
    snapshot = icd_fault;
    pthread_mutex_unlock(&command_lock);
    if (snapshot.state == ICD_ENVIRONMENT_EMPTY ||
        strcmp(snapshot.stage_request_id, json_object_get_string(stage_request))) {
        send_receipt(sender, request_id, 0, "unknown ICD fault transaction", sequence, NULL);
        return;
    }
    send_receipt(sender, request_id, snapshot.state != ICD_ENVIRONMENT_REJECTED,
                 snapshot.reason, snapshot.applied_step ? snapshot.applied_step : sequence,
                 icd_fault_fields(&snapshot));
}

static struct json_object* icd_flight_fields(const IcdFlightStage* snapshot) {
    struct json_object* fields = json_object_new_object();
    struct json_object* readback = json_object_new_array();
    unsigned index;
    json_object_object_add(fields, "state",
                           json_object_new_string(icd_environment_state_name(snapshot->state)));
    json_object_object_add(fields, "stage_request_id",
                           json_object_new_string(snapshot->stage_request_id));
    json_object_object_add(fields, "target_step",
                           json_object_new_int64((int64_t)snapshot->target_step));
    json_object_object_add(fields, "applied_step",
                           json_object_new_int64((int64_t)snapshot->applied_step));
    json_object_object_add(fields, "model_revision",
                           json_object_new_int64((int64_t)snapshot->model_revision));
    json_object_object_add(fields, "reason", json_object_new_string(snapshot->reason));
    if (snapshot->state == ICD_ENVIRONMENT_APPLIED) {
        for (index = 0; index < HIL_ACTUATOR_COUNT; ++index)
            json_object_array_add(readback, json_object_new_double(snapshot->readback[index]));
        json_object_object_add(fields, "readback", readback);
    } else {
        json_object_put(readback);
    }
    return fields;
}

/* ID7 is a complete four-motor snapshot.  The command thread only stages it;
 * the main thread commits it after every other motor writer has run. */
static void parse_stage_icd_flight_control(struct json_object* root, const char* request_id,
                                           const struct sockaddr_in* sender) {
    struct json_object *params = NULL, *target = NULL, *deadline = NULL, *flight = NULL, *motor = NULL;
    IcdFlightStage staged;
    const HilInputSpec* spec;
    uint64_t now_ns = monotonic_time_ns();
    if (!json_object_object_get_ex(root, "params", &params) ||
        json_object_get_type(params) != json_type_object ||
        !json_object_object_get_ex(params, "target_step", &target) ||
        !json_object_object_get_ex(params, "deadline_ns", &deadline) ||
        !json_object_object_get_ex(params, "flight_control", &flight) ||
        json_object_get_type(flight) != json_type_object ||
        json_object_object_length(flight) != 1 ||
        !json_object_object_get_ex(flight, "motor_command", &motor) ||
        !json_uint64(target, &staged.target_step) || !json_uint64(deadline, &staged.deadline_ns) ||
        lifecycle != HIL_RUNNING || staged.deadline_ns <= now_ns ||
        staged.target_step <= sequence ||
        staged.target_step > sequence + ICD_ENVIRONMENT_MAX_LOOKAHEAD_STEPS) {
        send_receipt(sender, request_id, 0, "complete admissible target flight-control snapshot is required",
                     sequence, NULL);
        return;
    }
    spec = hil_contract_find_input("flight_control.motor_command");
    if (!spec || spec->dimension != HIL_ACTUATOR_COUNT ||
        !parse_input_value(motor, spec, staged.values)) {
        send_receipt(sender, request_id, 0, "motor command type, dimension or range violates contract",
                     sequence, NULL);
        return;
    }
    memset(&staged, 0, sizeof(staged));
    json_uint64(target, &staged.target_step);
    json_uint64(deadline, &staged.deadline_ns);
    if (!parse_input_value(motor, spec, staged.values)) {
        send_receipt(sender, request_id, 0, "motor command violates contract", sequence, NULL);
        return;
    }
    staged.state = ICD_ENVIRONMENT_STAGED;
    strncpy(staged.stage_request_id, request_id, sizeof(staged.stage_request_id) - 1U);
    strncpy(staged.reason, "awaiting final motor boundary", sizeof(staged.reason) - 1U);
    pthread_mutex_lock(&command_lock);
    if (icd_flight.state == ICD_ENVIRONMENT_STAGED) {
        pthread_mutex_unlock(&command_lock);
        send_receipt(sender, request_id, 0, "previous ICD flight-control transaction is pending", sequence, NULL);
        return;
    }
    icd_flight = staged;
    pthread_mutex_unlock(&command_lock);
    send_receipt(sender, request_id, 1, "staged", staged.target_step, NULL);
}

static void parse_get_icd_flight_control_result(struct json_object* root, const char* request_id,
                                                const struct sockaddr_in* sender) {
    struct json_object *params = NULL, *stage_request = NULL;
    IcdFlightStage snapshot;
    if (!json_object_object_get_ex(root, "params", &params) ||
        json_object_get_type(params) != json_type_object ||
        !json_object_object_get_ex(params, "stage_request_id", &stage_request) ||
        json_object_get_type(stage_request) != json_type_string) {
        send_receipt(sender, request_id, 0, "params.stage_request_id is required", sequence, NULL);
        return;
    }
    pthread_mutex_lock(&command_lock);
    snapshot = icd_flight;
    pthread_mutex_unlock(&command_lock);
    if (snapshot.state == ICD_ENVIRONMENT_EMPTY ||
        strcmp(snapshot.stage_request_id, json_object_get_string(stage_request))) {
        send_receipt(sender, request_id, 0, "unknown ICD flight-control transaction", sequence, NULL);
        return;
    }
    send_receipt(sender, request_id, snapshot.state != ICD_ENVIRONMENT_REJECTED,
                 snapshot.reason, snapshot.applied_step ? snapshot.applied_step : sequence,
                 icd_flight_fields(&snapshot));
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
    if (ok && seen) {
        pending_live.input = candidate;
        pending_live.generation++;
        latency_accept_locked(HIL_LATENCY_LIVE_INPUT, pending_live.generation,
                              command_ingress_ns);
    }
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
    latency_accept_locked(HIL_LATENCY_MISSION, mission.generation, command_ingress_ns);
    strncpy(mission.mission_id, json_object_get_string(mission_id), sizeof(mission.mission_id) - 1);
    mission.mission_id[sizeof(mission.mission_id) - 1] = '\0';
    pthread_mutex_unlock(&command_lock);
    if (HIL_FIXED_WING_V3_TCP)
        fixed_wing_v3_tcp_set_mission(json_object_get_string(mission_id), parsed,
                                      (unsigned)count + 1U);
    send_receipt(sender, request_id, 1, "mission accepted as explicit NED route", sequence + 1U, NULL);
}

static const HilParameterSpec* find_parameter(const char* name) {
    unsigned i;
    for (i = 0; i < HIL_PARAMETER_COUNT; ++i)
        if (!strcmp(HIL_PARAMETER_SPECS[i].name, name)) return &HIL_PARAMETER_SPECS[i];
    return NULL;
}

/* The optional demo mission controller must consume contract values through
 * this generic registry, never model-generated global symbols. */
static double active_parameter_or_default(const char* name, double default_value) {
    const HilParameterSpec* spec = find_parameter(name);
    unsigned index;
    if (!spec) return default_value;
    index = (unsigned)(spec - HIL_PARAMETER_SPECS);
    if (index >= HIL_PARAMETER_COUNT || !isfinite(active_parameters.value[index]) ||
        active_parameters.value[index] <= 0.0) return default_value;
    return active_parameters.value[index];
}

static void configure_demo_mission_controller(void) {
    mission_controller_configure_vehicle(
        active_parameter_or_default("mass_kg", 1.5),
        active_parameter_or_default("thrust_coefficient_n", 4.2),
        active_parameter_or_default("motor_efficiency", 1.0));
}

static const char* parameter_class_name(int klass) {
    if (klass == HIL_PARAM_LIVE) return "live";
    if (klass == HIL_PARAM_RESET_ONLY) return "reset_only";
    return "readonly";
}

static void parse_get_parameter_registry(const char* request_id,
                                         const struct sockaddr_in* sender) {
    struct json_object* fields = json_object_new_object();
    struct json_object* parameters = json_object_new_array();
    unsigned index;
    pthread_mutex_lock(&command_lock);
    for (index = 0; index < HIL_PARAMETER_COUNT; ++index) {
        const HilParameterSpec* spec = &HIL_PARAMETER_SPECS[index];
        struct json_object* item = json_object_new_object();
        /* V2 generated contract headers predate descriptive parameter
         * metadata.  Keep those deployed models runnable: their initial
         * parameter snapshot is authoritative for the default, while V3
         * headers provide the richer schema below. */
        const char* unit = "";
        const char* review_status = "approved";
        double default_value = initial_parameters.value[index];
#if defined(HIL_PARAMETER_METADATA)
        unit = spec->unit;
        review_status = spec->review_status;
        default_value = spec->default_value;
#endif
        json_object_object_add(item, "name", json_object_new_string(spec->name));
        json_object_object_add(item, "unit", json_object_new_string(unit));
        json_object_object_add(item, "review_status", json_object_new_string(review_status));
        json_object_object_add(item, "class", json_object_new_string(parameter_class_name(spec->klass)));
        json_object_object_add(item, "type", json_object_new_string(spec->is_bool ? "bool" : "double"));
        json_object_object_add(item, "default", spec->is_bool ? json_object_new_boolean(default_value != 0.0) : json_object_new_double(default_value));
        json_object_object_add(item, "min", json_object_new_double(spec->min_value));
        json_object_object_add(item, "max", json_object_new_double(spec->max_value));
        json_object_object_add(item, "current", spec->is_bool ? json_object_new_boolean(active_parameters.value[index] != 0.0) : json_object_new_double(active_parameters.value[index]));
        json_object_object_add(item, "allowed_phase_mask", json_object_new_int((int)spec->phase_mask));
        json_object_array_add(parameters, item);
    }
    pthread_mutex_unlock(&command_lock);
    json_object_object_add(fields, "parameters", parameters);
    send_receipt(sender, request_id, 1, "parameter registry", sequence, fields);
}

static int state_is_valid(const FlightStateV3_t* candidate) {
    const float norm = sqrtf(candidate->q_w * candidate->q_w + candidate->q_x * candidate->q_x +
                             candidate->q_y * candidate->q_y + candidate->q_z * candidate->q_z);
    if (!isfinite(candidate->sim_time_s) || !isfinite(candidate->north_m) ||
        !isfinite(candidate->east_m) || !isfinite(candidate->down_m) ||
        !isfinite(candidate->vn_mps) || !isfinite(candidate->ve_mps) || !isfinite(candidate->vd_mps) ||
        !isfinite(candidate->q_w) || !isfinite(candidate->q_x) || !isfinite(candidate->q_y) ||
        !isfinite(candidate->q_z) || !isfinite(candidate->p_radps) || !isfinite(candidate->q_radps) ||
        !isfinite(candidate->r_radps) || !isfinite(candidate->ax_mps2) ||
        !isfinite(candidate->ay_mps2) || !isfinite(candidate->az_mps2) ||
        !isfinite(candidate->p_dot_radps2) || !isfinite(candidate->q_dot_radps2) ||
        !isfinite(candidate->r_dot_radps2) || !isfinite(candidate->wind_n_mps) ||
        !isfinite(candidate->wind_e_mps) || !isfinite(candidate->wind_d_mps) ||
        !isfinite(candidate->throttle) || !isfinite(candidate->aileron_rad) ||
        !isfinite(candidate->elevator_rad) || !isfinite(candidate->rudder_rad) ||
        !isfinite(candidate->tas_min_mps)) return 0;
    return norm > 0.0f && fabsf(norm - 1.0f) <= 0.02f && candidate->airborne <= 1 &&
           candidate->throttle >= 0.0f && candidate->throttle <= 1.0f &&
           candidate->tas_min_mps > 0.0f &&
           candidate->flight_phase <= HIL_FLIGHT_FAULT &&
           candidate->control_surface_valid <= 1;
}

static uint8_t fixed_wing_flight_phase(const FlightStateV3_t* candidate,
                                       const ModelY_t* output) {
    const int model_phase = HIL_READ_FLIGHT_PHASE_MODEL(output);
    if (!HIL_FIXED_WING) return candidate->airborne ? HIL_FLIGHT_FLYING : HIL_FLIGHT_LANDED;
    if (HIL_READ_FAULT_ACTIVE(&active_input)) return HIL_FLIGHT_FAULT;
    if (lifecycle == HIL_ENDED) return HIL_FLIGHT_LANDED;
    if (lifecycle == HIL_RESETTING) return HIL_FLIGHT_READY;
    /* A declared model phase is authoritative only after C has handled
     * lifecycle and explicit fault overrides above. */
    if (model_phase >= HIL_FLIGHT_READY && model_phase <= HIL_FLIGHT_FAULT)
        return (uint8_t)model_phase;
    if (candidate->airborne) {
        fixed_wing_has_taken_off = 1;
        return candidate->throttle <= HIL_LANDING_THROTTLE_MAX ? HIL_FLIGHT_LANDING : HIL_FLIGHT_FLYING;
    }
    if (fixed_wing_has_taken_off) return HIL_FLIGHT_LANDED;
    return candidate->throttle > HIL_TAKEOFF_THROTTLE_MIN ? HIL_FLIGHT_TAKING_OFF : HIL_FLIGHT_READY;
}

static void populate_state(void) {
    ModelY_t output;
    FlightStateV3_t candidate;
    model_get_output(&output);
    memset(&candidate, 0, sizeof(candidate));
    candidate.version = FLIGHT_STATE_V3_VERSION;
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
    candidate.p_dot_radps2 = prior_rates_valid ? (candidate.p_radps - prior_p_radps) * 1000.0f : 0.0f;
    candidate.q_dot_radps2 = prior_rates_valid ? (candidate.q_radps - prior_q_radps) * 1000.0f : 0.0f;
    candidate.r_dot_radps2 = prior_rates_valid ? (candidate.r_radps - prior_r_radps) * 1000.0f : 0.0f;
    candidate.wind_n_mps = (float)HIL_READ_WIND_N_MPS(&active_input);
    candidate.wind_e_mps = (float)HIL_READ_WIND_E_MPS(&active_input);
    candidate.wind_d_mps = (float)HIL_READ_WIND_D_MPS(&active_input);
    candidate.throttle = (float)HIL_READ_THROTTLE(&active_input);
    candidate.aileron_rad = (float)HIL_READ_AILERON_RAD(&active_input, &output);
    candidate.elevator_rad = (float)HIL_READ_ELEVATOR_RAD(&active_input, &output);
    candidate.rudder_rad = (float)HIL_READ_RUDDER_RAD(&active_input, &output);
    candidate.tas_min_mps = (float)HIL_TAS_MIN_MPS;
    candidate.control_surface_valid = HIL_SURFACE_OUTPUT_VALID ? 1 : 0;
    candidate.flight_phase = fixed_wing_flight_phase(&candidate, &output);
    if (state_is_valid(&candidate)) {
        memcpy(&state, &candidate, sizeof(state));
        prior_p_radps = candidate.p_radps;
        prior_q_radps = candidate.q_radps;
        prior_r_radps = candidate.r_radps;
        prior_rates_valid = 1;
        have_valid_state = 1;
    }
    else {
        fprintf(stderr, "[HIL] rejected invalid generated state at sequence %llu\n", (unsigned long long)sequence);
    }
}

static double active_input_scalar(const char* name, double fallback) {
    double value = fallback;
    if (!hil_contract_get_input(&active_input, name, &value, 1U) || !isfinite(value))
        return fallback;
    return value;
}

static void record_sensor_truth(void) {
    const unsigned slot = (unsigned)(state.sequence % SENSOR_HISTORY_STEPS);
    if (!have_valid_state) return;
    sensor_truth_history[slot] = state;
    sensor_truth_valid[slot] = 1U;
}

/* Status/monitor retain the unfaulted model truth.  Only the sensor transport
 * receives delayed samples and GPS/IMU bias, and packet loss suppresses an
 * actual datagram instead of scaling a numerical value. */
static int prepare_sensor_sample(FlightStateV3_t* sample) {
    double delay_ms, loss;
    uint64_t delay_steps, sample_step;
    unsigned slot;
    if (!sample || !have_valid_state) return 0;
    delay_ms = fmin(1000.0, fmax(0.0,
        active_input_scalar("fault.sensor_delay_ms", 0.0)));
    loss = fmin(1.0, fmax(0.0,
        active_input_scalar("fault.packet_loss_ratio", 0.0)));
    sensor_loss_accumulator += loss;
    if (sensor_loss_accumulator >= 1.0) {
        sensor_loss_accumulator -= 1.0;
        return 0;
    }
    delay_steps = (uint64_t)floor(delay_ms + 0.5);
    if (state.sequence < delay_steps) return 0;
    sample_step = state.sequence - delay_steps;
    slot = (unsigned)(sample_step % SENSOR_HISTORY_STEPS);
    if (!sensor_truth_valid[slot] || sensor_truth_history[slot].sequence != sample_step)
        return 0;
    *sample = sensor_truth_history[slot];
    sample->north_m += (float)active_input_scalar("fault.gps_bias_n_m", 0.0);
    sample->east_m += (float)active_input_scalar("fault.gps_bias_e_m", 0.0);
    sample->down_m += (float)active_input_scalar("fault.gps_bias_d_m", 0.0);
    sample->p_radps += (float)active_input_scalar("fault.imu_bias_p_radps", 0.0);
    sample->q_radps += (float)active_input_scalar("fault.imu_bias_q_radps", 0.0);
    sample->r_radps += (float)active_input_scalar("fault.imu_bias_r_radps", 0.0);
    return 1;
}

static void queue_lifecycle_at(int event, uint64_t target_step, int target_bound,
                               const char* request_id, const struct sockaddr_in* sender) {
    pthread_mutex_lock(&command_lock);
    lifecycle_request.pending = 1;
    lifecycle_request.event = event;
    lifecycle_request.target_bound = target_bound;
    lifecycle_request.target_step = target_step;
    strncpy(lifecycle_request.request_id, request_id, sizeof(lifecycle_request.request_id) - 1);
    lifecycle_request.request_id[sizeof(lifecycle_request.request_id) - 1] = '\0';
    lifecycle_request.sender = *sender;
    pthread_mutex_unlock(&command_lock);
}

static void queue_lifecycle(int event, const char* request_id, const struct sockaddr_in* sender) {
    queue_lifecycle_at(event, sequence, 1, request_id, sender);
}

static int lifecycle_event_from_name(const char* name, int* event) {
    if (!name || !event) return 0;
    if (!strcmp(name, "START")) *event = HIL_RUNNING;
    else if (!strcmp(name, "PAUSE")) *event = HIL_PAUSED;
    else if (!strcmp(name, "RESUME")) *event = HIL_RUNNING;
    else if (!strcmp(name, "STOP")) *event = HIL_STOPPED;
    else if (!strcmp(name, "RESET")) *event = HIL_RESETTING;
    else return 0;
    return 1;
}

/* Formal lifecycle requests name the exact C model boundary.  This command
 * only stages a transition; the main 1ms thread emits the final receipt after
 * it has made the state/control change at that boundary. */
static void parse_stage_lifecycle(struct json_object* root, const char* request_id,
                                  const struct sockaddr_in* sender) {
    struct json_object *params = NULL, *action = NULL, *target = NULL;
    uint64_t target_step;
    int event;
    if (!json_object_object_get_ex(root, "params", &params) || json_object_get_type(params) != json_type_object ||
        json_object_object_length(params) != 2 ||
        !json_object_object_get_ex(params, "action", &action) || json_object_get_type(action) != json_type_string ||
        !json_object_object_get_ex(params, "target_step", &target) || !json_uint64(target, &target_step) ||
        !lifecycle_event_from_name(json_object_get_string(action), &event)) {
        send_receipt(sender, request_id, 0, "action and target_step are required", sequence, NULL);
        return;
    }
    pthread_mutex_lock(&command_lock);
    if (lifecycle_request.pending ||
        (lifecycle == HIL_RUNNING && (target_step <= sequence || target_step > sequence + ICD_ENVIRONMENT_MAX_LOOKAHEAD_STEPS)) ||
        (lifecycle != HIL_RUNNING && target_step != sequence)) {
        pthread_mutex_unlock(&command_lock);
        send_receipt(sender, request_id, 0, "lifecycle target is not an admissible actual model boundary", sequence, NULL);
        return;
    }
    pthread_mutex_unlock(&command_lock);
    queue_lifecycle_at(event, target_step, 1, request_id, sender);
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
    int reset_to_stopped = 0;
    char v3_mission_id[MISSION_ID_MAX] = "";
    pthread_mutex_lock(&model_boundary_lock);
    pthread_mutex_lock(&command_lock);
    if (!lifecycle_request.pending ||
        (lifecycle_request.target_bound && sequence < lifecycle_request.target_step)) {
        pthread_mutex_unlock(&command_lock);
        pthread_mutex_unlock(&model_boundary_lock);
        return;
    }
    request = lifecycle_request;
    lifecycle_request.pending = 0;
    pthread_mutex_unlock(&command_lock);

    if (request.target_bound && sequence != request.target_step) {
        send_receipt(&request.sender, request.request_id, 0, "lifecycle target boundary was missed", sequence, NULL);
        pthread_mutex_unlock(&model_boundary_lock);
        return;
    }

    if (request.event == HIL_PAUSED) {
        if (lifecycle != HIL_RUNNING) valid = 0;
        else { lifecycle = HIL_PAUSED; if (HIL_FIXED_WING_V3_TCP) fixed_wing_v3_tcp_send_event("pause", mission.mission_id); }
    } else if (request.event == HIL_RUNNING) {
        if (lifecycle != HIL_PAUSED && lifecycle != HIL_CONFIGURED) valid = 0;
        else {
            const int resumed = lifecycle == HIL_PAUSED;
            lifecycle = HIL_RUNNING;
            if (HIL_FIXED_WING_V3_TCP)
                fixed_wing_v3_tcp_send_event(resumed ? "resume" : "start", mission.mission_id);
        }
    } else if (request.event == HIL_ENDED) {
        if (lifecycle != HIL_RUNNING && lifecycle != HIL_PAUSED && lifecycle != HIL_CONFIGURED) valid = 0;
        else {
            lifecycle = HIL_ENDED;
            pthread_mutex_lock(&command_lock);
            strncpy(v3_mission_id, mission.mission_id, sizeof(v3_mission_id) - 1);
            v3_mission_id[sizeof(v3_mission_id) - 1] = '\0';
            mission.active = 0;
            mission.waypoint_count = 0;
            mission.mission_id[0] = '\0';
            mission.generation++;
            applied_mission_generation = mission.generation;
            pthread_mutex_unlock(&command_lock);
            mission_controller_reset();
            if (HIL_FIXED_WING_V3_TCP) fixed_wing_v3_tcp_send_event("mission_end", v3_mission_id);
        }
    } else if (request.event == HIL_STOPPED) {
        if (lifecycle == HIL_RESETTING || lifecycle == HIL_FAILED) valid = 0;
        else {
            lifecycle = HIL_STOPPED;
            pthread_mutex_lock(&command_lock);
            control_arbiter_clear(&control_arbiter);
            mission.active = 0;
            mission.waypoint_count = 0;
            mission.mission_id[0] = '\0';
            mission.generation++;
            applied_mission_generation = mission.generation;
            pthread_mutex_unlock(&command_lock);
            mission_controller_reset();
            zero_motor_command();
            if (have_valid_state) state.lifecycle = (uint8_t)lifecycle;
            if (HIL_FIXED_WING_V3_TCP) fixed_wing_v3_tcp_send_event("stop", "");
        }
    } else if (request.event == HIL_RESETTING) {
        if (lifecycle == HIL_RESETTING || lifecycle == HIL_FAILED) valid = 0;
        else {
            reset_to_stopped = lifecycle == HIL_STOPPED;
            lifecycle = HIL_RESETTING;
            /* Never publish a stale pre-reset state while the new model has
             * not yet emitted a valid normalized state. */
            have_valid_state = 0;
            model_terminate();
            model_initialize();
            prior_rates_valid = 0;
            fixed_wing_has_taken_off = 0;
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
            sequence = 0;
            sim_time_s = 0.0;
            pthread_mutex_lock(&command_lock);
            mission.active = 0;
            mission.waypoint_count = 0;
            mission.mission_id[0] = '\0';
            mission.generation++;
            applied_mission_generation = mission.generation;
            pthread_mutex_unlock(&command_lock);
            mission_controller_reset();
            pthread_mutex_lock(&command_lock);
            control_arbiter_clear(&control_arbiter);
            pthread_mutex_unlock(&command_lock);
            /* Reset returns to the safe configuration boundary.  A separate
             * start command is required before any model step can occur. */
            lifecycle = reset_to_stopped ? HIL_STOPPED : HIL_CONFIGURED;
            populate_state();
            memset(sensor_truth_valid, 0, sizeof(sensor_truth_valid));
            sensor_loss_accumulator = 0.0;
            record_sensor_truth();
            if (HIL_FIXED_WING_V3_TCP) {
                fixed_wing_v3_tcp_send_event("reset_scene", "");
                fixed_wing_v3_tcp_clear_mission();
            }
            send_reset_parameter_completion(sequence);
        }
    } else valid = 0;
    send_receipt(&request.sender, request.request_id, valid,
                 valid ? "applied" : "invalid lifecycle transition", sequence, NULL);
    pthread_mutex_unlock(&model_boundary_lock);
}

static void apply_live_update(void) {
    InputSnapshot snapshot;
    pthread_mutex_lock(&model_boundary_lock);
    pthread_mutex_lock(&command_lock);
    snapshot = pending_live;
    pthread_mutex_unlock(&command_lock);
    if (snapshot.generation != applied_live_generation) {
        active_input = snapshot.input;
        active_parameters = snapshot.parameters;
        *model_get_input() = active_input;
        hil_contract_apply_exported_globals(&active_parameters);
        applied_live_generation = snapshot.generation;
        latency_mark_applied(HIL_LATENCY_LIVE_INPUT, snapshot.generation);
    }
    pthread_mutex_unlock(&model_boundary_lock);
}

static void reject_icd_binding_stage(IcdBindingGroup group,
                                     const IcdBindingStage* snapshot,
                                     const char* reason) {
    pthread_mutex_lock(&command_lock);
    if (icd_binding_groups[group].state == ICD_ENVIRONMENT_STAGED &&
        !strcmp(icd_binding_groups[group].stage_request_id, snapshot->stage_request_id)) {
        icd_binding_groups[group].state = ICD_ENVIRONMENT_REJECTED;
        strncpy(icd_binding_groups[group].reason, reason,
                sizeof(icd_binding_groups[group].reason) - 1U);
    }
    pthread_mutex_unlock(&command_lock);
}

/* Commit one complete generated-contract group.  Work is performed on local
 * candidates first; active model memory changes only after every field has
 * validated and every generated setter succeeded. */
static void apply_icd_binding_group(IcdBindingGroup group, uint64_t next_step) {
    IcdBindingStage snapshot;
    ModelU_t input_candidate;
    HilParameterValues parameter_candidate;
    unsigned item;
    uint64_t now_ns = monotonic_time_ns();
    pthread_mutex_lock(&command_lock);
    snapshot = icd_binding_groups[group];
    input_candidate = active_input;
    parameter_candidate = active_parameters;
    pthread_mutex_unlock(&command_lock);
    if (snapshot.state != ICD_ENVIRONMENT_STAGED) return;
    if (snapshot.deadline_ns <= now_ns || snapshot.target_step < next_step) {
        reject_icd_binding_stage(group, &snapshot,
                                 snapshot.deadline_ns <= now_ns ? "EXPIRED" : "LATE");
        return;
    }
    if (snapshot.target_step != next_step) return;
    for (item = 0; item < snapshot.field_count; ++item) {
        if (group == ICD_GROUP_PARAMETERS) {
            const HilParameterSpec* spec = &HIL_PARAMETER_SPECS[snapshot.spec_indices[item]];
            if (!hil_contract_set_parameter(&input_candidate, &parameter_candidate,
                                            spec->name, snapshot.values[item][0])) {
                reject_icd_binding_stage(group, &snapshot, "GENERATED_SETTER_UNAVAILABLE");
                return;
            }
        } else {
            const HilInputSpec* spec = &HIL_INPUT_SPECS[snapshot.spec_indices[item]];
            if (!hil_contract_set_input(&input_candidate, spec->name,
                                        snapshot.values[item], snapshot.dimensions[item])) {
                reject_icd_binding_stage(group, &snapshot, "GENERATED_SETTER_UNAVAILABLE");
                return;
            }
        }
    }
    active_input = input_candidate;
    active_parameters = parameter_candidate;
    *model_get_input() = active_input;
    if (group == ICD_GROUP_PARAMETERS)
        hil_contract_apply_exported_globals(&active_parameters);
    for (item = 0; item < snapshot.field_count; ++item) {
        if (group == ICD_GROUP_PARAMETERS) {
            snapshot.readback[item][0] =
                active_parameters.value[snapshot.spec_indices[item]];
        } else {
            const HilInputSpec* spec = &HIL_INPUT_SPECS[snapshot.spec_indices[item]];
            if (!hil_contract_get_input(&active_input, spec->name,
                                        snapshot.readback[item], snapshot.dimensions[item])) {
                reject_icd_binding_stage(group, &snapshot, "GENERATED_GETTER_UNAVAILABLE");
                return;
            }
        }
    }
    pthread_mutex_lock(&command_lock);
    if (icd_binding_groups[group].state == ICD_ENVIRONMENT_STAGED &&
        !strcmp(icd_binding_groups[group].stage_request_id, snapshot.stage_request_id)) {
        for (item = 0; item < snapshot.field_count; ++item)
            memcpy(icd_binding_groups[group].readback[item], snapshot.readback[item],
                   snapshot.dimensions[item] * sizeof(double));
        icd_binding_groups[group].state = ICD_ENVIRONMENT_APPLIED;
        icd_binding_groups[group].applied_step = next_step;
        icd_binding_groups[group].model_revision = ++icd_binding_revisions[group];
        strncpy(icd_binding_groups[group].reason, "APPLIED",
                sizeof(icd_binding_groups[group].reason) - 1U);
    }
    pthread_mutex_unlock(&command_lock);
}

/* Runs only on the real-time model thread immediately before model_step().
 * This is the sole place an ICD Environment transaction becomes APPLIED. */
static void apply_icd_environment_stage(uint64_t next_step) {
    IcdEnvironmentStage snapshot;
    unsigned index;
    uint64_t now_ns = monotonic_time_ns();
    pthread_mutex_lock(&command_lock);
    snapshot = icd_environment;
    pthread_mutex_unlock(&command_lock);
    if (snapshot.state != ICD_ENVIRONMENT_STAGED) return;

    if (snapshot.deadline_ns <= now_ns || snapshot.target_step < next_step) {
        pthread_mutex_lock(&command_lock);
        if (icd_environment.state == ICD_ENVIRONMENT_STAGED &&
            !strcmp(icd_environment.stage_request_id, snapshot.stage_request_id)) {
            icd_environment.state = ICD_ENVIRONMENT_REJECTED;
            strncpy(icd_environment.reason, snapshot.deadline_ns <= now_ns ? "EXPIRED" : "LATE",
                    sizeof(icd_environment.reason) - 1U);
        }
        pthread_mutex_unlock(&command_lock);
        return;
    }
    if (snapshot.target_step != next_step) return;

    for (index = 0; index < ICD_ENVIRONMENT_FIELD_COUNT; ++index) {
        if (!hil_contract_set_input(&active_input, ICD_ENVIRONMENT_FIELDS[index],
                                    &snapshot.values[index], 1U)) {
            pthread_mutex_lock(&command_lock);
            if (icd_environment.state == ICD_ENVIRONMENT_STAGED &&
                !strcmp(icd_environment.stage_request_id, snapshot.stage_request_id)) {
                icd_environment.state = ICD_ENVIRONMENT_REJECTED;
                strncpy(icd_environment.reason, "GENERATED_SETTER_UNAVAILABLE",
                        sizeof(icd_environment.reason) - 1U);
            }
            pthread_mutex_unlock(&command_lock);
            return;
        }
    }
    *model_get_input() = active_input;

    pthread_mutex_lock(&command_lock);
    if (icd_environment.state == ICD_ENVIRONMENT_STAGED &&
        !strcmp(icd_environment.stage_request_id, snapshot.stage_request_id)) {
        for (index = 0; index < ICD_ENVIRONMENT_FIELD_COUNT; ++index)
            icd_environment.readback[index] = snapshot.values[index];
        icd_environment.state = ICD_ENVIRONMENT_APPLIED;
        icd_environment.applied_step = next_step;
        icd_environment.model_revision = ++icd_environment_revision;
        strncpy(icd_environment.reason, "APPLIED", sizeof(icd_environment.reason) - 1U);
    }
    pthread_mutex_unlock(&command_lock);
}

/* ID11 is committed beside Environment, before model_step(), so all thirteen
 * generated ExtU fault ports are a single snapshot for target step S. */
static void apply_icd_fault_stage(uint64_t next_step) {
    IcdFaultStage snapshot;
    unsigned index;
    uint64_t now_ns = monotonic_time_ns();
    pthread_mutex_lock(&command_lock);
    snapshot = icd_fault;
    pthread_mutex_unlock(&command_lock);
    if (snapshot.state != ICD_ENVIRONMENT_STAGED) return;
    if (snapshot.deadline_ns <= now_ns || snapshot.target_step < next_step) {
        pthread_mutex_lock(&command_lock);
        if (icd_fault.state == ICD_ENVIRONMENT_STAGED &&
            !strcmp(icd_fault.stage_request_id, snapshot.stage_request_id)) {
            icd_fault.state = ICD_ENVIRONMENT_REJECTED;
            strncpy(icd_fault.reason, snapshot.deadline_ns <= now_ns ? "EXPIRED" : "LATE",
                    sizeof(icd_fault.reason) - 1U);
        }
        pthread_mutex_unlock(&command_lock);
        return;
    }
    if (snapshot.target_step != next_step) return;
    for (index = 0; index < ICD_FAULT_FIELD_COUNT; ++index) {
        if (!hil_contract_set_input(&active_input, ICD_FAULT_FIELDS[index],
                                    &snapshot.values[index], 1U)) {
            pthread_mutex_lock(&command_lock);
            if (icd_fault.state == ICD_ENVIRONMENT_STAGED &&
                !strcmp(icd_fault.stage_request_id, snapshot.stage_request_id)) {
                icd_fault.state = ICD_ENVIRONMENT_REJECTED;
                strncpy(icd_fault.reason, "GENERATED_SETTER_UNAVAILABLE",
                        sizeof(icd_fault.reason) - 1U);
            }
            pthread_mutex_unlock(&command_lock);
            return;
        }
    }
    *model_get_input() = active_input;
    pthread_mutex_lock(&command_lock);
    if (icd_fault.state == ICD_ENVIRONMENT_STAGED &&
        !strcmp(icd_fault.stage_request_id, snapshot.stage_request_id)) {
        memcpy(icd_fault.readback, snapshot.values, sizeof(snapshot.values));
        icd_fault.state = ICD_ENVIRONMENT_APPLIED;
        icd_fault.applied_step = next_step;
        icd_fault.model_revision = ++icd_fault_revision;
        strncpy(icd_fault.reason, "APPLIED", sizeof(icd_fault.reason) - 1U);
    }
    pthread_mutex_unlock(&command_lock);
}

/* This runs after mission/external arbiter output.  It is therefore the
 * final motor writer observed by the generated model for target step S. */
static void apply_icd_flight_control_stage(uint64_t next_step) {
    IcdFlightStage snapshot;
    uint64_t now_ns = monotonic_time_ns();
    pthread_mutex_lock(&command_lock);
    snapshot = icd_flight;
    pthread_mutex_unlock(&command_lock);
    if (snapshot.state != ICD_ENVIRONMENT_STAGED) return;
    if (snapshot.deadline_ns <= now_ns || snapshot.target_step < next_step) {
        pthread_mutex_lock(&command_lock);
        if (icd_flight.state == ICD_ENVIRONMENT_STAGED &&
            !strcmp(icd_flight.stage_request_id, snapshot.stage_request_id)) {
            icd_flight.state = ICD_ENVIRONMENT_REJECTED;
            strncpy(icd_flight.reason, snapshot.deadline_ns <= now_ns ? "EXPIRED" : "LATE",
                    sizeof(icd_flight.reason) - 1U);
        }
        pthread_mutex_unlock(&command_lock);
        return;
    }
    if (snapshot.target_step != next_step) return;
    if (!hil_contract_set_actuators(&active_input, snapshot.values, HIL_ACTUATOR_COUNT)) {
        pthread_mutex_lock(&command_lock);
        if (icd_flight.state == ICD_ENVIRONMENT_STAGED &&
            !strcmp(icd_flight.stage_request_id, snapshot.stage_request_id)) {
            icd_flight.state = ICD_ENVIRONMENT_REJECTED;
            strncpy(icd_flight.reason, "GENERATED_SETTER_UNAVAILABLE",
                    sizeof(icd_flight.reason) - 1U);
        }
        pthread_mutex_unlock(&command_lock);
        return;
    }
    *model_get_input() = active_input;
    pthread_mutex_lock(&command_lock);
    if (icd_flight.state == ICD_ENVIRONMENT_STAGED &&
        !strcmp(icd_flight.stage_request_id, snapshot.stage_request_id)) {
        memcpy(icd_flight.readback, snapshot.values, sizeof(snapshot.values));
        icd_flight.state = ICD_ENVIRONMENT_APPLIED;
        icd_flight.applied_step = next_step;
        icd_flight.model_revision = ++icd_flight_revision;
        strncpy(icd_flight.reason, "APPLIED", sizeof(icd_flight.reason) - 1U);
    }
    pthread_mutex_unlock(&command_lock);
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
    latency_mark_applied(HIL_LATENCY_MISSION, snapshot.generation);
}

static void write_actuator_command(const float* actuator, unsigned count) {
    double values[HIL_ACTUATOR_COUNT ? HIL_ACTUATOR_COUNT : 1];
    unsigned index;
    if (!actuator || count != HIL_ACTUATOR_COUNT) {
        lifecycle = HIL_FAILED;
        running = 0;
        return;
    }
    for (index = 0; index < count; ++index) values[index] = actuator[index];
    if (!hil_contract_set_actuators(&active_input, values, count)) {
        fprintf(stderr, "[HIL] generated motor command setter unavailable\n");
        lifecycle = HIL_FAILED;
        running = 0;
        return;
    }
    *model_get_input() = active_input;
}

static void zero_motor_command(void) {
    const float actuator[HIL_ACTUATOR_COUNT ? HIL_ACTUATOR_COUNT : 1] = {0.0f};
    write_actuator_command(actuator, HIL_ACTUATOR_COUNT);
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
        if (has_live) {
            pending_live.input = live_candidate;
            pending_live.parameters = live_parameters;
            pending_live.generation++;
            latency_accept_locked(HIL_LATENCY_LIVE_INPUT, pending_live.generation,
                                  command_ingress_ns);
        }
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

static void parse_select_control_source(struct json_object* root, const char* request_id,
                                        const struct sockaddr_in* sender) {
    struct json_object* params = NULL;
    struct json_object* source_value = NULL;
    ControlSource source;
    if (!json_object_object_get_ex(root, "params", &params) ||
        json_object_get_type(params) != json_type_object ||
        !json_object_object_get_ex(params, "source", &source_value) ||
        json_object_get_type(source_value) != json_type_string) {
        send_receipt(sender, request_id, 0, "params.source is required", sequence, NULL);
        return;
    }
    source = control_source_from_name(json_object_get_string(source_value));
    pthread_mutex_lock(&command_lock);
    if (!control_source_allowed(source) ||
        (source == CONTROL_SOURCE_DEMO_MISSION && HIL_ACTUATOR_COUNT != 4U) ||
        !control_arbiter_select(&control_arbiter, source)) {
        pthread_mutex_unlock(&command_lock);
        send_receipt(sender, request_id, 0, "unsupported control source", sequence, NULL);
        return;
    }
    pthread_mutex_unlock(&command_lock);
    send_receipt(sender, request_id, 1, control_source_name(source), sequence + 1U, NULL);
}

static void parse_actuator_command(struct json_object* root, const char* request_id,
                                   const struct sockaddr_in* sender) {
    struct json_object *params = NULL, *source_value = NULL, *values = NULL;
    float command[HIL_MAX_ACTUATORS];
    ControlSource source;
    size_t index, count;
    if (!json_object_object_get_ex(root, "params", &params) ||
        json_object_get_type(params) != json_type_object ||
        !json_object_object_get_ex(params, "source", &source_value) ||
        json_object_get_type(source_value) != json_type_string ||
        !json_object_object_get_ex(params, "values", &values) ||
        json_object_get_type(values) != json_type_array) {
        send_receipt(sender, request_id, 0, "params.source and params.values are required", sequence, NULL);
        return;
    }
    source = control_source_from_name(json_object_get_string(source_value));
    count = json_object_array_length(values);
    pthread_mutex_lock(&command_lock);
    if (source == CONTROL_SOURCE_NONE || count != control_arbiter.actuator_count) {
        pthread_mutex_unlock(&command_lock);
        send_receipt(sender, request_id, 0, "control source or actuator count is invalid", sequence, NULL);
        return;
    }
    for (index = 0; index < count; ++index) {
        double value;
        int was_bool = 0;
        if (!valid_number(json_object_array_get_idx(values, index), &value, &was_bool) ||
            was_bool || value < HIL_ACTUATOR_SPECS[index].min_value ||
            value > HIL_ACTUATOR_SPECS[index].max_value) {
            pthread_mutex_unlock(&command_lock);
            send_receipt(sender, request_id, 0, "actuator command is outside its contract range", sequence, NULL);
            return;
        }
        command[index] = (float)value;
    }
    if (!control_arbiter_submit(&control_arbiter, source, command, (unsigned)count,
                                monotonic_time_ns())) {
        pthread_mutex_unlock(&command_lock);
        send_receipt(sender, request_id, 0, "source is not active", sequence, NULL);
        return;
    }
    pthread_mutex_unlock(&command_lock);
    send_receipt(sender, request_id, 1, "actuator command accepted", sequence + 1U, NULL);
}

static void parse_command(const char* text, const struct sockaddr_in* sender) {
    struct json_object *root, *request, *cmd;
    const char *request_id, *command;
    command_ingress_ns = monotonic_time_ns();
    root = json_tokener_parse(text);
    if (!root || json_object_get_type(root) != json_type_object) { send_receipt(sender, "", 0, "invalid JSON object", sequence, NULL); if (root) json_object_put(root); return; }
    if (!json_object_object_get_ex(root, "request_id", &request) || json_object_get_type(request) != json_type_string ||
        !json_object_object_get_ex(root, "cmd", &cmd) || json_object_get_type(cmd) != json_type_string) {
        send_receipt(sender, "", 0, "request_id and cmd are required", sequence, NULL); json_object_put(root); return;
    }
    request_id = json_object_get_string(request); command = json_object_get_string(cmd);
    if (!strcmp(command, "tune")) parse_tune(root, request_id, sender);
    else if (!strcmp(command, "set_inputs")) parse_set_inputs(root, request_id, sender);
    else if (!strcmp(command, "stage_icd_group")) parse_stage_icd_group(root, request_id, sender);
    else if (!strcmp(command, "get_icd_group_result")) parse_get_icd_group_result(root, request_id, sender);
    else if (!strcmp(command, "get_icd_snapshot")) parse_get_icd_snapshot(root, request_id, sender);
    else if (!strcmp(command, "get_hil_status")) parse_get_hil_status(request_id, sender);
    else if (!strcmp(command, "get_configuration_snapshot")) parse_get_configuration_snapshot(request_id, sender);
    else if (!strcmp(command, "configure")) parse_configure(root, request_id, sender);
    else if (!strcmp(command, "stage_lifecycle")) parse_stage_lifecycle(root, request_id, sender);
#if HIL_INITIAL_STATE_ABI_AVAILABLE
    else if (!strcmp(command, "set_model_initial_state")) parse_set_model_initial_state(root, request_id, sender);
    else if (!strcmp(command, "prepare_model_snapshot")) parse_prepare_model_snapshot(root, request_id, sender);
#endif
    else if (!strcmp(command, "stage_icd_environment")) parse_stage_icd_environment(root, request_id, sender);
    else if (!strcmp(command, "get_icd_environment_result")) parse_get_icd_environment_result(root, request_id, sender);
    else if (!strcmp(command, "stage_icd_fault")) parse_stage_icd_fault(root, request_id, sender);
    else if (!strcmp(command, "get_icd_fault_result")) parse_get_icd_fault_result(root, request_id, sender);
    else if (!strcmp(command, "stage_icd_flight_control")) parse_stage_icd_flight_control(root, request_id, sender);
    else if (!strcmp(command, "get_icd_flight_control_result")) parse_get_icd_flight_control_result(root, request_id, sender);
    else if (!strcmp(command, "get_parameter_registry")) parse_get_parameter_registry(request_id, sender);
    else if (!strcmp(command, "select_control_source")) parse_select_control_source(root, request_id, sender);
    else if (!strcmp(command, "actuator_command")) parse_actuator_command(root, request_id, sender);
    else if (!strcmp(command, "load_mission")) parse_load_mission(root, request_id, sender);
    else if (!strcmp(command, "start")) queue_lifecycle(HIL_RUNNING, request_id, sender);
    else if (!strcmp(command, "stop")) queue_lifecycle(HIL_STOPPED, request_id, sender);
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

static ControlSource active_control_source(void) {
    ControlSource source;
    pthread_mutex_lock(&command_lock);
    source = control_arbiter.active_source;
    pthread_mutex_unlock(&command_lock);
    return source;
}

int main(void) {
    pthread_t command_worker; struct timespec next; unsigned send_counter = 0;
    const unsigned short udp_cmd_port = configured_udp_port("HIL_UDP_CMD_PORT", UDP_CMD_PORT);
    const unsigned short udp_status_port = configured_udp_port("HIL_UDP_STATUS_PORT", UDP_STATUS_PORT);
    uint64_t next_latency_report_ns = 0;
    float mission_motor[HIL_ACTUATOR_COUNT ? HIL_ACTUATOR_COUNT : 1] = {0.0f};
    float external_actuator[HIL_ACTUATOR_COUNT ? HIL_ACTUATOR_COUNT : 1] = {0.0f};
    float actuator_safe_value[HIL_ACTUATOR_COUNT ? HIL_ACTUATOR_COUNT : 1];
    unsigned actuator_index;
    signal(SIGINT, on_signal); signal(SIGTERM, on_signal);
    if (hil_realtime_init(90) != 0) {
        HilRealtimeStats stats = hil_realtime_stats();
        fprintf(stderr,
                "[HIL] SCHED_FIFO/locked memory unavailable; refusing production start "
                "(sched_setscheduler=%d:%s mlockall=%d:%s)\n",
                stats.sched_setscheduler_errno,
                stats.sched_setscheduler_errno ? strerror(stats.sched_setscheduler_errno) : "ok",
                stats.mlockall_errno,
                stats.mlockall_errno ? strerror(stats.mlockall_errno) : "ok");
        return 1;
    }
    if (udp_init(udp_cmd_port, udp_status_port) != 0) { fprintf(stderr, "UDP initialization failed\n"); return 1; }
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
    for (actuator_index = 0; actuator_index < HIL_ACTUATOR_COUNT; ++actuator_index)
        actuator_safe_value[actuator_index] = (float)HIL_ACTUATOR_SPECS[actuator_index].safe_value;
    if (!control_arbiter_init(&control_arbiter, HIL_ACTUATOR_COUNT, actuator_safe_value,
                              EXTERNAL_CONTROL_TIMEOUT_NS)) {
        fprintf(stderr, "[HIL] control arbiter initialization failed\n");
        model_terminate(); udp_close(); return 1;
    }
    populate_state();
    record_sensor_truth();
    if (HIL_FIXED_WING_V3_TCP && !fixed_wing_v3_tcp_start()) {
        fprintf(stderr, "[HIL] fixed-wing V3 TCP worker start failed\n");
        model_terminate(); udp_close(); return 1;
    }
    if (pthread_create(&command_worker, NULL, command_thread, NULL) != 0) { model_terminate(); udp_close(); return 1; }
    clock_gettime(CLOCK_MONOTONIC, &next);
    while (running) {
        next.tv_nsec += STEP_NS; if (next.tv_nsec >= 1000000000L) { next.tv_sec++; next.tv_nsec -= 1000000000L; }
        apply_lifecycle_request();
        if (lifecycle == HIL_RUNNING) {
            ControlSource source = active_control_source();
            apply_live_update();
            apply_icd_binding_group(ICD_GROUP_ENVIRONMENT, sequence + 1U);
            apply_icd_binding_group(ICD_GROUP_FAULT, sequence + 1U);
            apply_icd_binding_group(ICD_GROUP_PARAMETERS, sequence + 1U);
            apply_icd_environment_stage(sequence + 1U);
            apply_icd_fault_stage(sequence + 1U);
            apply_mission_update();
            if (source == CONTROL_SOURCE_DEMO_MISSION && HIL_DEMO_MISSION_ENABLED &&
                HIL_ACTUATOR_COUNT == 4U) {
                configure_demo_mission_controller();
                mission_controller_step(have_valid_state ? (const FlightState_t*)&state : NULL, 0.001,
                                        mission_motor);
                if (mission_controller_take_landed_event()) {
                    lifecycle = HIL_ENDED;
                    if (HIL_FIXED_WING_V3_TCP)
                        fixed_wing_v3_tcp_send_event("mission_end", mission.mission_id);
                }
                write_actuator_command(mission_motor, HIL_ACTUATOR_COUNT);
            } else if (source != CONTROL_SOURCE_DEMO_MISSION) {
                pthread_mutex_lock(&command_lock);
                control_arbiter_get(&control_arbiter, monotonic_time_ns(),
                                    external_actuator, HIL_ACTUATOR_COUNT);
                pthread_mutex_unlock(&command_lock);
                write_actuator_command(external_actuator, HIL_ACTUATOR_COUNT);
            }
            apply_icd_flight_control_stage(sequence + 1U);
            apply_icd_binding_group(ICD_GROUP_FLIGHT_CONTROL, sequence + 1U);
            model_step(); sequence++; sim_time_s += 0.001; populate_state();
            record_sensor_truth();
            if (have_valid_state && sequence % 4U == 0U) {
                FlightStateV3_t sensor_sample;
                if (prepare_sensor_sample(&sensor_sample))
                    udp_send_sensor(&sensor_sample, sizeof(sensor_sample));
            }
        } else {
            zero_motor_command();
            if (have_valid_state) state.lifecycle = (uint8_t)lifecycle;
        }
        if (++send_counter >= SEND_INTERVAL) {
            if (have_valid_state) {
                udp_send_status(&state, sizeof(state));
                udp_send_monitor(&state, sizeof(state));
                if (HIL_FIXED_WING_V3_TCP) fixed_wing_v3_tcp_publish_state(&state);
                latency_record_output_completed();
            }
            if (monotonic_time_ns() >= next_latency_report_ns) {
                latency_report();
                next_latency_report_ns = monotonic_time_ns() + 10000000000ULL;
            }
            send_counter = 0;
        }
        clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL);
        { struct timespec now; clock_gettime(CLOCK_MONOTONIC, &now);
          { int64_t lateness = (int64_t)(now.tv_sec - next.tv_sec) * 1000000000LL + now.tv_nsec - next.tv_nsec;
            hil_realtime_record_deadline(lateness); } }
    }
    fixed_wing_v3_tcp_stop();
    { HilRealtimeStats stats = hil_realtime_stats();
      fprintf(stderr, "[HIL] realtime samples=%llu p99_abs_lateness_ns=%lld max_abs_lateness_ns=%lld over_250us=%llu non_realtime=%d\n",
              (unsigned long long)stats.samples, (long long)stats.p99_abs_lateness_ns, (long long)stats.max_abs_lateness_ns,
              (unsigned long long)stats.over_250us, stats.non_realtime); }
    latency_report();
    pthread_join(command_worker, NULL); model_terminate(); udp_close(); return 0;
}

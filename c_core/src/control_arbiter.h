#ifndef CONTROL_ARBITER_H
#define CONTROL_ARBITER_H

#include <stdint.h>

#define HIL_MAX_ACTUATORS 32U

typedef enum {
    CONTROL_SOURCE_NONE = 0,
    CONTROL_SOURCE_DEMO_MISSION,
    CONTROL_SOURCE_PX4_SITL,
    CONTROL_SOURCE_PHYSICAL_UUT
} ControlSource;

typedef struct {
    ControlSource active_source;
    unsigned actuator_count;
    float safe_value[HIL_MAX_ACTUATORS];
    float command[HIL_MAX_ACTUATORS];
    uint64_t last_command_ns;
    uint64_t timeout_ns;
} ControlArbiter;

int control_arbiter_init(ControlArbiter* arbiter, unsigned actuator_count,
                         const float* safe_values, uint64_t timeout_ns);
int control_arbiter_select(ControlArbiter* arbiter, ControlSource source);
int control_arbiter_submit(ControlArbiter* arbiter, ControlSource source,
                           const float* command, unsigned count,
                           uint64_t now_ns);
int control_arbiter_get(ControlArbiter* arbiter, uint64_t now_ns,
                        float* command, unsigned count);
const char* control_source_name(ControlSource source);
ControlSource control_source_from_name(const char* name);

#endif

#include "control_arbiter.h"

#include <string.h>

const char* control_source_name(ControlSource source)
{
    switch (source) {
    case CONTROL_SOURCE_DEMO_MISSION: return "demo_mission";
    case CONTROL_SOURCE_PX4_SITL: return "px4_sitl";
    case CONTROL_SOURCE_PHYSICAL_UUT: return "physical_uut";
    default: return "none";
    }
}

ControlSource control_source_from_name(const char* name)
{
    if (!name) return CONTROL_SOURCE_NONE;
    if (!strcmp(name, "demo_mission")) return CONTROL_SOURCE_DEMO_MISSION;
    if (!strcmp(name, "px4_sitl")) return CONTROL_SOURCE_PX4_SITL;
    if (!strcmp(name, "physical_uut")) return CONTROL_SOURCE_PHYSICAL_UUT;
    return CONTROL_SOURCE_NONE;
}

int control_arbiter_init(ControlArbiter* arbiter, unsigned actuator_count,
                         const float* safe_values, uint64_t timeout_ns)
{
    unsigned index;
    if (!arbiter || !safe_values || !actuator_count || actuator_count > HIL_MAX_ACTUATORS || !timeout_ns)
        return 0;
    memset(arbiter, 0, sizeof(*arbiter));
    arbiter->active_source = CONTROL_SOURCE_DEMO_MISSION;
    arbiter->actuator_count = actuator_count;
    arbiter->timeout_ns = timeout_ns;
    for (index = 0; index < actuator_count; ++index) {
        arbiter->safe_value[index] = safe_values[index];
        arbiter->command[index] = safe_values[index];
    }
    return 1;
}

int control_arbiter_select(ControlArbiter* arbiter, ControlSource source)
{
    unsigned index;
    if (!arbiter || source == CONTROL_SOURCE_NONE) return 0;
    arbiter->active_source = source;
    arbiter->last_command_ns = 0;
    for (index = 0; index < arbiter->actuator_count; ++index)
        arbiter->command[index] = arbiter->safe_value[index];
    return 1;
}

int control_arbiter_submit(ControlArbiter* arbiter, ControlSource source,
                           const float* command, unsigned count, uint64_t now_ns)
{
    unsigned index;
    if (!arbiter || !command || source == CONTROL_SOURCE_NONE ||
        source != arbiter->active_source || count != arbiter->actuator_count || !now_ns)
        return 0;
    for (index = 0; index < count; ++index) arbiter->command[index] = command[index];
    arbiter->last_command_ns = now_ns;
    return 1;
}

int control_arbiter_get(ControlArbiter* arbiter, uint64_t now_ns,
                        float* command, unsigned count)
{
    unsigned index;
    int valid = 1;
    if (!arbiter || !command || count != arbiter->actuator_count) return 0;
    if (arbiter->active_source != CONTROL_SOURCE_DEMO_MISSION &&
        (!arbiter->last_command_ns || now_ns - arbiter->last_command_ns > arbiter->timeout_ns))
        valid = 0;
    for (index = 0; index < count; ++index)
        command[index] = valid ? arbiter->command[index] : arbiter->safe_value[index];
    return valid;
}

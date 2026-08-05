#include <assert.h>
#include <stdio.h>

#include "control_arbiter.h"

int main(void)
{
    const float safe[4] = {0, 0, 0, 0};
    const float px4[4] = {0.2f, 0.3f, 0.4f, 0.5f};
    float output[4];
    ControlArbiter arbiter;

    assert(control_arbiter_init(&arbiter, 4U, safe, 100000000ULL));
    assert(arbiter.active_source == CONTROL_SOURCE_DEMO_MISSION);
    assert(control_arbiter_select(&arbiter, CONTROL_SOURCE_PX4_SITL));
    assert(!control_arbiter_submit(&arbiter, CONTROL_SOURCE_PHYSICAL_UUT,
                                   px4, 4U, 1000U));
    assert(control_arbiter_submit(&arbiter, CONTROL_SOURCE_PX4_SITL,
                                  px4, 4U, 1000U));
    assert(control_arbiter_get(&arbiter, 2000U, output, 4U));
    assert(output[0] == px4[0] && output[3] == px4[3]);
    assert(!control_arbiter_get(&arbiter, 100002000ULL, output, 4U));
    assert(output[0] == 0.0f && output[3] == 0.0f);
    puts("control_arbiter: all tests passed");
    return 0;
}

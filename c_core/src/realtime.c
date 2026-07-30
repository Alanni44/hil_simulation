#include "realtime.h"

#include <errno.h>
#include <limits.h>
#include <sched.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

static HilRealtimeStats stats;
static uint64_t histogram[1001];

int hil_realtime_init(int priority) {
    struct sched_param parameter;
    const char* allow_nonrt = getenv("HIL_ALLOW_NONRT");
    int scheduler_ok;
    int memory_lock_ok;
    memset(&parameter, 0, sizeof(parameter));
    parameter.sched_priority = priority;
    scheduler_ok = sched_setscheduler(0, SCHED_FIFO, &parameter) == 0;
    if (!scheduler_ok) stats.sched_setscheduler_errno = errno;
    memory_lock_ok = mlockall(MCL_CURRENT | MCL_FUTURE) == 0;
    if (!memory_lock_ok) stats.mlockall_errno = errno;
    if (!scheduler_ok || !memory_lock_ok) {
        if (allow_nonrt && !strcmp(allow_nonrt, "1")) {
            stats.non_realtime = 1;
            return 0;
        }
        return -1;
    }
    return 0;
}

void hil_realtime_record_deadline(int64_t lateness_ns) {
    int64_t absolute = lateness_ns < 0 ? -lateness_ns : lateness_ns;
    stats.samples++;
    if (absolute > stats.max_abs_lateness_ns) stats.max_abs_lateness_ns = absolute;
    if (absolute > 250000) stats.over_250us++;
    histogram[absolute / 1000 > 1000 ? 1000 : absolute / 1000]++;
}

HilRealtimeStats hil_realtime_stats(void) {
    uint64_t cumulative = 0, target = (stats.samples * 99 + 99) / 100;
    unsigned index;
    for (index = 0; index < 1001; ++index) {
        cumulative += histogram[index];
        if (cumulative >= target) { stats.p99_abs_lateness_ns = (int64_t)index * 1000; break; }
    }
    return stats;
}

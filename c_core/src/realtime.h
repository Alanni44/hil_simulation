#ifndef HIL_REALTIME_H
#define HIL_REALTIME_H

#include <stdint.h>

typedef struct {
    uint64_t samples;
    uint64_t over_250us;
    int64_t max_abs_lateness_ns;
    int64_t p99_abs_lateness_ns;
    int non_realtime;
} HilRealtimeStats;

/* Production returns non-zero unless FIFO scheduling and locked memory both
 * succeed.  Development may opt in to HIL_ALLOW_NONRT=1. */
int hil_realtime_init(int priority);
void hil_realtime_record_deadline(int64_t lateness_ns);
HilRealtimeStats hil_realtime_stats(void);

#endif

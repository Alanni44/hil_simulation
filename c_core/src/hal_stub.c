#include "hal_stub.h"
#include <math.h>
#include <stdio.h>

static float sim_time = 0.0f;

int32_t hal_system_init(void) {
    printf("[HAL] System initialized (STUB mode)\n");
    return 0;
}

void hal_system_deinit(void) {
    printf("[HAL] System deinitialized\n");
}

int32_t hal_ad_read_all(float* values, uint32_t count) {
    sim_time += 0.001f;
    for (uint32_t i = 0; i < count && i < 8; i++) {
        values[i] = 2.0f * sinf(sim_time * 2.0f * 3.14159f * (1.0f + i * 0.3f)) + i * 0.2f;
    }
    return 0;
}

int32_t hal_da_write_all(const float* values, uint32_t count) {
    static uint32_t counter = 0;
    counter++;
    if (counter % 1000 == 0) {
        printf("[HAL] DA output: %.2f, %.2f, %.2f, %.2f...\n",
               values[0], values[1], values[2], values[3]);
    }
    return 0;
}

int32_t hal_refmem_write(const void* data, uint32_t size) {
    static uint32_t counter = 0;
    counter++;
    if (counter % 1000 == 0) {
        printf("[HAL] RefMem write: %u bytes\n", size);
    }
    return 0;
}

int32_t hal_telemetry_send(const void* data, uint32_t size) {
    return 0;
}
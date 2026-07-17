#ifndef HAL_STUB_H
#define HAL_STUB_H

#include <stdint.h>

int32_t hal_ad_read_all(float* values, uint32_t count);
int32_t hal_da_write_all(const float* values, uint32_t count);
int32_t hal_refmem_write(const void* data, uint32_t size);
int32_t hal_telemetry_send(const void* data, uint32_t size);
int32_t hal_system_init(void);
void hal_system_deinit(void);

#endif
#ifndef LOCAL_UDP_H
#define LOCAL_UDP_H

#include "flight_state.h"
#include <stddef.h>
#include <netinet/in.h>

#define UDP_MONITOR_PORT 9999
#define UDP_SENSOR_PORT 9996

int udp_init(int command_port, int status_port);
void udp_send_status(const void* state, size_t state_size);
void udp_send_monitor(const void* state, size_t state_size);
void udp_send_sensor(const void* state, size_t state_size);
int udp_recv_command(char* buffer, int buffer_size, struct sockaddr_in* sender);
int udp_send_receipt(const char* receipt, const struct sockaddr_in* recipient);
void udp_close(void);

#endif

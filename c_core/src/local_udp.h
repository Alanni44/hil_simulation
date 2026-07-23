#ifndef LOCAL_UDP_H
#define LOCAL_UDP_H

#include "flight_state.h"

#define UDP_MONITOR_PORT 9999

int udp_init(int command_port, int status_port);
void udp_send_status(const FlightState_t* state);
void udp_send_monitor(const FlightState_t* state);
int udp_recv_command(char* buffer, int buffer_size);
void udp_close(void);

#endif
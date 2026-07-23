#include "local_udp.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

static int cmd_sock = -1;
static int status_sock = -1;
static int monitor_sock = -1;
static struct sockaddr_in status_addr;
static struct sockaddr_in monitor_addr;

int udp_init(int command_port, int status_port) {
    cmd_sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (cmd_sock < 0) return -1;

    struct timeval tv = {0, 100000};
    setsockopt(cmd_sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(command_port);
    addr.sin_addr.s_addr = inet_addr("127.0.0.1");
    if (bind(cmd_sock, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        close(cmd_sock);
        cmd_sock = -1;
        return -1;
    }
    printf("[UDP] Command socket bound to 127.0.0.1:%d\n", command_port);

    status_sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (status_sock < 0) {
        close(cmd_sock);
        cmd_sock = -1;
        return -1;
    }
    memset(&status_addr, 0, sizeof(status_addr));
    status_addr.sin_family = AF_INET;
    status_addr.sin_port = htons(status_port);
    status_addr.sin_addr.s_addr = inet_addr("127.0.0.1");
    printf("[UDP] Status socket ready to send to 127.0.0.1:%d\n", status_port);

    /* Monitor socket → UDP 9999 for test scripts */
    monitor_sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (monitor_sock < 0) {
        perror("[UDP] monitor socket");
    } else {
        memset(&monitor_addr, 0, sizeof(monitor_addr));
        monitor_addr.sin_family = AF_INET;
        monitor_addr.sin_port = htons(UDP_MONITOR_PORT);
        monitor_addr.sin_addr.s_addr = inet_addr("127.0.0.1");
        printf("[UDP] Monitor socket ready to send to 127.0.0.1:%d\n", UDP_MONITOR_PORT);
    }

    return 0;
}

void udp_send_status(const FlightState_t* state) {
    if (status_sock < 0) return;
    sendto(status_sock, state, sizeof(FlightState_t), 0,
           (struct sockaddr*)&status_addr, sizeof(status_addr));
}

void udp_send_monitor(const FlightState_t* state) {
    if (monitor_sock < 0) return;
    sendto(monitor_sock, state, sizeof(FlightState_t), 0,
           (struct sockaddr*)&monitor_addr, sizeof(monitor_addr));
}

int udp_recv_command(char* buffer, int buffer_size) {
    if (cmd_sock < 0) return -1;
    struct sockaddr_in from_addr;
    socklen_t from_len = sizeof(from_addr);
    int n = recvfrom(cmd_sock, buffer, buffer_size - 1, 0,
                     (struct sockaddr*)&from_addr, &from_len);
    if (n > 0) { buffer[n] = '\0'; return n; }
    return -1;
}

void udp_close(void) {
    if (cmd_sock >= 0) { close(cmd_sock); cmd_sock = -1; }
    if (status_sock >= 0) { close(status_sock); status_sock = -1; }
    if (monitor_sock >= 0) { close(monitor_sock); monitor_sock = -1; }
}
CC = gcc
CFLAGS = -O2 -Wall -pthread -fPIC -I./src
LDFLAGS = -lm -lrt -ljson-c -ldl

SRC_DIR = ./src
BUILD_DIR = ./build

SRCS = $(SRC_DIR)/main_rt.c \
       $(SRC_DIR)/model_loader.c \
       $(SRC_DIR)/hal_stub.c \
       $(SRC_DIR)/local_udp.c

TARGET = $(BUILD_DIR)/hil_core

all: dirs $(TARGET)

dirs:
	mkdir -p $(BUILD_DIR)

$(TARGET): $(SRCS)
	$(CC) $(CFLAGS) $^ -o $@ $(LDFLAGS)
	@echo "=== Build complete: $(TARGET) ==="
	@echo "Run with: sudo $(TARGET)"

clean:
	rm -rf $(BUILD_DIR)

.PHONY: all clean dirs
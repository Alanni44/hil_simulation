CC = gcc
CFLAGS = -O2 -Wall -pthread -I./src -I../model
LDFLAGS = -lm -lrt -ljson-c -lpthread

SRC_DIR = ./src
BUILD_DIR = ./build

SRCS = $(SRC_DIR)/main_rt.c \
       $(SRC_DIR)/model_rt_wrapper.c \
       $(SRC_DIR)/hal_stub.c \
       $(SRC_DIR)/local_udp.c

MODEL_SRCS = ../model/my_uav_model.c ../model/my_uav_model_data.c \
             ../model/rt_nonfinite.c ../model/rtGetInf.c ../model/rtGetNaN.c

TARGET = $(BUILD_DIR)/hil_rt

all: dirs $(TARGET)

dirs:
	mkdir -p $(BUILD_DIR)

$(TARGET): $(SRCS) $(MODEL_SRCS)
	$(CC) $(CFLAGS) -DMODEL_RT_BRIDGE_H=my_uav_model.h -DSKIP_STATIC_ASSERT \
	      -DMODEL_INIT_FN=my_uav_model_initialize \
	      -DMODEL_STEP_FN=my_uav_model_step \
	      -DMODEL_TERM_FN=my_uav_model_terminate \
	      -DMODEL_U_VAR=my_uav_model_U \
	      -DMODEL_Y_VAR=my_uav_model_Y \
	      $^ -o $@ $(LDFLAGS)
	@echo "=== Build complete: $(TARGET) ==="
	@echo "Run with: sudo $(TARGET)"

clean:
	rm -rf $(BUILD_DIR)

.PHONY: all clean dirs

# HIL仿真系统

## 系统概述
硬件在环（HIL）仿真飞行验证系统的核心计算引擎，运行于PXIe模型运算设备，负责以1ms周期执行Simulink飞行模型。

## 核心特性
- **硬实时调度**：1ms周期，抖动 < 50μs
- **模型热加载**：前端上传.slx → MATLAB自动生成代码 → 编译.so → 主程序不重启加载
- **多通道输出**：反射内存(3D显示) + UDP(Spring Boot) + TCP(UE4)
- **在线调参**：TCP JSON指令，即时生效
- **版本兼容**：MATLAB R2018b / R2019+ / R2020+ 均支持

## 架构说明
- **C核心（硬实时）** ：1ms调度、模型解算、HAL抽象
- **Python服务（控制与转发）** ：TCP调参、UDP转发、UE4推送、模型上传与构建
- **MATLAB脚本**：代码生成、动态库编译

## 快速开始

### 1. 安装依赖
```bash
sudo apt update
sudo apt install -y build-essential libjson-c-dev python3 python3-pip
pip3 install pyyaml# hil_simulation

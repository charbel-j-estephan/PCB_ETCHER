# DIY PCB Plotter & CNC Machine

A high-precision automated system designed to convert Gerber files into physical PCB layouts using a **PIC16F877A** for motion control and an **ESP32** for cloud-based file management.

---

## 🚀 Overview
This project bridges the gap between digital PCB design and physical prototyping. It features a custom-built CNC chassis capable of **400 steps/mm precision**, utilizing a frame-based UART protocol for reliable data transfer between the web interface and the motor controllers.

## 🛠️ Technical Specifications

### Hardware
* **Main Controller:** PIC16F877A (Running with a **4MHz Crystal**)
* **Network Bridge:** ESP32 (Web Server & Handshake Protocol)
* **Motors:** NEMA 17 Steppers with T8 Lead Screws
* **Drivers:** L293D H-Bridge with 74HC04 Logic Inverters
* **Actuator:** SG90 Servo for Pen Lift (PWM controlled)
* **Display:** 16x2 LCD (Port E: RS=RE2, RW=RE1, E=RE0)

### Software & Firmware
* **Motion Logic:** Custom implementation of the **Bresenham Algorithm** for linear interpolation.
* **Communication:** UART @ 9600 Baud with a custom frame-based handshake protocol.
* **Microstepping:** Calibrated for 1/16 microstepping.
* **Logic:** * `1` = Pen Down (Writing)
  * `0` = Pen Up (Moving)

## 📂 Project Structure
As shown in the repository:
* `3d prints/` - STL files for the CNC chassis and motor mounts.
* `asm/` - PIC16F877A Assembly source code and firmware.
* `documentations/` - Datasheets, wiring diagrams, and project notes.
* `esp32_firmware_v8_1/` - ESP32 source code for the Wi-Fi bridge.
* `pcb-plotter-server/` - Web interface and Gerber processing logic.
* `simulations/` - Proteus and circuit simulation files.

## 📐 Calibration Details
| Parameter | Value |
| :--- | :--- |
| **Resolution** | 400 steps/mm |
| **Step Angle** | 1.8° |
| **Lead Screw Pitch** | 8mm |
| **Microstepping** | 1/16 |
| **Baud Rate** | 9600 |

## 🏗️ System Architecture
1. **Web UI:** Users upload Gerber files to the `pcb-plotter-server`.
2. **Data Processing:** The ESP32 processes the coordinates and initiates a handshake with the PIC.
3. **Motion Execution:** The PIC16F877A receives instructions and generates precisely timed pulses for the NEMA 17 motors using Assembly-optimized routines.
4. **Homing:** Integrated hardware homing ensures a consistent zero-point.

---

## 🤝 Contributing
Feel free to fork this repo and submit pull requests for any optimizations in the motion algorithm or UI.

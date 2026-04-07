# AI Limits Mini-Dashboard

## Project Overview
A mini-dashboard for displaying usage limits of popular AI models: Claude Code and Antigravity.


![dashboard](https://github.com/user-attachments/assets/0a918d48-4b6b-42bf-97f6-2b9d55028eea)

To display the data, the project uses an affordable E-ink screen: the **CrowPanel ESP32 5.79-inch (272x792 resolution)**, powered by an ESP32-S3 microcontroller. 

This hardware configuration ensures fast rendering of your limits. Screen redraws are executed using **Partial Refresh**, allowing the image to update smoothly without the unwanted visual artifacts typically associated with full E-ink screen refreshes.

## Architecture Structure
Due to the limited processing resources of the ESP32-S3, all HTTP request logic—including external authorization—has been offloaded to an external mini-server (this can be a VPS or a local Raspberry Pi). 

This server handles all API requests and stores the data locally. A dedicated Python script acts as a micro web server, processing data retrieval requests for subsequent rendering on the E-ink panel. As a result, the internal logic on the ESP32 is kept to an absolute minimum: it simply fetches pre-formatted JSON data from the microserver and renders it on the screen.

## Hardware Requirements
* **E-ink Panel Used:** [CrowPanel ESP32 5.79" E-paper HMI Display](https://www.elecrow.com/crowpanel-esp32-5-79-e-paper-hmi-display-with-272-792-resolution-black-white-color-driven-by-spi-interface.html)

> **⚠️ Important Note:** This panel strictly requires an external power supply. Battery operation is not natively supported, and no battery is included in the kit.

## Installation & Setup

### 1. Firmware Setup (ESP32)
The `limitsdashboard.ino` file needs to be flashed onto your CrowPanel ESP32 board.
1. Download and install the [Arduino IDE](https://www.arduino.cc/en/software).
2. Install the ESP32 board library.
3. Select your board: **ESP32S3 Dev Module**.
4. In the **Tools** menu, configure the following settings:
   * **Partition Scheme:** `Huge App`
   * **PSRAM:** `OPI PSRAM`
5. Compile and upload the sketch to the board.

### 2. Backend Setup (Server/Raspberry Pi)
1. Copy all files from the `backend` folder to your designated server.
2. Run the `antigravity.py` and `claude.py` scripts manually. Follow the on-screen instructions to obtain your authorization tokens.
3. Once authenticated, configure these two scripts to run automatically (e.g., via cron jobs, as systemd services, or maintain their sessions using `tmux`).
4. After verifying that both scripts are successfully running on a schedule, start `microserver.py`. Set it up as a background service or run it via `tmux` as well.

Once completed, the ESP32's requests will be successfully intercepted by your backend, and the E-ink display will show updated usage limits every minute.

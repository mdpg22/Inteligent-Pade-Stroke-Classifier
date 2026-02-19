# 🏓 Padel Stroke Classifier

**Real-time padel stroke classification using Arduino Nano 33 BLE and TensorFlow Lite Micro**

Classify **drive**, **revés** (backhand), and **smash** strokes in real time using an IMU sensor and a neural network running on-device. Visualize results instantly through a Python dashboard connected via **USB Serial** or **Bluetooth Low Energy (BLE)**.

---

## 📋 Overview

This project implements an end-to-end pipeline for padel stroke recognition:

1. **Data Capture** — Collect IMU (accelerometer + gyroscope) data from an Arduino Nano 33 BLE mounted on the racket or wrist
2. **Model Training** — Train a TensorFlow neural network to classify stroke types from the captured data
3. **On-Device Inference** — Deploy the trained model as a TensorFlow Lite Micro model running directly on the Arduino
4. **Live Dashboard** — Visualize classified strokes, IMU statistics, and session analytics in real time via a Python GUI

The system supports both **wired (USB Serial)** and **wireless (BLE)** communication, allowing players to move freely on the court while streaming classification results to the dashboard.

---

## 🎯 Features

- **3 stroke classes**: Drive, Revés (backhand), Smash — plus automatic "descanso" (rest) detection for unrecognized movements
- **On-device classification**: TensorFlow Lite Micro runs inference directly on the Arduino — no cloud or phone required
- **Dual connectivity**: USB Serial for development, Bluetooth BLE for wireless play
- **Real-time dashboard** with:
  - Last stroke display with IMU acceleration summary
  - Drive/Revés ratio indicator
  - Smash percentage KPI
  - Stroke distribution pie chart and bar chart
  - Confidence timeline
  - Live stroke feed
  - Session export to CSV

---

## 🏗️ Architecture

```
┌─────────────────────┐     BLE / Serial     ┌──────────────────────┐
│   Arduino Nano 33   │ ──────────────────►   │   Python Dashboard   │
│        BLE          │                       │     (Tkinter +       │
│                     │                       │      Matplotlib)     │
│  ┌───────────────┐  │                       │                      │
│  │  BMI270 IMU   │  │                       │  • Live stats        │
│  │  (6-axis)     │  │                       │  • Charts            │
│  └───────┬───────┘  │                       │  • Stroke feed       │
│          │          │                       │  • CSV export        │
│  ┌───────▼───────┐  │                       └──────────────────────┘
│  │  TFLite Micro │  │
│  │  Classifier   │  │
│  └───────────────┘  │
└─────────────────────┘
```

---

## 📁 Project Structure

```
padel-stroke-classifier/
├── README.md
├── LICENSE
├── requirements.txt
├── .gitignore
│
├── arduino/
│   ├── IMU_Classifier_Padel/
│   │   ├── IMU_Classifier_Padel.ino    # Main classifier sketch (BLE + Serial)
│   │   └── model33.h                   # TFLite model as C header
│   └── IMU_Capture/
│       └── IMU_Capture.ino             # Data capture sketch
│
├── python/
│   ├── dashboard_padel.py              # Real-time dashboard (Serial + BLE)
│   ├── entrenar_modelo_padel.py        # Model training script
│   └── captura_datos_padel.py          # Data capture companion script
│
├── data/
│   ├── drive.csv                       # Captured drive stroke data
│   ├── reves.csv                       # Captured revés stroke data
│   └── smash.csv                       # Captured smash stroke data
│
└── models/
    └── gesture_model.tflite            # Trained TFLite model
```

---

## 🔧 Hardware Requirements

| Component | Details |
|-----------|---------|
| **Microcontroller** | Arduino Nano 33 BLE (Rev2) |
| **IMU Sensor** | On-board BMI270 (6-axis: accelerometer ±4G + gyroscope ±2000°/s) |
| **Power** | USB or 3.7V LiPo battery |
| **Mounting** | Attached to the padel racket handle or player's wrist |

---

## 💻 Software Requirements

### Arduino Libraries

Install via Arduino IDE Library Manager:

- `Arduino_BMI270_BMM150` — IMU driver
- `ArduinoBLE` — Bluetooth Low Energy
- `Arduino_TensorFlowLite` — TFLite Micro inference

### Python Dependencies

```bash
pip install pyserial matplotlib numpy bleak tensorflow scikit-learn pandas
```

> **Note**: `bleak` is optional — if not installed, only USB Serial connection is available in the dashboard.

---

## 🚀 Getting Started

### Step 1: Capture Training Data

1. Upload `arduino/IMU_Capture/IMU_Capture.ino` to the Arduino
2. Run the Python capture script:
   ```bash
   python python/captura_datos_padel.py
   ```
3. Follow the prompts to record multiple repetitions of each stroke type (drive, revés, smash)
4. CSV files are saved to the `data/` directory

### Step 2: Train the Model

```bash
python python/entrenar_modelo_padel.py
```

This script:
- Loads and augments the captured data (noise injection)
- Trains a Dense neural network (128→64→32 with BatchNorm and Dropout)
- Evaluates with confusion matrix and classification report
- Exports a TFLite model and generates `model.h` for Arduino

### Step 3: Deploy to Arduino

1. Copy the generated `model.h` to `arduino/IMU_Classifier_Padel/` and rename it to `model33.h`
2. Upload `arduino/IMU_Classifier_Padel/IMU_Classifier_Padel.ino` to the Arduino
3. The Arduino will advertise itself as **"PadelIMU"** over BLE

### Step 4: Run the Dashboard

```bash
python python/dashboard_padel.py
```

1. Click **"Conectar"** (Connect)
2. Choose **USB Serial** or **Bluetooth BLE**
3. For BLE: click **"Escanear"** (Scan), select **PadelIMU**, then **"Conectar BLE"**
4. Start playing — strokes are classified and displayed in real time!

---

## 📊 Model Architecture

```
Input (900) → Dense(128, ReLU) → BatchNorm → Dropout(0.3)
           → Dense(64, ReLU)  → BatchNorm → Dropout(0.3)
           → Dense(32, ReLU)  → Dropout(0.2)
           → Dense(3, Softmax) → Output (drive/revés/smash)
```

- **Input**: 150 samples × 6 channels (aX, aY, aZ, gX, gY, gZ) = 900 features
- **Normalization**: Acceleration [-4, 4]G → [0, 1], Gyroscope [-2000, 2000]°/s → [0, 1]
- **Training**: Adam optimizer, categorical crossentropy, early stopping, LR scheduling
- **Data augmentation**: Gaussian noise injection (2× augmentation factor)

---

## 📡 BLE Protocol

The Arduino uses the **Nordic UART Service (NUS)** to transmit classification results wirelessly:

| UUID | Characteristic |
|------|---------------|
| `6E400001-B5A3-F393-E0A9-E50E24DCCA9E` | NUS Service |
| `6E400003-B5A3-F393-E0A9-E50E24DCCA9E` | TX (Arduino → Dashboard) |

Each classified stroke transmits the following data block:

```
--- Resultado ---
  drive: 85.3%
  reves: 10.2%
  smash: 3.5%
--- IMU ---
accel_pico: 4.52
accel_media: 1.83
gyro_pico: 845.2
gyro_media: 312.4
accel_max_x: 3.21
accel_max_y: 2.10
accel_max_z: 1.85
>>> GOLPE DETECTADO: drive (85.3%)
```

---

## ⚙️ Configuration

Key parameters in the Arduino sketch (`IMU_Classifier_Padel.ino`):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `accelerationThreshold` | 2.5 G | Minimum acceleration to trigger capture |
| `numSamples` | 150 | Samples per stroke (~1.5s at 100Hz) |
| `confidenceThreshold` | 0.60 | Minimum confidence to report classification |

---

## 📸 Dashboard Preview

The dashboard provides a dark-themed real-time interface with:

- **Top**: Last stroke display with IMU statistics (peak acceleration, mean values, per-axis maximums)
- **Left panel**: Session statistics, drive/revés ratio bar, smash percentage, stroke count bars, and live feed
- **Right panel**: Pie chart (stroke distribution), bar chart (stroke counts), and confidence timeline

---

## 📄 License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgments

- Based on the [Arduino TensorFlow Lite gesture recognition example](https://github.com/arduino/ArduinoTensorFlowLiteTutorials)
- Built as part of the **Industry 4.0 Analysis** course (Master's program)
- Uses the [Nordic UART Service](https://developer.nordicsemi.com/nRF_Connect_SDK/doc/latest/nrf/include/bluetooth/services/nus.html) for BLE communication

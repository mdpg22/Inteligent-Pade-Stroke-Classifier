/*
  IMU Classifier - Padel Stroke Recognition

  Uses the on-board IMU to capture acceleration and gyroscope data,
  then classifies the movement as a padel stroke using a TensorFlow Lite
  (Micro) model running on the Arduino Nano 33 BLE.

  Classified strokes: Drive, Revés, Smash, Bandeja

  Adds:
  - IMU summary stats for the captured stroke window (printed in a "--- IMU ---" block)
    so your Python dashboard can parse and display:
      accel_pico, accel_media, gyro_pico, gyro_media, accel_max_x/y/z

  Based on the Arduino TensorFlowLite gesture recognition example.
  Adapted for padel stroke classification.
*/

#include <Arduino_BMI270_BMM150.h>

#include <TensorFlowLite.h>
#include <tensorflow/lite/micro/all_ops_resolver.h>
#include <tensorflow/lite/micro/micro_error_reporter.h>
#include <tensorflow/lite/micro/micro_interpreter.h>
#include <tensorflow/lite/schema/schema_generated.h>
#include <tensorflow/lite/version.h>

#include "model.h"

// ============================================================
// CONFIGURABLE PARAMETERS
// Must match the training configuration!
// ============================================================
const float accelerationThreshold = 2.5;  // Trigger threshold in G's
const int numSamples = 150;               // Samples per stroke (must match training)
const float confidenceThreshold = 0.60;   // Minimum confidence to report a classification

int samplesRead = numSamples;

// TensorFlow Lite (Micro) globals
tflite::MicroErrorReporter tflErrorReporter;
tflite::AllOpsResolver tflOpsResolver;

const tflite::Model* tflModel = nullptr;
tflite::MicroInterpreter* tflInterpreter = nullptr;
TfLiteTensor* tflInputTensor = nullptr;
TfLiteTensor* tflOutputTensor = nullptr;

// Memory buffer for TFLM
// Increase if you get allocation errors (model needs more memory)
constexpr int tensorArenaSize = 16 * 1024;
byte tensorArena[tensorArenaSize] __attribute__((aligned(16)));

// Padel stroke names - must match training order!
const char* GESTURES[] = {
  "drive",
  "reves",
  "smash",
};

#define NUM_GESTURES (sizeof(GESTURES) / sizeof(GESTURES[0]))

// LED feedback (optional - uses built-in LED)
const int LED_PIN = LED_BUILTIN;

// ============================================================
// IMU SUMMARY STATS (computed per captured stroke window)
// ============================================================
float accelMagMax = 0.0f, accelMagSum = 0.0f;
float gyroMagMax  = 0.0f, gyroMagSum  = 0.0f;
float accelMaxX = 0.0f, accelMaxY = 0.0f, accelMaxZ = 0.0f;

inline float mag3(float x, float y, float z) {
  return sqrtf(x * x + y * y + z * z);
}

void blinkLED(int times);

void setup() {
  Serial.begin(115200);
  while (!Serial);

  pinMode(LED_PIN, OUTPUT);

  // Initialize the IMU
  if (!IMU.begin()) {
    Serial.println("Failed to initialize IMU!");
    while (1);
  }

  Serial.print("Accelerometer sample rate = ");
  Serial.print(IMU.accelerationSampleRate());
  Serial.println(" Hz");
  Serial.print("Gyroscope sample rate = ");
  Serial.print(IMU.gyroscopeSampleRate());
  Serial.println(" Hz");
  Serial.print("Num samples per stroke = ");
  Serial.println(numSamples);
  Serial.print("Confidence threshold = ");
  Serial.print(confidenceThreshold * 100);
  Serial.println("%");
  Serial.println();

  // Load the TFL model
  tflModel = tflite::GetModel(model);
  if (tflModel->version() != TFLITE_SCHEMA_VERSION) {
    Serial.println("Model schema mismatch!");
    while (1);
  }

  // Create interpreter
  tflInterpreter = new tflite::MicroInterpreter(
    tflModel, tflOpsResolver, tensorArena, tensorArenaSize, &tflErrorReporter
  );

  // Allocate tensors
  tflInterpreter->AllocateTensors();

  // Get input/output tensor pointers
  tflInputTensor = tflInterpreter->input(0);
  tflOutputTensor = tflInterpreter->output(0);

  // Verify tensor dimensions
  Serial.print("Input tensor size: ");
  Serial.println(tflInputTensor->bytes);
  Serial.print("Expected input: ");
  Serial.print(numSamples * 6);
  Serial.println(" floats");

  Serial.println("\n=== CLASIFICADOR DE GOLPES DE PÁDEL ===");
  Serial.println("Esperando golpe...\n");
}

void loop() {
  float aX, aY, aZ, gX, gY, gZ;

  // ---- PHASE 1: Wait for significant motion (stroke trigger) ----
  while (samplesRead == numSamples) {
    if (IMU.accelerationAvailable()) {
      IMU.readAcceleration(aX, aY, aZ);

      float aSum = fabs(aX) + fabs(aY) + fabs(aZ);

      if (aSum >= accelerationThreshold) {
        samplesRead = 0;

        // Reset stroke stats
        accelMagMax = 0.0f; accelMagSum = 0.0f;
        gyroMagMax  = 0.0f; gyroMagSum  = 0.0f;
        accelMaxX = accelMaxY = accelMaxZ = 0.0f;

        break;
      }
    }
  }

  // ---- PHASE 2: Capture the full stroke data ----
  while (samplesRead < numSamples) {
    if (IMU.accelerationAvailable() && IMU.gyroscopeAvailable()) {
      IMU.readAcceleration(aX, aY, aZ);
      IMU.readGyroscope(gX, gY, gZ);

      // Update IMU stats for this stroke window (RAW values)
      float aMag = mag3(aX, aY, aZ);
      float gMag = mag3(gX, gY, gZ);

      accelMagSum += aMag;
      gyroMagSum  += gMag;

      if (aMag > accelMagMax) accelMagMax = aMag;
      if (gMag > gyroMagMax)  gyroMagMax  = gMag;

      float axAbs = fabs(aX), ayAbs = fabs(aY), azAbs = fabs(aZ);
      if (axAbs > accelMaxX) accelMaxX = axAbs;
      if (ayAbs > accelMaxY) accelMaxY = ayAbs;
      if (azAbs > accelMaxZ) accelMaxZ = azAbs;

      // Normalize data between 0 and 1 (must match training normalization!)
      tflInputTensor->data.f[samplesRead * 6 + 0] = (aX + 4.0) / 8.0;
      tflInputTensor->data.f[samplesRead * 6 + 1] = (aY + 4.0) / 8.0;
      tflInputTensor->data.f[samplesRead * 6 + 2] = (aZ + 4.0) / 8.0;
      tflInputTensor->data.f[samplesRead * 6 + 3] = (gX + 2000.0) / 4000.0;
      tflInputTensor->data.f[samplesRead * 6 + 4] = (gY + 2000.0) / 4000.0;
      tflInputTensor->data.f[samplesRead * 6 + 5] = (gZ + 2000.0) / 4000.0;

      samplesRead++;

      // ---- PHASE 3: Run inference when all samples collected ----
      if (samplesRead == numSamples) {
        // Run the model
        TfLiteStatus invokeStatus = tflInterpreter->Invoke();
        if (invokeStatus != kTfLiteOk) {
          Serial.println("Invoke failed!");
          while (1);
          return;
        }

        // Find the gesture with highest confidence
        int bestGesture = -1;
        float bestConfidence = 0.0;

        Serial.println("--- Resultado ---");
        for (int i = 0; i < NUM_GESTURES; i++) {
          float confidence = tflOutputTensor->data.f[i];
          Serial.print("  ");
          Serial.print(GESTURES[i]);
          Serial.print(": ");
          Serial.print(confidence * 100, 1);
          Serial.println("%");

          if (confidence > bestConfidence) {
            bestConfidence = confidence;
            bestGesture = i;
          }
        }

        // Print IMU summary block (Python dashboard parses this)
        float accelMean = accelMagSum / (float)numSamples;
        float gyroMean  = gyroMagSum  / (float)numSamples;

        Serial.println("--- IMU ---");
        Serial.print("accel_pico: ");   Serial.println(accelMagMax, 2);
        Serial.print("accel_media: ");  Serial.println(accelMean, 2);
        Serial.print("gyro_pico: ");    Serial.println(gyroMagMax, 1);
        Serial.print("gyro_media: ");   Serial.println(gyroMean, 1);
        Serial.print("accel_max_x: ");  Serial.println(accelMaxX, 2);
        Serial.print("accel_max_y: ");  Serial.println(accelMaxY, 2);
        Serial.print("accel_max_z: ");  Serial.println(accelMaxZ, 2);

        // Report the classification result
        if (bestGesture >= 0 && bestConfidence >= confidenceThreshold) {
          Serial.print(">>> GOLPE DETECTADO: ");
          Serial.print(GESTURES[bestGesture]);
          Serial.print(" (");
          Serial.print(bestConfidence * 100, 1);
          Serial.println("%)");

          // Visual feedback: blink LED
          blinkLED(bestGesture + 1);
        } else {
          Serial.println(">>> Golpe no reconocido (confianza baja)");
        }

        Serial.println();
      }
    }
  }
}

// Blink the LED N times to indicate the detected stroke
// 1 = drive, 2 = revés, 3 = smash, 4 = bandeja
void blinkLED(int times) {
  for (int i = 0; i < times; i++) {
    digitalWrite(LED_PIN, HIGH);
    delay(100);
    digitalWrite(LED_PIN, LOW);
    delay(100);
  }
}

/*
  IMU Capture - Padel Stroke Data Collection
  
  Captures acceleration and gyroscope data from the Arduino Nano 33 BLE
  IMU sensor for padel stroke classification.
  
  Strokes to classify: Drive, Revés, Smash, Bandeja
  
  Adaptations for padel:
  - Acceleration threshold adjusted for racket sport dynamics (3.0G)
  - Number of samples set to 150 (~1.5s at 100Hz) to capture 
    the full stroke including backswing and follow-through
  - Added stroke label protocol for Python capture script
  
  The circuit:
  - Arduino Nano 33 BLE or Arduino Nano 33 BLE Sense board
    mounted on the padel racket handle or wrist.
*/

#include <Arduino_BMI270_BMM150.h>

// ============================================================
// CONFIGURABLE PARAMETERS - Adjust these for your setup
// ============================================================

// Threshold to detect the start of a stroke (in G's).
// Padel strokes generate higher accelerations than simple arm movements.
// - A soft drive may produce ~2.5-3G
// - A smash can easily exceed 5-6G
// Set lower to capture softer strokes, higher to filter noise.
const float accelerationThreshold = 2.5;

// Number of samples to capture per stroke.
// IMU sample rate is ~104 Hz, so:
//   119 samples ≈ 1.14 seconds
//   150 samples ≈ 1.44 seconds (recommended for full stroke)
// A padel stroke (backswing + hit + follow-through) typically
// lasts 0.8-1.5 seconds.
const int numSamples = 150;

int samplesRead = numSamples;

void setup() {
  Serial.begin(115200);  // Higher baud rate for faster data transfer
  while (!Serial);

  if (!IMU.begin()) {
    Serial.println("Failed to initialize IMU!");
    while (1);
  }

  // Print IMU info for debugging
  Serial.print("Accelerometer sample rate = ");
  Serial.print(IMU.accelerationSampleRate());
  Serial.println(" Hz");
  Serial.print("Gyroscope sample rate = ");
  Serial.print(IMU.gyroscopeSampleRate());
  Serial.println(" Hz");
  Serial.print("Samples per stroke = ");
  Serial.println(numSamples);
  Serial.print("Acceleration threshold = ");
  Serial.print(accelerationThreshold);
  Serial.println(" G");
  Serial.println();

  // Signal ready to the Python capture script
  Serial.println("---READY---");
  
  // Print CSV header
  Serial.println("aX,aY,aZ,gX,gY,gZ");
}

void loop() {
  float aX, aY, aZ, gX, gY, gZ;

  // Wait for significant motion (stroke detection)
  while (samplesRead == numSamples) {
    if (IMU.accelerationAvailable()) {
      IMU.readAcceleration(aX, aY, aZ);

      // Sum of absolute accelerations
      float aSum = fabs(aX) + fabs(aY) + fabs(aZ);

      if (aSum >= accelerationThreshold) {
        samplesRead = 0;
        // Signal start of a new stroke capture
        Serial.println("---STROKE_START---");
        break;
      }
    }
  }

  // Capture all samples for this stroke
  while (samplesRead < numSamples) {
    if (IMU.accelerationAvailable() && IMU.gyroscopeAvailable()) {
      IMU.readAcceleration(aX, aY, aZ);
      IMU.readGyroscope(gX, gY, gZ);

      samplesRead++;

      // Print in CSV format with 3 decimal places
      Serial.print(aX, 3);
      Serial.print(',');
      Serial.print(aY, 3);
      Serial.print(',');
      Serial.print(aZ, 3);
      Serial.print(',');
      Serial.print(gX, 3);
      Serial.print(',');
      Serial.print(gY, 3);
      Serial.print(',');
      Serial.print(gZ, 3);
      Serial.println();

      if (samplesRead == numSamples) {
        // Signal end of stroke capture
        Serial.println("---STROKE_END---");
        Serial.println();
      }
    }
  }
}

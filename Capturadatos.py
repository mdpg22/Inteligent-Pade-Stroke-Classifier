#!/usr/bin/env python3
"""
Padel Stroke Data Capture Script
=================================
Reads IMU data directly from the Arduino Nano 33 BLE via serial port
and saves it into CSV files organized by stroke type.

Usage:
    python captura_datos_padel.py

Requirements:
    pip install pyserial numpy

The script will:
1. Connect to the Arduino via serial port
2. Ask you which stroke type you want to record
3. Capture each stroke automatically when the IMU detects motion
4. Save all strokes to a CSV file per stroke type
5. Allow you to switch between stroke types or finish

Stroke types: drive, reves, smash, bandeja
"""

import serial
import serial.tools.list_ports
import csv
import os
import sys
import time
import numpy as np
from datetime import datetime


# ============================================================
# CONFIGURATION
# ============================================================
BAUD_RATE = 115200
NUM_SAMPLES = 150          # Must match the Arduino sketch
CSV_HEADER = ['aX', 'aY', 'aZ', 'gX', 'gY', 'gZ']
STROKE_TYPES = ['drive', 'reves', 'smash', 'bandeja', 'ruido']
OUTPUT_DIR = 'data'        # Directory to save CSV files


def find_arduino_port():
    """Auto-detect Arduino serial port."""
    ports = serial.tools.list_ports.comports()
    arduino_ports = []
    
    for port in ports:
        desc = port.description.lower()
        if any(keyword in desc for keyword in ['arduino', 'nano', 'ble', 'usbmodem', 'acm', 'usb serial']):
            arduino_ports.append(port)
    
    if not arduino_ports:
        print("\nPuertos serie disponibles:")
        for i, port in enumerate(ports):
            print(f"  [{i}] {port.device} - {port.description}")
        
        if not ports:
            print("  No se encontraron puertos serie.")
            return None
        
        try:
            idx = int(input("\nSelecciona el número del puerto: "))
            return ports[idx].device
        except (ValueError, IndexError):
            print("Selección inválida.")
            return None
    
    if len(arduino_ports) == 1:
        print(f"Arduino detectado en: {arduino_ports[0].device}")
        return arduino_ports[0].device
    
    print("\nMúltiples Arduinos detectados:")
    for i, port in enumerate(arduino_ports):
        print(f"  [{i}] {port.device} - {port.description}")
    
    try:
        idx = int(input("Selecciona el número del puerto: "))
        return arduino_ports[idx].device
    except (ValueError, IndexError):
        return arduino_ports[0].device


def wait_for_ready(ser):
    """Wait for the Arduino to signal it's ready."""
    print("Esperando a que el Arduino esté listo...")
    while True:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line:
            print(f"  Arduino: {line}")
        if '---READY---' in line:
            print("¡Arduino listo!\n")
            return True


def capture_stroke(ser):
    """
    Capture one stroke from the serial port.
    Returns a list of sample rows, or None if capture failed.
    """
    samples = []
    capturing = False
    
    while True:
        try:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
        except serial.SerialException:
            print("Error de conexión serial.")
            return None
        
        if not line:
            continue
        
        if '---STROKE_START---' in line:
            capturing = True
            samples = []
            continue
        
        if '---STROKE_END---' in line:
            if len(samples) == NUM_SAMPLES:
                return samples
            else:
                print(f"  ⚠ Captura incompleta ({len(samples)}/{NUM_SAMPLES} muestras). Descartando...")
                return None
        
        if capturing:
            try:
                values = [float(v) for v in line.split(',')]
                if len(values) == 6:
                    samples.append(values)
            except ValueError:
                pass  # Skip malformed lines
    
    return None


def preview_stroke(samples):
    """
    Show a quick summary of the captured stroke so the user
    can decide whether to keep or discard it.
    """
    data = np.array(samples)
    # columns: aX, aY, aZ, gX, gY, gZ
    accel_mag = np.sqrt(data[:, 0]**2 + data[:, 1]**2 + data[:, 2]**2)
    gyro_mag = np.sqrt(data[:, 3]**2 + data[:, 4]**2 + data[:, 5]**2)
    
    print(f"\n    ┌─── Resumen de la captura ────────────────────┐")
    print(f"    │  Muestras:       {len(samples):>5d}                      │")
    print(f"    │  Acel. máx:      {accel_mag.max():>7.2f} G                  │")
    print(f"    │  Acel. media:    {accel_mag.mean():>7.2f} G                  │")
    print(f"    │  Gyro. máx:      {gyro_mag.max():>7.1f} °/s                │")
    print(f"    └───────────────────────────────────────────────┘")


def save_strokes_to_csv(stroke_type, all_samples, output_dir):
    """
    Save all captured strokes to a single CSV file.
    Each stroke is appended consecutively (NUM_SAMPLES rows per stroke).
    """
    filepath = os.path.join(output_dir, f"{stroke_type}.csv")
    
    # Check if file exists to decide whether to write header
    file_exists = os.path.exists(filepath) and os.path.getsize(filepath) > 0
    
    with open(filepath, 'a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(CSV_HEADER)
        for sample in all_samples:
            writer.writerow([f"{v:.3f}" for v in sample])
    
    return filepath


def remove_last_stroke(stroke_type, output_dir):
    """
    Remove the last captured stroke (last NUM_SAMPLES rows) from a CSV file.
    Returns True if successfully removed, False otherwise.
    """
    filepath = os.path.join(output_dir, f"{stroke_type}.csv")
    if not os.path.exists(filepath):
        return False
    
    with open(filepath, 'r') as f:
        lines = f.readlines()
    
    # lines[0] is the header, rest are data rows
    num_data_rows = len(lines) - 1
    
    if num_data_rows < NUM_SAMPLES:
        return False
    
    # Remove the last NUM_SAMPLES rows
    lines = lines[:len(lines) - NUM_SAMPLES]
    
    # If only the header remains, delete the file entirely
    if len(lines) <= 1:
        os.remove(filepath)
    else:
        with open(filepath, 'w') as f:
            f.writelines(lines)
    
    return True


def count_existing_strokes(stroke_type, output_dir):
    """Count how many strokes are already recorded in the CSV file."""
    filepath = os.path.join(output_dir, f"{stroke_type}.csv")
    if not os.path.exists(filepath):
        return 0
    
    with open(filepath, 'r') as f:
        reader = csv.reader(f)
        next(reader, None)  # Skip header
        num_rows = sum(1 for _ in reader)
    
    return num_rows // NUM_SAMPLES


def print_status(output_dir):
    """Print current data collection status."""
    print("\n" + "=" * 50)
    print("  ESTADO DE LA RECOGIDA DE DATOS")
    print("=" * 50)
    for stroke in STROKE_TYPES:
        count = count_existing_strokes(stroke, output_dir)
        bar = "█" * count + "░" * max(0, 20 - count)
        print(f"  {stroke:>8s}: [{bar}] {count} golpes")
    print("=" * 50)


def print_menu():
    """Print the stroke selection menu."""
    print("\nSelecciona el tipo de golpe a grabar:")
    for i, stroke in enumerate(STROKE_TYPES):
        print(f"  [{i + 1}] {stroke.upper()}")
    print(f"  [s] Ver estado")
    print(f"  [d] Eliminar último golpe de un tipo")
    print(f"  [r] Reiniciar archivo de un golpe")
    print(f"  [q] Finalizar y salir")


def main():
    print("=" * 50)
    print("  CAPTURA DE DATOS IMU - GOLPES DE PÁDEL")
    print("=" * 50)
    print(f"  Golpes: {', '.join(STROKE_TYPES)}")
    print(f"  Muestras por golpe: {NUM_SAMPLES}")
    print(f"  Directorio de salida: {OUTPUT_DIR}/")
    print("=" * 50)
    
    # Create output directory
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Find and connect to Arduino
    port = find_arduino_port()
    if not port:
        print("No se pudo encontrar el puerto del Arduino. Saliendo.")
        sys.exit(1)
    
    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=2)
        time.sleep(2)  # Wait for Arduino to reset after serial connection
    except serial.SerialException as e:
        print(f"Error al conectar con {port}: {e}")
        sys.exit(1)
    
    # Wait for Arduino ready signal
    wait_for_ready(ser)
    
    # Consume the CSV header line from Arduino
    ser.readline()
    
    print_status(OUTPUT_DIR)
    
    try:
        while True:
            print_menu()
            choice = input("\nTu elección: ").strip().lower()
            
            if choice == 'q':
                print("\n¡Sesión de captura finalizada!")
                print_status(OUTPUT_DIR)
                break
            
            if choice == 's':
                print_status(OUTPUT_DIR)
                continue
            
            if choice == 'r':
                print("¿Qué archivo quieres reiniciar?")
                for i, s in enumerate(STROKE_TYPES):
                    print(f"  [{i + 1}] {s}")
                r_choice = input("Número: ").strip()
                try:
                    idx = int(r_choice) - 1
                    stroke = STROKE_TYPES[idx]
                    filepath = os.path.join(OUTPUT_DIR, f"{stroke}.csv")
                    if os.path.exists(filepath):
                        os.remove(filepath)
                        print(f"  Archivo {stroke}.csv eliminado.")
                    else:
                        print(f"  No existe archivo para {stroke}.")
                except (ValueError, IndexError):
                    print("  Opción inválida.")
                continue
            
            if choice == 'd':
                print("¿De qué golpe quieres eliminar la última captura?")
                for i, s in enumerate(STROKE_TYPES):
                    count = count_existing_strokes(s, OUTPUT_DIR)
                    print(f"  [{i + 1}] {s} ({count} golpes)")
                d_choice = input("Número: ").strip()
                try:
                    idx = int(d_choice) - 1
                    stroke = STROKE_TYPES[idx]
                    if remove_last_stroke(stroke, OUTPUT_DIR):
                        new_count = count_existing_strokes(stroke, OUTPUT_DIR)
                        print(f"  Último golpe de {stroke} eliminado. Quedan {new_count}.")
                    else:
                        print(f"  No hay golpes que eliminar de {stroke}.")
                except (ValueError, IndexError):
                    print("  Opción inválida.")
                continue
            
            try:
                stroke_idx = int(choice) - 1
                if stroke_idx < 0 or stroke_idx >= len(STROKE_TYPES):
                    raise ValueError
            except ValueError:
                print("Opción no válida. Inténtalo de nuevo.")
                continue
            
            stroke_type = STROKE_TYPES[stroke_idx]
            existing = count_existing_strokes(stroke_type, OUTPUT_DIR)
            print(f"\n--- Grabando: {stroke_type.upper()} (ya hay {existing} golpes) ---")
            print("Realiza el golpe cuando quieras. Pulsa Ctrl+C para volver al menú.")
            print("Tras cada captura: [Enter] = guardar, [d] = descartar\n")
            
            stroke_count = 0
            discarded_count = 0
            try:
                while True:
                    print(f"  Esperando golpe de {stroke_type.upper()}... ", end='', flush=True)
                    
                    samples = capture_stroke(ser)
                    
                    if samples:
                        print(f"Capturado!")
                        preview_stroke(samples)
                        
                        # Ask user to keep or discard
                        decision = input("    ¿Guardar? [Enter]=Sí  [d]=Descartar: ").strip().lower()
                        
                        if decision == 'd':
                            discarded_count += 1
                            print(f"    ✗ Descartado. (Descartados en sesión: {discarded_count})")
                        else:
                            save_strokes_to_csv(stroke_type, samples, OUTPUT_DIR)
                            stroke_count += 1
                            total = existing + stroke_count
                            print(f"    ✓ Guardado! (Sesión: {stroke_count} | Total: {total})")
                        print()
                    else:
                        print("✗ Fallo en captura, reintentando...")
            
            except KeyboardInterrupt:
                print(f"\n\n  Sesión de {stroke_type}: {stroke_count} guardados, {discarded_count} descartados.")
    
    except KeyboardInterrupt:
        print("\n\nInterrumpido por el usuario.")
    
    finally:
        ser.close()
        print("Puerto serie cerrado. ¡Hasta luego!")


if __name__ == '__main__':
    main()
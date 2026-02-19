//
//  BluetoothPadelManager.swift
//  Padel_APP
//
//  Created by Santi López  on 16/2/26.
//
import Foundation
import CoreBluetooth
import Combine

final class BluetoothPadelManager: NSObject, ObservableObject {
    // Estado UI
    @Published var status: String = "Bluetooth: inicializando..."
    @Published var isConnected: Bool = false

    // DEMO
    @Published var demoMode: Bool = true   // <- ponlo a false cuando quieras volver a BLE real

    // Datos dashboard
    @Published var sessionStart = Date()
    @Published var totalStrokes: Int = 0
    @Published var strokesPerMin: Double = 0
    @Published var avgConfidence: Double = 0

    @Published var lastStroke: StrokeType = .descanso
    @Published var lastConfidence: Double = 0
    @Published var lastNote: String = ""

    @Published var gestureProbs = GestureProbs()
    @Published var imu = IMUSummary()
    @Published var history: [StrokeEvent] = []

    // BLE (se queda, pero en demo no lo usas)
    private var central: CBCentralManager!
    private var peripheral: CBPeripheral?

    private let nusServiceUUID = CBUUID(string: "6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
    private let nusTXUUID      = CBUUID(string: "6E400003-B5A3-F393-E0A9-E50E24DCCA9E")
    private var txChar: CBCharacteristic?

    private var rxBuffer = ""
    private var blockLines: [String] = []

    // Timer demo
    private var demoTimer: AnyCancellable?
    private var nextStrokeAt: Date = Date()

    override init() {
        super.init()
        central = CBCentralManager(delegate: self, queue: nil)

        if demoMode {
            startDemo()
        }
    }

    // MARK: - Public actions

    func startScan() {
        if demoMode {
            startDemo()
            return
        }

        guard central.state == .poweredOn else {
            status = "Bluetooth no está ON"
            return
        }
        status = "Escaneando (NUS)..."
        central.scanForPeripherals(withServices: [nusServiceUUID], options: [
            CBCentralManagerScanOptionAllowDuplicatesKey: false
        ])
    }

    func disconnect() {
        if demoMode {
            stopDemo()
            status = "Demo pausada"
            isConnected = false
            return
        }
        guard let p = peripheral else { return }
        central.cancelPeripheralConnection(p)
    }

    func toggleDemo(_ enabled: Bool) {
        demoMode = enabled
        if enabled {
            stopBLEIfNeeded()
            startDemo()
        } else {
            stopDemo()
            status = "Demo OFF (listo para BLE)"
            isConnected = false
        }
    }

    // MARK: - DEMO engine

    private func startDemo() {
        // reset sesión
        DispatchQueue.main.async {
            self.status = "DEMO: Generando datos..."
            self.isConnected = true  // para que tu UI ponga verde y "LIVE"
            self.sessionStart = Date()
            self.totalStrokes = 0
            self.strokesPerMin = 0
            self.avgConfidence = 0
            self.history.removeAll()
            self.gestureProbs = GestureProbs()
            self.imu = IMUSummary()
            self.lastStroke = .descanso
            self.lastConfidence = 0
            self.lastNote = "Demo activa"
        }

        // Próximo golpe aleatorio (cada 1.5–4.5s aprox)
        nextStrokeAt = Date().addingTimeInterval(Double.random(in: 1.0...2.5))

        demoTimer?.cancel()
        demoTimer = Timer
            .publish(every: 0.15, on: .main, in: .common)
            .autoconnect()
            .sink { [weak self] _ in
                self?.demoTick()
            }
    }

    private func stopDemo() {
        demoTimer?.cancel()
        demoTimer = nil
    }

    private func demoTick() {
        // Entre golpes: baja lentamente a descanso
        if Date() < nextStrokeAt {
            // Pequeña animación de “probabilidades” en descanso
            let drift = Double.random(in: -0.01...0.01)
            gestureProbs.drive = clamp01(gestureProbs.drive + drift)
            gestureProbs.reves = clamp01(gestureProbs.reves - drift)
            gestureProbs.smash = clamp01(gestureProbs.smash + Double.random(in: -0.008...0.008))
            normalizeProbs()
            return
        }

        // Genera un golpe
        let event = DemoStrokeGenerator.generate()

        // Actualiza modelo de “probabilidades” (top gesto alto, otros bajos)
        var probs = GestureProbs()
        probs.drive = event.type == .drive ? Double.random(in: 0.72...0.92) : Double.random(in: 0.02...0.18)
        probs.reves = event.type == .reves ? Double.random(in: 0.72...0.92) : Double.random(in: 0.02...0.18)
        probs.smash = event.type == .smash ? Double.random(in: 0.72...0.92) : Double.random(in: 0.02...0.18)
        // Normaliza para que tenga sentido (no obligatorio pero queda bonito)
        let sum = max(0.001, probs.drive + probs.reves + probs.smash)
        probs.drive /= sum; probs.reves /= sum; probs.smash /= sum

        // IMU demo realista según golpe
        let imuLocal = DemoStrokeGenerator.imu(for: event.type)

        // Nota
        var note = ""
        if imuLocal.accelPeak > 6.0 { note = "Golpe explosivo (accel pico alta)" }
        else if imuLocal.gyroPeak > 1200 { note = "Rotación alta (gyro pico alto)" }
        else { note = "Golpe detectado" }

        DispatchQueue.main.async {
            self.gestureProbs = probs
            self.imu = imuLocal

            self.lastStroke = event.type
            self.lastConfidence = event.confidence
            self.lastNote = note

            self.totalStrokes += 1
            let ev = StrokeEvent(date: Date(), type: event.type, confidence: event.confidence, note: note)
            self.history.insert(ev, at: 0)
            if self.history.count > 80 { self.history.removeLast() }

            let elapsed = Date().timeIntervalSince(self.sessionStart)
            if elapsed > 1 {
                self.strokesPerMin = Double(self.totalStrokes) / (elapsed / 60.0)
            }
            let confs = self.history.map { $0.confidence }
            self.avgConfidence = confs.isEmpty ? 0 : confs.reduce(0, +) / Double(confs.count)

            self.status = "DEMO: OK (\(self.totalStrokes) golpes)"
            self.isConnected = true
        }

        // Próximo golpe
        nextStrokeAt = Date().addingTimeInterval(Double.random(in: 1.4...4.2))
    }

    private func normalizeProbs() {
        let s = max(0.001, gestureProbs.drive + gestureProbs.reves + gestureProbs.smash)
        gestureProbs.drive /= s
        gestureProbs.reves /= s
        gestureProbs.smash /= s
    }

    private func clamp01(_ x: Double) -> Double { min(1, max(0, x)) }

    private func stopBLEIfNeeded() {
        if let p = peripheral {
            central.cancelPeripheralConnection(p)
        }
        central.stopScan()
        peripheral = nil
        txChar = nil
    }

    // MARK: - BLE RX handling (se mantiene por si desactivas demo)

    private func handleIncomingChunk(_ data: Data) {
        guard let chunk = String(data: data, encoding: .utf8) else { return }
        rxBuffer.append(chunk)

        while let range = rxBuffer.range(of: "\n") {
            let line = String(rxBuffer[..<range.lowerBound])
            rxBuffer.removeSubrange(..<range.upperBound)
            handleLine(line.trimmingCharacters(in: .whitespacesAndNewlines))
        }
    }

    private func handleLine(_ line: String) {
        if line.isEmpty {
            if !blockLines.isEmpty {
                let msg = blockLines.joined(separator: "\n")
                blockLines.removeAll(keepingCapacity: true)
                parseDashboardMessage(msg)
            }
            return
        }
        blockLines.append(line)
    }

    // Tu parser original (intacto)
    private func parseDashboardMessage(_ msg: String) {
        var probs = gestureProbs
        var imuLocal = imu
        var detectedType: StrokeType = .descanso
        var detectedConf: Double = 0
        var note = ""

        let lines = msg.split(separator: "\n").map { String($0).trimmingCharacters(in: .whitespaces) }

        for line in lines {
            if line.lowercased().hasPrefix("drive:") || (line.lowercased().contains("drive") && line.contains("%")) {
                probs.drive = parsePercent(line)
            } else if line.lowercased().hasPrefix("reves:") || (line.lowercased().contains("reves") && line.contains("%")) {
                probs.reves = parsePercent(line)
            } else if line.lowercased().hasPrefix("smash:") || (line.lowercased().contains("smash") && line.contains("%")) {
                probs.smash = parsePercent(line)
            } else if line.lowercased().hasPrefix("accel_pico:") {
                imuLocal.accelPeak = parseNumber(line)
            } else if line.lowercased().hasPrefix("accel_media:") {
                imuLocal.accelMean = parseNumber(line)
            } else if line.lowercased().hasPrefix("gyro_pico:") {
                imuLocal.gyroPeak = parseNumber(line)
            } else if line.lowercased().hasPrefix("gyro_media:") {
                imuLocal.gyroMean = parseNumber(line)
            } else if line.lowercased().hasPrefix("accel_max_x:") {
                imuLocal.accelMaxX = parseNumber(line)
            } else if line.lowercased().hasPrefix("accel_max_y:") {
                imuLocal.accelMaxY = parseNumber(line)
            } else if line.lowercased().hasPrefix("accel_max_z:") {
                imuLocal.accelMaxZ = parseNumber(line)
            }

            if line.contains(">>> GOLPE DETECTADO:") {
                let lower = line.lowercased()
                if lower.contains("drive") { detectedType = .drive }
                else if lower.contains("reves") { detectedType = .reves }
                else if lower.contains("smash") { detectedType = .smash }

                detectedConf = parsePercent(line)

                if imuLocal.accelPeak > 6.0 { note = "Golpe explosivo (accel pico alta)" }
                else if imuLocal.gyroPeak > 1200 { note = "Rotación alta (gyro pico alto)" }
                else { note = "Golpe detectado" }
            }

            if line.contains(">>> Golpe no reconocido") {
                detectedType = .descanso
                detectedConf = 0.0
                note = "Confianza baja"
            }
        }

        DispatchQueue.main.async {
            self.gestureProbs = probs
            self.imu = imuLocal
            self.lastStroke = detectedType
            self.lastConfidence = detectedConf
            self.lastNote = note

            if detectedType != .descanso {
                self.totalStrokes += 1
                let ev = StrokeEvent(date: Date(), type: detectedType, confidence: detectedConf, note: note)
                self.history.insert(ev, at: 0)
                if self.history.count > 80 { self.history.removeLast() }
            }

            let elapsed = Date().timeIntervalSince(self.sessionStart)
            if elapsed > 1 {
                self.strokesPerMin = Double(self.totalStrokes) / (elapsed / 60.0)
            }
            let confs = self.history.map { $0.confidence }
            self.avgConfidence = confs.isEmpty ? 0 : confs.reduce(0, +) / Double(confs.count)
        }
    }

    private func parsePercent(_ line: String) -> Double {
        if let pctRange = line.range(of: "%") {
            let prefix = line[..<pctRange.lowerBound]
            let comps = prefix.split(whereSeparator: { !"0123456789.".contains($0) })
            if let last = comps.last, let v = Double(last) {
                return v / 100.0
            }
        }
        return 0
    }

    private func parseNumber(_ line: String) -> Double {
        let comps = line.split(whereSeparator: { !"0123456789.-".contains($0) })
        if let last = comps.last, let v = Double(last) { return v }
        return 0
    }
}

// MARK: - DEMO generator helpers
private struct DemoStroke {
    let type: StrokeType
    let confidence: Double
}

private enum DemoStrokeGenerator {
    static func generate() -> DemoStroke {
        // Distribución típica: drive/revés más comunes, smash menos
        let r = Double.random(in: 0...1)
        let type: StrokeType
        if r < 0.46 { type = .drive }
        else if r < 0.86 { type = .reves }
        else { type = .smash }

        // Confianza realista
        let conf: Double
        switch type {
        case .drive: conf = Double.random(in: 0.68...0.92)
        case .reves: conf = Double.random(in: 0.66...0.90)
        case .smash: conf = Double.random(in: 0.72...0.96)
        default: conf = 0
        }

        return DemoStroke(type: type, confidence: conf)
    }

    static func imu(for type: StrokeType) -> IMUSummary {
        // Rangos inventados pero “creíbles”
        switch type {
        case .drive:
            return IMUSummary(
                accelPeak: Double.random(in: 3.2...6.0),
                accelMean: Double.random(in: 1.2...2.6),
                gyroPeak:  Double.random(in: 450...1050),
                gyroMean:  Double.random(in: 180...420),
                accelMaxX: Double.random(in: 1.2...3.0),
                accelMaxY: Double.random(in: 1.0...2.8),
                accelMaxZ: Double.random(in: 1.5...3.6)
            )
        case .reves:
            return IMUSummary(
                accelPeak: Double.random(in: 3.0...5.8),
                accelMean: Double.random(in: 1.1...2.5),
                gyroPeak:  Double.random(in: 550...1200),
                gyroMean:  Double.random(in: 220...520),
                accelMaxX: Double.random(in: 1.0...2.8),
                accelMaxY: Double.random(in: 1.2...3.2),
                accelMaxZ: Double.random(in: 1.4...3.4)
            )
        case .smash:
            return IMUSummary(
                accelPeak: Double.random(in: 5.6...9.5),
                accelMean: Double.random(in: 1.8...3.4),
                gyroPeak:  Double.random(in: 900...1700),
                gyroMean:  Double.random(in: 320...720),
                accelMaxX: Double.random(in: 2.0...4.2),
                accelMaxY: Double.random(in: 1.8...4.0),
                accelMaxZ: Double.random(in: 2.5...5.0)
            )
        default:
            return IMUSummary()
        }
    }
}

// MARK: - CBCentralManagerDelegate (BLE real)
extension BluetoothPadelManager: CBCentralManagerDelegate {
    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard !demoMode else { return }
        switch central.state {
        case .poweredOn: status = "Bluetooth ON"
        case .poweredOff: status = "Bluetooth OFF"
        case .unauthorized: status = "Bluetooth sin permisos"
        case .unsupported: status = "Bluetooth no soportado"
        case .resetting: status = "Bluetooth reiniciando"
        case .unknown: fallthrough
        @unknown default: status = "Bluetooth estado desconocido"
        }
    }

    func centralManager(_ central: CBCentralManager,
                        didDiscover peripheral: CBPeripheral,
                        advertisementData: [String : Any],
                        rssi RSSI: NSNumber) {
        guard !demoMode else { return }

        let name = (advertisementData[CBAdvertisementDataLocalNameKey] as? String) ?? peripheral.name ?? "?"
        guard name.contains("PadelIMU33") else { return }

        self.peripheral = peripheral
        self.peripheral?.delegate = self

        status = "Conectando..."
        central.stopScan()
        central.connect(peripheral, options: nil)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        guard !demoMode else { return }

        isConnected = true
        status = "Conectado. Descubriendo servicios..."

        sessionStart = Date()
        totalStrokes = 0
        strokesPerMin = 0
        avgConfidence = 0
        history.removeAll()
        rxBuffer = ""
        blockLines.removeAll()

        peripheral.discoverServices([nusServiceUUID])
    }

    func centralManager(_ central: CBCentralManager,
                        didFailToConnect peripheral: CBPeripheral,
                        error: Error?) {
        guard !demoMode else { return }
        isConnected = false
        status = "Falló conexión: \(error?.localizedDescription ?? "unknown")"
    }

    func centralManager(_ central: CBCentralManager,
                        didDisconnectPeripheral peripheral: CBPeripheral,
                        error: Error?) {
        guard !demoMode else { return }
        isConnected = false
        txChar = nil
        status = "Desconectado"
    }
}

// MARK: - CBPeripheralDelegate
extension BluetoothPadelManager: CBPeripheralDelegate {
    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard !demoMode else { return }
        if let error = error { status = "Error servicios: \(error.localizedDescription)"; return }
        guard let services = peripheral.services else { return }
        for s in services where s.uuid == nusServiceUUID {
            status = "Buscando TX characteristic..."
            peripheral.discoverCharacteristics([nusTXUUID], for: s)
        }
    }

    func peripheral(_ peripheral: CBPeripheral,
                    didDiscoverCharacteristicsFor service: CBService,
                    error: Error?) {
        guard !demoMode else { return }
        if let error = error { status = "Error chars: \(error.localizedDescription)"; return }
        guard let chars = service.characteristics else { return }
        for c in chars where c.uuid == nusTXUUID {
            txChar = c
            status = "Suscrito (NUS TX)"
            peripheral.setNotifyValue(true, for: c)
        }
    }

    func peripheral(_ peripheral: CBPeripheral,
                    didUpdateValueFor characteristic: CBCharacteristic,
                    error: Error?) {
        guard !demoMode else { return }
        if let error = error { status = "Error update: \(error.localizedDescription)"; return }
        guard characteristic.uuid == nusTXUUID, let data = characteristic.value else { return }
        handleIncomingChunk(data)
    }
}

//
//  ContentView.swift
//  Padel_APP
//
//  Created by Santi López  on 16/2/26.
//

import SwiftUI
import Charts

struct ContentView: View {
    @StateObject private var bt = BluetoothPadelManager()

    var body: some View {
        TabView {
            DashboardView(bt: bt)
                .tabItem { Label("Inicio", systemImage: "speedometer") }

            StatsView(bt: bt)
                .tabItem { Label("Stats", systemImage: "chart.pie") }

            TimelineView(bt: bt)
                .tabItem { Label("Historial", systemImage: "clock.arrow.circlepath") }
        }
    }
}

// MARK: - Helpers (cards / spacing)
private struct Card<Content: View>: View {
    let title: String?
    let content: Content
    init(title: String? = nil, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let title {
                Text(title.uppercased())
                    .font(.caption.weight(.bold))
                    .foregroundStyle(.secondary)
            }
            content
        }
        .padding(14)
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}

private struct KPI: View {
    let title: String
    let value: String
    let icon: String
    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundStyle(.primary)

            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.caption).foregroundStyle(.secondary)
                Text(value).font(.title3.weight(.bold))
            }

            Spacer()
        }
        .padding(12)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
    }
}

private func strokeColor(_ s: StrokeType) -> Color {
    switch s {
    case .drive: return .cyan
    case .reves: return .yellow
    case .smash: return .red
    case .descanso: return .gray
    }
}

// MARK: - 1) Dashboard (principal)
struct DashboardView: View {
    @ObservedObject var bt: BluetoothPadelManager

    var body: some View {
        NavigationStack {
            ScrollView(showsIndicators: false) {
                VStack(spacing: 12) {

                    // Conexión
                    Card(title: "Conexión") {
                        HStack(spacing: 10) {
                            Circle()
                                .fill(bt.isConnected ? .green : .red)
                                .frame(width: 10, height: 10)
                            Text(bt.isConnected ? "Conectado" : "Desconectado")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)

                            Spacer()

                            Button("Conectar") { bt.startScan() }
                                .buttonStyle(.borderedProminent)

                            Button("Desconectar") { bt.disconnect() }
                                .buttonStyle(.bordered)
                                .disabled(!bt.isConnected)
                        }

                        Text(bt.status)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    // KPIs (2 por fila, responsive)
                    Card(title: "KPIs") {
                        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                            KPI(title: "Golpes", value: "\(bt.totalStrokes)", icon: "figure.tennis")
                            KPI(title: "Golpes/min", value: String(format: "%.1f", bt.strokesPerMin), icon: "speedometer")
                            KPI(title: "Conf. media", value: String(format: "%.0f%%", bt.avgConfidence * 100), icon: "checkmark.seal.fill")
                            KPI(title: "Sesión", value: sessionElapsed(from: bt.sessionStart), icon: "clock.fill")
                        }
                    }

                    // Último golpe (layout adaptado)
                    Card(title: "Último golpe") {
                        HStack(alignment: .center, spacing: 12) {
                            ZStack {
                                Circle().stroke(Color.secondary.opacity(0.25), lineWidth: 10)
                                Circle()
                                    .trim(from: 0, to: max(0, min(1, bt.lastConfidence)))
                                    .stroke(strokeColor(bt.lastStroke), style: StrokeStyle(lineWidth: 10, lineCap: .round))
                                    .rotationEffect(.degrees(-90))
                                    .animation(.easeOut(duration: 0.25), value: bt.lastConfidence)

                                Text("\(Int(bt.lastConfidence * 100))%")
                                    .font(.headline.weight(.bold))
                            }
                            .frame(width: 72, height: 72)

                            VStack(alignment: .leading, spacing: 6) {
                                HStack(spacing: 8) {
                                    Label(bt.lastStroke.rawValue, systemImage: "bolt.fill")
                                        .font(.caption.weight(.semibold))
                                        .padding(.horizontal, 10)
                                        .padding(.vertical, 6)
                                        .background(strokeColor(bt.lastStroke).opacity(0.18))
                                        .clipShape(Capsule())

                                    if bt.isConnected {
                                        Text("LIVE")
                                            .font(.caption.weight(.bold))
                                            .padding(.horizontal, 10)
                                            .padding(.vertical, 6)
                                            .background(Color.green.opacity(0.18))
                                            .clipShape(Capsule())
                                    }
                                }

                                Text(bt.lastStroke.rawValue)
                                    .font(.title.weight(.bold))
                                    .lineLimit(1)
                                    .minimumScaleFactor(0.7)

                                Text(bt.lastNote.isEmpty ? "—" : bt.lastNote)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(2)
                            }

                            Spacer()
                        }
                    }

                    // IMU resumen compacto (en 2 filas)
                    Card(title: "IMU") {
                        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                            imuRow("Accel pico", bt.imu.accelPeak, unit: "G")
                            imuRow("Accel media", bt.imu.accelMean, unit: "G")
                            imuRow("Gyro pico", bt.imu.gyroPeak, unit: "°/s")
                            imuRow("Gyro media", bt.imu.gyroMean, unit: "°/s")
                        }
                    }
                }
                .padding(12)
            }
            .navigationTitle("Dashboard")
        }
    }

    private func imuRow(_ name: String, _ v: Double, unit: String) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(name).font(.caption).foregroundStyle(.secondary)
                Text(String(format: "%.2f %@", v, unit)).font(.headline.weight(.bold))
            }
            Spacer()
        }
        .padding(12)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
    }

    private func sessionElapsed(from start: Date) -> String {
        let elapsed = Date().timeIntervalSince(start)
        let m = Int(elapsed) / 60
        let s = Int(elapsed) % 60
        return String(format: "%02d:%02d", m, s)
    }
}

// MARK: - 2) Stats
struct StatsView: View {
    @ObservedObject var bt: BluetoothPadelManager

    var body: some View {
        NavigationStack {
            ScrollView(showsIndicators: false) {
                VStack(spacing: 12) {

                    Card(title: "Ratio Drive / Revés") {
                        let drive = count(.drive)
                        let reves = count(.reves)
                        let total = max(1, drive + reves)

                        VStack(alignment: .leading, spacing: 10) {
                            HStack {
                                chip("DRIVE \(pct(drive, total))%", .cyan)
                                chip("REVÉS \(pct(reves, total))%", .yellow)
                                Spacer()
                                chip("SMASH \(Int(smashRatio()*100))%", .red)
                            }

                            ProgressView(value: Double(drive), total: Double(total))
                                .tint(.cyan)
                                .scaleEffect(x: 1, y: 2.0, anchor: .center)
                        }
                    }

                    Card(title: "Distribución") {
                        let data = pieData()
                        Chart(data, id: \.0) { item in
                            SectorMark(angle: .value("Count", item.1), innerRadius: .ratio(0.55))
                                .foregroundStyle(colorFor(item.0))
                        }
                        .frame(height: 240)
                    }

                    Card(title: "Conteo") {
                        let bars = barData()
                        Chart(bars, id: \.0) { item in
                            BarMark(x: .value("Golpe", item.0),
                                    y: .value("Cantidad", item.1))
                            .foregroundStyle(colorFor(item.0))
                        }
                        .frame(height: 240)
                    }
                }
                .padding(12)
            }
            .navigationTitle("Stats")
        }
    }

    private func chip(_ text: String, _ color: Color) -> some View {
        Text(text)
            .font(.caption.weight(.bold))
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(color.opacity(0.18))
            .clipShape(Capsule())
    }

    private func count(_ t: StrokeType) -> Int { bt.history.filter { $0.type == t }.count }
    private func smashRatio() -> Double {
        let s = Double(count(.smash))
        let tot = Double(max(1, bt.history.count))
        return s / tot
    }
    private func pct(_ part: Int, _ total: Int) -> Int {
        guard total > 0 else { return 0 }
        return Int((Double(part) / Double(total)) * 100.0)
    }

    private func pieData() -> [(String, Int)] {
        [("DRIVE", count(.drive)), ("REVÉS", count(.reves)), ("SMASH", count(.smash))]
    }
    private func barData() -> [(String, Int)] {
        [("DRIVE", count(.drive)), ("REVÉS", count(.reves)), ("SMASH", count(.smash))]
    }

    private func colorFor(_ name: String) -> Color {
        switch name.uppercased() {
        case "DRIVE": return .cyan
        case "REVÉS", "REVES": return .yellow
        case "SMASH": return .red
        default: return .gray
        }
    }
}

// MARK: - 3) Timeline
struct TimelineView: View {
    @ObservedObject var bt: BluetoothPadelManager

    var body: some View {
        NavigationStack {
            ScrollView(showsIndicators: false) {
                VStack(spacing: 12) {

                    Card(title: "Confianza por golpe") {
                        let points = bt.history.prefix(30).reversed().enumerated().map { (idx, ev) in
                            (idx, ev)
                        }
                        Chart(points, id: \.0) { item in
                            LineMark(x: .value("N", item.0),
                                     y: .value("Confianza", item.1.confidence))
                                .foregroundStyle(strokeColor(item.1.type))
                            PointMark(x: .value("N", item.0),
                                      y: .value("Confianza", item.1.confidence))
                                .foregroundStyle(strokeColor(item.1.type))
                        }
                        .chartYScale(domain: 0...1)
                        .frame(height: 220)
                    }

                    Card(title: "Últimos golpes") {
                        if bt.history.isEmpty {
                            Text("Sin datos todavía. Conecta y golpea.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        } else {
                            VStack(spacing: 10) {
                                ForEach(bt.history.prefix(25)) { ev in
                                    HStack(spacing: 10) {
                                        Circle()
                                            .fill(strokeColor(ev.type))
                                            .frame(width: 10, height: 10)

                                        Text(time(ev.date))
                                            .font(.system(.caption, design: .monospaced))
                                            .foregroundStyle(.secondary)
                                            .frame(width: 72, alignment: .leading)

                                        Text(ev.type.rawValue)
                                            .font(.subheadline.weight(.semibold))

                                        Spacer()

                                        Text(String(format: "%.0f%%", ev.confidence * 100))
                                            .font(.system(.caption, design: .monospaced))
                                            .foregroundStyle(.secondary)
                                    }
                                    Divider().opacity(0.35)
                                }
                            }
                        }
                    }
                }
                .padding(12)
            }
            .navigationTitle("Historial")
        }
    }

    private func time(_ d: Date) -> String {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f.string(from: d)
    }
}

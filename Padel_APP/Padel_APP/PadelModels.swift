//
//  PadelModels.swift
//  Padel_APP
//
//  Created by Santi López  on 16/2/26.
//
import Foundation

enum StrokeType: String, CaseIterable {
    case drive = "DRIVE"
    case reves = "REVÉS"
    case smash = "SMASH"
    case descanso = "DESCANSO"
}

struct StrokeEvent: Identifiable {
    let id = UUID()
    let date: Date
    let type: StrokeType
    let confidence: Double   // 0..1
    let note: String
}

struct IMUSummary {
    var accelPeak: Double = 0
    var accelMean: Double = 0
    var gyroPeak: Double = 0
    var gyroMean: Double = 0
    var accelMaxX: Double = 0
    var accelMaxY: Double = 0
    var accelMaxZ: Double = 0
}

struct GestureProbs {
    var drive: Double = 0
    var reves: Double = 0
    var smash: Double = 0
}


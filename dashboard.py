#!/usr/bin/env python3
"""
Dashboard de Pádel en Tiempo Real
===================================
Lee las predicciones del clasificador IMU en el Arduino Nano 33 BLE
y muestra un dashboard con estadísticas en tiempo real.

Golpes: drive, revés, smash, descanso

Features:
- Último golpe en grande con resumen de aceleraciones
- Ratio drive/revés
- Porcentaje de smash
- Distribución y conteo de golpes
- Línea temporal de confianza
- Exportar sesión a CSV

Usage:
    python dashboard_padel.py

Requirements:
    pip install pyserial matplotlib numpy
"""

import tkinter as tk
from tkinter import ttk, messagebox
import serial
import serial.tools.list_ports
import threading
import time
import re
import csv
import os
from datetime import datetime, timedelta
from collections import deque

import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.ticker as mticker
import numpy as np


# ============================================================
# CONFIGURATION
# ============================================================
BAUD_RATE = 115200
STROKE_TYPES = ['drive', 'reves', 'smash']
ALL_CLASSES = ['drive', 'reves', 'smash', 'descanso']

COLORS = {
    'drive':    '#2196F3',
    'reves':    '#FF9800',
    'smash':    '#F44336',
    'descanso': '#9E9E9E',
}

# App styling
BG_COLOR = '#1a1a2e'
BG_CARD = '#16213e'
BG_CARD_ALT = '#0f3460'
TEXT_COLOR = '#e0e0e0'
TEXT_ACCENT = '#ffffff'
TEXT_DIM = '#8a8a9a'
ACCENT_COLOR = '#e94560'

FONT_TITLE = ('Helvetica', 24, 'bold')
FONT_SUBTITLE = ('Helvetica', 14, 'bold')
FONT_LABEL = ('Helvetica', 11)
FONT_VALUE = ('Helvetica', 28, 'bold')
FONT_BIG_STROKE = ('Helvetica', 42, 'bold')
FONT_SMALL = ('Helvetica', 10)
FONT_FEED = ('Courier', 11)
FONT_IMU_VAL = ('Helvetica', 16, 'bold')
FONT_IMU_LBL = ('Helvetica', 9)

TIMELINE_MAX = 50
FEED_MAX = 12
REFRESH_INTERVAL = 500


# ============================================================
# DATA MODEL
# ============================================================
class StrokeEvent:
    """Represents a single classified stroke."""
    def __init__(self, stroke_type, confidence, all_confidences,
                 imu_stats=None, timestamp=None):
        self.stroke_type = stroke_type
        self.confidence = confidence
        self.all_confidences = all_confidences
        self.imu_stats = imu_stats or {}  # accel_pico, accel_media, gyro_pico, etc.
        self.timestamp = timestamp or datetime.now()


class SessionData:
    """Holds all data for the current session."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.strokes = []
        self.start_time = datetime.now()
        self.counts = {c: 0 for c in ALL_CLASSES}

    def add_stroke(self, event: StrokeEvent):
        self.strokes.append(event)
        self.counts[event.stroke_type] += 1

    def delete_last(self):
        if self.strokes:
            last = self.strokes.pop()
            self.counts[last.stroke_type] -= 1
            return last
        return None

    @property
    def total_strokes(self):
        return len(self.strokes)

    @property
    def total_real_strokes(self):
        return sum(self.counts[s] for s in STROKE_TYPES)

    @property
    def elapsed(self):
        return datetime.now() - self.start_time

    @property
    def strokes_per_minute(self):
        elapsed_min = self.elapsed.total_seconds() / 60
        if elapsed_min < 0.1:
            return 0.0
        return self.total_real_strokes / elapsed_min

    @property
    def avg_confidence(self):
        real = [s.confidence for s in self.strokes if s.stroke_type != 'descanso']
        return np.mean(real) if real else 0.0

    @property
    def drive_reves_ratio(self):
        """Returns (drive%, reves%) tuple."""
        d = self.counts['drive']
        r = self.counts['reves']
        total = d + r
        if total == 0:
            return (50.0, 50.0)
        return (d / total * 100, r / total * 100)

    @property
    def smash_percentage(self):
        total = self.total_real_strokes
        if total == 0:
            return 0.0
        return self.counts['smash'] / total * 100

    @property
    def last_stroke(self):
        if self.strokes:
            return self.strokes[-1]
        return None

    def get_recent(self, n=FEED_MAX):
        return list(reversed(self.strokes[-n:]))

    def get_timeline_data(self, n=TIMELINE_MAX):
        return self.strokes[-n:]

    def export_csv(self, filepath):
        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            header = ['timestamp', 'stroke_type', 'confidence'] + \
                     [f'conf_{c}' for c in ALL_CLASSES] + \
                     ['accel_pico', 'accel_media', 'gyro_pico', 'gyro_media',
                      'accel_max_x', 'accel_max_y', 'accel_max_z']
            writer.writerow(header)
            for s in self.strokes:
                row = [
                    s.timestamp.strftime('%Y-%m-%d %H:%M:%S.%f'),
                    s.stroke_type,
                    f'{s.confidence:.3f}'
                ] + [f'{s.all_confidences.get(c, 0):.3f}' for c in ALL_CLASSES] + [
                    f'{s.imu_stats.get("accel_pico", 0):.2f}',
                    f'{s.imu_stats.get("accel_media", 0):.2f}',
                    f'{s.imu_stats.get("gyro_pico", 0):.1f}',
                    f'{s.imu_stats.get("gyro_media", 0):.1f}',
                    f'{s.imu_stats.get("accel_max_x", 0):.2f}',
                    f'{s.imu_stats.get("accel_max_y", 0):.2f}',
                    f'{s.imu_stats.get("accel_max_z", 0):.2f}',
                ]
                writer.writerow(row)
        return filepath


# ============================================================
# SERIAL READER
# ============================================================
class SerialReader:
    """Reads and parses Arduino classifier output including IMU stats."""

    def __init__(self, port, baud_rate, callback):
        self.port = port
        self.baud_rate = baud_rate
        self.callback = callback
        self.running = False
        self.thread = None
        self.ser = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._read_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.ser and self.ser.is_open:
            self.ser.close()

    def _read_loop(self):
        try:
            self.ser = serial.Serial(self.port, self.baud_rate, timeout=1)
            time.sleep(2)
        except serial.SerialException as e:
            self.callback(None, error=str(e))
            return

        confidences = {}
        imu_stats = {}
        parsing_result = False
        parsing_imu = False

        while self.running:
            try:
                raw = self.ser.readline()
                if not raw:
                    continue
                line = raw.decode('utf-8', errors='ignore').strip()
                if not line:
                    continue

                # Start of classification block
                if '--- Resultado ---' in line:
                    confidences = {}
                    imu_stats = {}
                    parsing_result = True
                    parsing_imu = False
                    continue

                # Start of IMU stats block
                if '--- IMU ---' in line:
                    parsing_result = False
                    parsing_imu = True
                    continue

                # Parse confidence lines
                if parsing_result:
                    match = re.match(r'\s*(\w+):\s*([\d.]+)%', line)
                    if match:
                        cls_name = match.group(1).lower()
                        conf_value = float(match.group(2)) / 100.0
                        confidences[cls_name] = conf_value
                    continue

                # Parse IMU stat lines
                if parsing_imu:
                    match = re.match(r'\s*([\w_]+):\s*([\d.]+)', line)
                    if match:
                        key = match.group(1)
                        val = float(match.group(2))
                        imu_stats[key] = val
                        continue
                    # If line doesn't match stat format, IMU block is done
                    parsing_imu = False
                    # Fall through to check if it's a detection line

                # Detection line
                if '>>> GOLPE DETECTADO:' in line:
                    parsing_result = False
                    parsing_imu = False
                    match = re.search(r'GOLPE DETECTADO:\s*(\w+)\s*\(([\d.]+)%\)', line)
                    if match and confidences:
                        stroke = match.group(1).lower()
                        confidence = float(match.group(2)) / 100.0
                        event = StrokeEvent(stroke, confidence,
                                            confidences.copy(), imu_stats.copy())
                        self.callback(event)
                    confidences = {}
                    imu_stats = {}
                    continue

                if '>>> Golpe no reconocido' in line:
                    parsing_result = False
                    parsing_imu = False
                    if confidences:
                        max_conf = max(confidences.values()) if confidences else 0
                        event = StrokeEvent('descanso', max_conf,
                                            confidences.copy(), imu_stats.copy())
                        self.callback(event)
                    confidences = {}
                    imu_stats = {}
                    continue

            except serial.SerialException:
                if self.running:
                    self.callback(None, error="Conexión serial perdida")
                break
            except Exception:
                continue


# ============================================================
# DASHBOARD GUI
# ============================================================
class PadelDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("Pádel Dashboard - Clasificador de Golpes")
        self.root.geometry("1400x850")
        self.root.minsize(1200, 750)
        self.root.configure(bg=BG_COLOR)

        self.session = SessionData()
        self.reader = None
        self.connected = False
        self.show_noise = tk.BooleanVar(value=True)
        self.paused = False
        self._last_stroke_count = 0

        self._build_ui()
        self._update_loop()

    # ---- UI CONSTRUCTION ----

    def _build_ui(self):
        self._build_topbar()

        main = tk.Frame(self.root, bg=BG_COLOR)
        main.pack(fill='both', expand=True, padx=10, pady=(0, 10))

        # Left column
        left = tk.Frame(main, bg=BG_COLOR, width=320)
        left.pack(side='left', fill='y', padx=(0, 8))
        left.pack_propagate(False)
        self._build_left_panel(left)

        # Right column
        right = tk.Frame(main, bg=BG_COLOR)
        right.pack(side='left', fill='both', expand=True)
        self._build_right_panel(right)

    def _build_topbar(self):
        bar = tk.Frame(self.root, bg=BG_CARD, height=56)
        bar.pack(fill='x', padx=10, pady=10)
        bar.pack_propagate(False)

        tk.Label(bar, text="PÁDEL DASHBOARD", font=FONT_TITLE,
                 bg=BG_CARD, fg=ACCENT_COLOR).pack(side='left', padx=15)

        controls = tk.Frame(bar, bg=BG_CARD)
        controls.pack(side='right', padx=10)

        self.btn_connect = tk.Button(
            controls, text="Conectar", command=self._toggle_connection,
            bg=ACCENT_COLOR, fg='white', font=FONT_LABEL,
            relief='flat', padx=12, pady=4, cursor='hand2')
        self.btn_connect.pack(side='left', padx=4)

        self.btn_pause = tk.Button(
            controls, text="Pausar", command=self._toggle_pause,
            bg=BG_CARD_ALT, fg=TEXT_COLOR, font=FONT_LABEL,
            relief='flat', padx=8, pady=4, cursor='hand2', state='disabled')
        self.btn_pause.pack(side='left', padx=4)

        self.btn_undo = tk.Button(
            controls, text="Deshacer", command=self._undo_last,
            bg=BG_CARD_ALT, fg=TEXT_COLOR, font=FONT_LABEL,
            relief='flat', padx=8, pady=4, cursor='hand2')
        self.btn_undo.pack(side='left', padx=4)

        self.btn_export = tk.Button(
            controls, text="Exportar CSV", command=self._export_session,
            bg=BG_CARD_ALT, fg=TEXT_COLOR, font=FONT_LABEL,
            relief='flat', padx=8, pady=4, cursor='hand2')
        self.btn_export.pack(side='left', padx=4)

        self.btn_reset = tk.Button(
            controls, text="Reset", command=self._reset_session,
            bg='#333', fg=TEXT_DIM, font=FONT_LABEL,
            relief='flat', padx=8, pady=4, cursor='hand2')
        self.btn_reset.pack(side='left', padx=4)

        tk.Checkbutton(
            controls, text="Mostrar descanso", variable=self.show_noise,
            bg=BG_CARD, fg=TEXT_DIM, selectcolor=BG_CARD_ALT,
            font=FONT_SMALL, activebackground=BG_CARD,
            activeforeground=TEXT_COLOR, command=self._force_redraw
        ).pack(side='left', padx=8)

        self.lbl_status = tk.Label(
            bar, text="● Desconectado", font=FONT_LABEL,
            bg=BG_CARD, fg='#F44336')
        self.lbl_status.pack(side='right', padx=15)

    # ---- LEFT PANEL ----

    def _build_left_panel(self, parent):
        # Session stats
        tk.Label(parent, text="ESTADÍSTICAS", font=FONT_SUBTITLE,
                 bg=BG_COLOR, fg=TEXT_ACCENT).pack(anchor='w', pady=(0, 4))

        card = tk.Frame(parent, bg=BG_CARD, padx=12, pady=8)
        card.pack(fill='x', pady=(0, 6))

        self.lbl_time = tk.Label(card, text="Sesión: 00:00:00", font=FONT_SMALL,
                                  bg=BG_CARD, fg=TEXT_DIM)
        self.lbl_time.pack(anchor='w')

        row = tk.Frame(card, bg=BG_CARD)
        row.pack(fill='x', pady=4)

        for attr, label_text in [('lbl_total', 'golpes'),
                                  ('lbl_spm', 'golpes/min'),
                                  ('lbl_conf', 'confianza')]:
            col = tk.Frame(row, bg=BG_CARD)
            col.pack(side='left', expand=True)
            lbl_val = tk.Label(col, text="0", font=FONT_VALUE, bg=BG_CARD, fg=TEXT_ACCENT)
            lbl_val.pack()
            tk.Label(col, text=label_text, font=FONT_SMALL, bg=BG_CARD, fg=TEXT_DIM).pack()
            setattr(self, attr, lbl_val)

        # KPI card: Drive/Revés ratio + Smash %
        kpi_card = tk.Frame(parent, bg=BG_CARD, padx=12, pady=8)
        kpi_card.pack(fill='x', pady=(0, 6))

        # Drive/Revés ratio
        tk.Label(kpi_card, text="RATIO DRIVE / REVÉS", font=FONT_SMALL,
                 bg=BG_CARD, fg=TEXT_DIM).pack(anchor='w')

        ratio_row = tk.Frame(kpi_card, bg=BG_CARD)
        ratio_row.pack(fill='x', pady=(4, 2))

        self.lbl_ratio_text = tk.Label(ratio_row, text="50 / 50",
                                        font=('Helvetica', 18, 'bold'),
                                        bg=BG_CARD, fg=TEXT_ACCENT)
        self.lbl_ratio_text.pack()

        # Ratio visual bar
        ratio_bar_frame = tk.Frame(kpi_card, bg='#2a2a3e', height=14)
        ratio_bar_frame.pack(fill='x', pady=(0, 6))
        ratio_bar_frame.pack_propagate(False)

        self.ratio_bar_drive = tk.Frame(ratio_bar_frame, bg=COLORS['drive'], height=14)
        self.ratio_bar_drive.place(x=0, y=0, relheight=1.0, relwidth=0.5)
        self.ratio_bar_reves = tk.Frame(ratio_bar_frame, bg=COLORS['reves'], height=14)
        self.ratio_bar_reves.place(relx=0.5, y=0, relheight=1.0, relwidth=0.5)

        ratio_labels = tk.Frame(kpi_card, bg=BG_CARD)
        ratio_labels.pack(fill='x')
        tk.Label(ratio_labels, text="DRIVE", font=FONT_SMALL,
                 bg=BG_CARD, fg=COLORS['drive']).pack(side='left')
        tk.Label(ratio_labels, text="REVÉS", font=FONT_SMALL,
                 bg=BG_CARD, fg=COLORS['reves']).pack(side='right')

        # Separator
        tk.Frame(kpi_card, bg=TEXT_DIM, height=1).pack(fill='x', pady=8)

        # Smash percentage
        smash_row = tk.Frame(kpi_card, bg=BG_CARD)
        smash_row.pack(fill='x')

        tk.Label(smash_row, text="% SMASH", font=FONT_SMALL,
                 bg=BG_CARD, fg=TEXT_DIM).pack(side='left')
        self.lbl_smash_pct = tk.Label(smash_row, text="0%",
                                       font=('Helvetica', 18, 'bold'),
                                       bg=BG_CARD, fg=COLORS['smash'])
        self.lbl_smash_pct.pack(side='right')

        # Count bars
        counts_card = tk.Frame(parent, bg=BG_CARD, padx=12, pady=8)
        counts_card.pack(fill='x', pady=(0, 6))

        tk.Label(counts_card, text="CONTEO POR GOLPE", font=FONT_SMALL,
                 bg=BG_CARD, fg=TEXT_DIM).pack(anchor='w', pady=(0, 6))

        self.count_bars = {}
        for stroke in ALL_CLASSES:
            row = tk.Frame(counts_card, bg=BG_CARD)
            row.pack(fill='x', pady=2)

            tk.Label(row, text=stroke.upper(), font=FONT_SMALL,
                     bg=BG_CARD, fg=COLORS[stroke], width=9, anchor='w').pack(side='left')

            bar_bg = tk.Frame(row, bg='#2a2a3e', height=16)
            bar_bg.pack(side='left', fill='x', expand=True, padx=(4, 4))
            bar_bg.pack_propagate(False)

            bar_fill = tk.Frame(bar_bg, bg=COLORS[stroke], height=16, width=0)
            bar_fill.place(x=0, y=0, relheight=1.0, width=0)

            lbl_count = tk.Label(row, text="0", font=FONT_SMALL,
                                  bg=BG_CARD, fg=TEXT_COLOR, width=4, anchor='e')
            lbl_count.pack(side='right')

            self.count_bars[stroke] = {'bar_bg': bar_bg, 'bar_fill': bar_fill, 'label': lbl_count}

        # Feed
        tk.Label(parent, text="ÚLTIMOS GOLPES", font=FONT_SUBTITLE,
                 bg=BG_COLOR, fg=TEXT_ACCENT).pack(anchor='w', pady=(8, 4))

        feed_frame = tk.Frame(parent, bg=BG_CARD, padx=8, pady=8)
        feed_frame.pack(fill='both', expand=True)

        self.feed_text = tk.Text(
            feed_frame, bg=BG_CARD, fg=TEXT_COLOR, font=FONT_FEED,
            relief='flat', highlightthickness=0, state='disabled',
            wrap='none', cursor='arrow')
        self.feed_text.pack(fill='both', expand=True)

        for stroke, color in COLORS.items():
            self.feed_text.tag_configure(stroke, foreground=color)
        self.feed_text.tag_configure('time', foreground=TEXT_DIM)
        self.feed_text.tag_configure('conf', foreground=TEXT_DIM)

    # ---- RIGHT PANEL ----

    def _build_right_panel(self, parent):
        # Top row: Last stroke card (big)
        self._build_last_stroke_card(parent)

        # Middle row: Pie + Bar charts
        mid = tk.Frame(parent, bg=BG_COLOR)
        mid.pack(fill='both', expand=True, pady=(6, 3))

        pie_frame = tk.Frame(mid, bg=BG_CARD)
        pie_frame.pack(side='left', fill='both', expand=True, padx=(0, 3))
        self.fig_pie = Figure(figsize=(4, 3), facecolor=BG_CARD)
        self.ax_pie = self.fig_pie.add_subplot(111)
        self.canvas_pie = FigureCanvasTkAgg(self.fig_pie, master=pie_frame)
        self.canvas_pie.get_tk_widget().pack(fill='both', expand=True)

        bar_frame = tk.Frame(mid, bg=BG_CARD)
        bar_frame.pack(side='left', fill='both', expand=True, padx=(3, 0))
        self.fig_bar = Figure(figsize=(4, 3), facecolor=BG_CARD)
        self.ax_bar = self.fig_bar.add_subplot(111)
        self.canvas_bar = FigureCanvasTkAgg(self.fig_bar, master=bar_frame)
        self.canvas_bar.get_tk_widget().pack(fill='both', expand=True)

        # Bottom: Timeline
        tl_frame = tk.Frame(parent, bg=BG_CARD)
        tl_frame.pack(fill='both', expand=True, pady=(3, 0))
        self.fig_timeline = Figure(figsize=(8, 2.2), facecolor=BG_CARD)
        self.ax_timeline = self.fig_timeline.add_subplot(111)
        self.canvas_timeline = FigureCanvasTkAgg(self.fig_timeline, master=tl_frame)
        self.canvas_timeline.get_tk_widget().pack(fill='both', expand=True)

    def _build_last_stroke_card(self, parent):
        """Big card showing last stroke + IMU summary."""
        card = tk.Frame(parent, bg=BG_CARD, padx=15, pady=10)
        card.pack(fill='x', pady=(0, 3))

        # Left side: stroke name + confidence
        left = tk.Frame(card, bg=BG_CARD)
        left.pack(side='left', fill='y', padx=(0, 20))

        tk.Label(left, text="ÚLTIMO GOLPE", font=FONT_SMALL,
                 bg=BG_CARD, fg=TEXT_DIM).pack(anchor='w')

        self.lbl_last_stroke = tk.Label(
            left, text="---", font=FONT_BIG_STROKE,
            bg=BG_CARD, fg=TEXT_DIM)
        self.lbl_last_stroke.pack(anchor='w')

        self.lbl_last_conf = tk.Label(
            left, text="", font=FONT_LABEL,
            bg=BG_CARD, fg=TEXT_DIM)
        self.lbl_last_conf.pack(anchor='w')

        # Separator
        tk.Frame(card, bg=TEXT_DIM, width=1).pack(side='left', fill='y', padx=10, pady=5)

        # Right side: IMU stats grid
        imu_frame = tk.Frame(card, bg=BG_CARD)
        imu_frame.pack(side='left', fill='both', expand=True)

        tk.Label(imu_frame, text="RESUMEN IMU", font=FONT_SMALL,
                 bg=BG_CARD, fg=TEXT_DIM).pack(anchor='w')

        stats_grid = tk.Frame(imu_frame, bg=BG_CARD)
        stats_grid.pack(fill='x', pady=(4, 0))

        self.imu_labels = {}
        imu_items = [
            ('accel_pico',  'Acel. Pico',  'G'),
            ('accel_media', 'Acel. Media', 'G'),
            ('gyro_pico',   'Gyro. Pico',  '°/s'),
            ('gyro_media',  'Gyro. Media', '°/s'),
            ('accel_max_x', 'Max |X|',     'G'),
            ('accel_max_y', 'Max |Y|',     'G'),
            ('accel_max_z', 'Max |Z|',     'G'),
        ]

        for i, (key, label, unit) in enumerate(imu_items):
            col = tk.Frame(stats_grid, bg=BG_CARD)
            col.grid(row=0 if i < 4 else 1, column=i % 4, padx=8, pady=2, sticky='w')

            val_lbl = tk.Label(col, text="--", font=FONT_IMU_VAL,
                                bg=BG_CARD, fg=TEXT_ACCENT)
            val_lbl.pack(anchor='w')

            tk.Label(col, text=f"{label} ({unit})", font=FONT_IMU_LBL,
                     bg=BG_CARD, fg=TEXT_DIM).pack(anchor='w')

            self.imu_labels[key] = val_lbl

    # ---- CHART DRAWING ----

    def _draw_pie(self):
        self.ax_pie.clear()
        self.ax_pie.set_facecolor(BG_CARD)

        classes = STROKE_TYPES
        sizes = [self.session.counts[c] for c in classes]
        colors = [COLORS[c] for c in classes]
        labels = [c.upper() for c in classes]

        total = sum(sizes)
        if total == 0:
            self.ax_pie.text(0.5, 0.5, 'Sin datos', ha='center', va='center',
                             fontsize=14, color=TEXT_DIM, transform=self.ax_pie.transAxes)
            self.ax_pie.set_title('Distribución de Golpes', color=TEXT_ACCENT,
                                   fontsize=12, fontweight='bold', pad=10)
            self.canvas_pie.draw_idle()
            return

        filtered = [(s, c, l) for s, c, l in zip(sizes, colors, labels) if s > 0]
        if not filtered:
            self.canvas_pie.draw_idle()
            return

        sizes_f, colors_f, labels_f = zip(*filtered)

        wedges, texts, autotexts = self.ax_pie.pie(
            sizes_f, labels=labels_f, colors=colors_f, autopct='%1.0f%%',
            startangle=90, textprops={'color': TEXT_COLOR, 'fontsize': 9},
            pctdistance=0.75, wedgeprops={'linewidth': 2, 'edgecolor': BG_CARD})

        for t in autotexts:
            t.set_color('white')
            t.set_fontweight('bold')
            t.set_fontsize(10)

        self.ax_pie.set_title('Distribución de Golpes', color=TEXT_ACCENT,
                               fontsize=12, fontweight='bold', pad=10)
        self.canvas_pie.draw_idle()

    def _draw_bar(self):
        self.ax_bar.clear()
        self.ax_bar.set_facecolor(BG_CARD)

        classes = STROKE_TYPES
        counts = [self.session.counts[c] for c in classes]
        colors = [COLORS[c] for c in classes]
        labels = [c.upper() for c in classes]

        x = np.arange(len(classes))
        bars = self.ax_bar.bar(x, counts, color=colors, width=0.6,
                                edgecolor=BG_CARD, linewidth=1)

        for bar, count in zip(bars, counts):
            if count > 0:
                self.ax_bar.text(bar.get_x() + bar.get_width() / 2,
                                  bar.get_height() + 0.3, str(count),
                                  ha='center', va='bottom',
                                  color=TEXT_ACCENT, fontsize=11, fontweight='bold')

        self.ax_bar.set_xticks(x)
        self.ax_bar.set_xticklabels(labels, color=TEXT_COLOR, fontsize=9)
        self.ax_bar.set_title('Conteo de Golpes', color=TEXT_ACCENT,
                               fontsize=12, fontweight='bold', pad=10)
        self.ax_bar.set_ylabel('Cantidad', color=TEXT_DIM, fontsize=9)
        self.ax_bar.tick_params(axis='y', colors=TEXT_DIM)
        self.ax_bar.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))
        self.ax_bar.spines['top'].set_visible(False)
        self.ax_bar.spines['right'].set_visible(False)
        self.ax_bar.spines['left'].set_color(TEXT_DIM)
        self.ax_bar.spines['bottom'].set_color(TEXT_DIM)
        self.canvas_bar.draw_idle()

    def _draw_timeline(self):
        self.ax_timeline.clear()
        self.ax_timeline.set_facecolor(BG_CARD)

        data = self.session.get_timeline_data(TIMELINE_MAX)
        show_noise = self.show_noise.get()
        if not show_noise:
            data = [s for s in data if s.stroke_type != 'descanso']

        if not data:
            self.ax_timeline.text(0.5, 0.5, 'Esperando golpes...',
                                   ha='center', va='center', fontsize=14,
                                   color=TEXT_DIM, transform=self.ax_timeline.transAxes)
            self.ax_timeline.set_title('Línea Temporal', color=TEXT_ACCENT,
                                        fontsize=12, fontweight='bold', pad=10)
            self._style_timeline_axes()
            self.canvas_timeline.draw_idle()
            return

        x = list(range(len(data)))
        y = [s.confidence for s in data]
        c = [COLORS[s.stroke_type] for s in data]

        self.ax_timeline.scatter(x, y, c=c, s=60, zorder=3,
                                  edgecolors='white', linewidths=0.5, alpha=0.9)
        if len(x) > 1:
            self.ax_timeline.plot(x, y, color=TEXT_DIM, alpha=0.2, linewidth=1, zorder=1)

        self.ax_timeline.set_ylim(-0.05, 1.05)
        self.ax_timeline.set_title('Línea Temporal - Confianza por Golpe',
                                    color=TEXT_ACCENT, fontsize=12,
                                    fontweight='bold', pad=10)
        self.ax_timeline.set_ylabel('Confianza', color=TEXT_DIM, fontsize=9)
        self.ax_timeline.set_xlabel('Golpe #', color=TEXT_DIM, fontsize=9)

        from matplotlib.lines import Line2D
        legend_classes = ALL_CLASSES if show_noise else STROKE_TYPES
        legend_elements = [
            Line2D([0], [0], marker='o', color='w', markerfacecolor=COLORS[c_name],
                   markersize=8, label=c_name.upper(), linestyle='None')
            for c_name in legend_classes if self.session.counts[c_name] > 0
        ]
        if legend_elements:
            self.ax_timeline.legend(
                handles=legend_elements, loc='upper left', fontsize=8,
                facecolor=BG_CARD_ALT, edgecolor=TEXT_DIM, labelcolor=TEXT_COLOR,
                ncol=len(legend_elements))

        self._style_timeline_axes()
        self.canvas_timeline.draw_idle()

    def _style_timeline_axes(self):
        self.ax_timeline.tick_params(axis='both', colors=TEXT_DIM)
        for spine in ['top', 'right']:
            self.ax_timeline.spines[spine].set_visible(False)
        for spine in ['left', 'bottom']:
            self.ax_timeline.spines[spine].set_color(TEXT_DIM)

    # ---- UPDATE METHODS ----

    def _update_stats(self):
        elapsed = self.session.elapsed
        h, rem = divmod(int(elapsed.total_seconds()), 3600)
        m, s = divmod(rem, 60)
        self.lbl_time.config(text=f"Sesión: {h:02d}:{m:02d}:{s:02d}")

        self.lbl_total.config(text=str(self.session.total_real_strokes))
        self.lbl_spm.config(text=f"{self.session.strokes_per_minute:.1f}")
        self.lbl_conf.config(text=f"{self.session.avg_confidence * 100:.0f}%")

        # Drive/Revés ratio
        dr, rv = self.session.drive_reves_ratio
        self.lbl_ratio_text.config(text=f"{dr:.0f} / {rv:.0f}")
        self.ratio_bar_drive.place_configure(relwidth=dr / 100)
        self.ratio_bar_reves.place_configure(relx=dr / 100, relwidth=rv / 100)

        # Smash %
        self.lbl_smash_pct.config(text=f"{self.session.smash_percentage:.0f}%")

        # Count bars
        max_count = max(max(self.session.counts.values()), 1)
        for stroke in ALL_CLASSES:
            count = self.session.counts[stroke]
            bar_info = self.count_bars[stroke]
            bar_info['label'].config(text=str(count))
            bar_bg_width = bar_info['bar_bg'].winfo_width()
            if bar_bg_width > 1:
                fill_width = int((count / max_count) * bar_bg_width)
                bar_info['bar_fill'].place_configure(width=max(fill_width, 0))

    def _update_last_stroke(self):
        """Update the big last stroke display."""
        last = self.session.last_stroke
        if not last:
            return

        color = COLORS.get(last.stroke_type, TEXT_DIM)
        self.lbl_last_stroke.config(text=last.stroke_type.upper(), fg=color)
        self.lbl_last_conf.config(
            text=f"Confianza: {last.confidence * 100:.0f}%  •  {last.timestamp.strftime('%H:%M:%S')}",
            fg=TEXT_COLOR)

        # IMU stats
        stats = last.imu_stats
        formats = {
            'accel_pico': '{:.2f}', 'accel_media': '{:.2f}',
            'gyro_pico': '{:.0f}', 'gyro_media': '{:.0f}',
            'accel_max_x': '{:.2f}', 'accel_max_y': '{:.2f}', 'accel_max_z': '{:.2f}',
        }
        for key, lbl in self.imu_labels.items():
            val = stats.get(key)
            if val is not None:
                fmt = formats.get(key, '{:.2f}')
                lbl.config(text=fmt.format(val), fg=color)
            else:
                lbl.config(text="--", fg=TEXT_DIM)
        # Optional: simple textual interpretation
        a_peak = stats.get('accel_pico', None)
        a_mean = stats.get('accel_media', None)
        if a_peak is not None and a_mean is not None:
    # ejemplo simple (ajusta umbrales a tus datos reales)
            if a_peak > 3.0:
                desc = "Aceleración alta (golpe explosivo)"
            elif a_peak > 2.0:
                desc = "Aceleración media"
            else:
                desc = "Aceleración baja (golpe suave)"
            self.lbl_last_conf.config(
                text=f"Confianza: {last.confidence * 100:.0f}%  •  {last.timestamp.strftime('%H:%M:%S')}  •  {desc}",
                fg=TEXT_COLOR
            )        
    def _update_feed(self):
        self.feed_text.config(state='normal')
        self.feed_text.delete('1.0', 'end')

        recent = self.session.get_recent(FEED_MAX)
        show_noise = self.show_noise.get()
        if not show_noise:
            recent = [s for s in recent if s.stroke_type != 'descanso']

        for stroke in recent:
            time_str = stroke.timestamp.strftime('%H:%M:%S')
            conf_str = f"{stroke.confidence * 100:.0f}%"
            self.feed_text.insert('end', f" {time_str} ", 'time')
            self.feed_text.insert('end', f" {stroke.stroke_type.upper():<9s}", stroke.stroke_type)
            self.feed_text.insert('end', f" {conf_str}\n", 'conf')

        if not recent:
            self.feed_text.insert('end', " Esperando golpes...", 'time')

        self.feed_text.config(state='disabled')

    def _force_redraw(self):
        self._last_stroke_count = -1

    def _update_loop(self):
        current_count = self.session.total_strokes
        self._update_stats()

        if current_count != self._last_stroke_count:
            self._update_last_stroke()
            self._update_feed()
            self._draw_pie()
            self._draw_bar()
            self._draw_timeline()
            self._last_stroke_count = current_count

        self.root.after(REFRESH_INTERVAL, self._update_loop)

    # ---- CALLBACKS AND ACTIONS ----

    def _on_stroke_received(self, event, error=None):
        if error:
            self.root.after(0, lambda: self._show_error(error))
            return
        if event and not self.paused:
            self.root.after(0, lambda e=event: self.session.add_stroke(e))

    def _show_error(self, msg):
        self.lbl_status.config(text=f"● Error: {msg}", fg='#F44336')

    def _toggle_connection(self):
        if self.connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        port = self._find_port()
        if not port:
            return
        self.reader = SerialReader(port, BAUD_RATE, self._on_stroke_received)
        self.reader.start()
        self.connected = True
        self.btn_connect.config(text="Desconectar", bg='#666')
        self.btn_pause.config(state='normal')
        self.lbl_status.config(text=f"● Conectado ({port})", fg='#4CAF50')

    def _disconnect(self):
        if self.reader:
            self.reader.stop()
        self.connected = False
        self.btn_connect.config(text="Conectar", bg=ACCENT_COLOR)
        self.btn_pause.config(state='disabled')
        self.lbl_status.config(text="● Desconectado", fg='#F44336')

    def _find_port(self):
        ports = serial.tools.list_ports.comports()
        if not ports:
            messagebox.showerror("Error", "No se encontraron puertos serie.")
            return None

        for port in ports:
            desc = port.description.lower()
            if any(kw in desc for kw in ['arduino', 'nano', 'ble', 'usbmodem', 'acm']):
                return port.device

        dialog = tk.Toplevel(self.root)
        dialog.title("Seleccionar Puerto")
        dialog.geometry("400x250")
        dialog.configure(bg=BG_COLOR)
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Selecciona el puerto del Arduino:",
                 font=FONT_LABEL, bg=BG_COLOR, fg=TEXT_COLOR).pack(pady=10)

        listbox = tk.Listbox(dialog, font=FONT_FEED, bg=BG_CARD, fg=TEXT_COLOR,
                              selectbackground=ACCENT_COLOR, height=8)
        listbox.pack(fill='both', expand=True, padx=20)
        for port in ports:
            listbox.insert('end', f"{port.device} - {port.description}")

        result = [None]

        def on_select():
            sel = listbox.curselection()
            if sel:
                result[0] = ports[sel[0]].device
            dialog.destroy()

        tk.Button(dialog, text="Conectar", command=on_select,
                  bg=ACCENT_COLOR, fg='white', font=FONT_LABEL,
                  relief='flat', padx=20).pack(pady=10)
        dialog.wait_window()
        return result[0]

    def _toggle_pause(self):
        self.paused = not self.paused
        if self.paused:
            self.btn_pause.config(text="Reanudar", bg=ACCENT_COLOR)
            self.lbl_status.config(text="● Pausado", fg='#FF9800')
        else:
            self.btn_pause.config(text="Pausar", bg=BG_CARD_ALT)
            port_info = self.reader.port if self.reader else ""
            self.lbl_status.config(text=f"● Conectado ({port_info})", fg='#4CAF50')

    def _undo_last(self):
        removed = self.session.delete_last()
        if removed:
            self._force_redraw()
        else:
            messagebox.showinfo("Info", "No hay golpes que deshacer.")

    def _reset_session(self):
        if self.session.total_strokes > 0:
            confirm = messagebox.askyesno(
                "Reiniciar Sesión",
                f"¿Seguro? Se perderán {self.session.total_strokes} golpes.")
            if not confirm:
                return
        self.session.reset()
        # Reset last stroke display
        self.lbl_last_stroke.config(text="---", fg=TEXT_DIM)
        self.lbl_last_conf.config(text="", fg=TEXT_DIM)
        for lbl in self.imu_labels.values():
            lbl.config(text="--", fg=TEXT_DIM)
        self._force_redraw()

    def _export_session(self):
        if self.session.total_strokes == 0:
            messagebox.showinfo("Info", "No hay datos que exportar.")
            return
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"sesion_padel_{timestamp}.csv"
        try:
            filepath = self.session.export_csv(filename)
            messagebox.showinfo("Exportado",
                                f"Sesión exportada a:\n{os.path.abspath(filepath)}")
        except Exception as e:
            messagebox.showerror("Error", f"Error al exportar:\n{e}")

    def on_close(self):
        if self.reader:
            self.reader.stop()
        self.root.destroy()


# ============================================================
# MAIN
# ============================================================
def main():
    root = tk.Tk()
    app = PadelDashboard(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == '__main__':
    main()
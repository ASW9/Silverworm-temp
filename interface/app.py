#!/usr/bin/env python3
"""
Thread Wrapping Machine Control System - Enhanced Modern Interface
Advanced version with additional animations and modern UI features.
"""

import os
import sys
import math
import random
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple
from dataclasses import dataclass

import numpy as np

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QFrame, QScrollArea,
    QGraphicsDropShadowEffect, QSizePolicy, QSpacerItem,
    QProgressBar, QStackedWidget, QLineEdit,
    QFileDialog, QMenuBar, QMenu
)
from PyQt6.QtGui import QDoubleValidator
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup,
    pyqtSignal, pyqtProperty, QPoint, QSize, QRectF, QSequentialAnimationGroup,
    QAbstractAnimation, QStandardPaths
)
from PyQt6.QtGui import (
    QFont, QFontDatabase, QPainter, QColor, QPen, QBrush,
    QLinearGradient, QPainterPath, QPixmap, QKeyEvent, QRadialGradient,
)  # QDoubleValidator imported above with QLineEdit

# Camera and processing modules
from camera import CameraDetector, CameraWorker, CameraConfig
from camera.rolling_buffer import RollingBuffer
from processing import PitchDetectionPipeline
from ui.camera_widget import EnhancedCameraView
from ui.manual_mode_dialog import ManualModeBanner
from ui.manual_overlay_panel import ManualOverlayPanel
from ui.startup_dialog import StartupConfigDialog

# Controller and comms
from controller import SetpointController, OperatingMode, Setpoints, SPEED_A_MIN, SPEED_A_MAX, SPEED_B_MIN, SPEED_B_MAX
from comms import MockTransport, Transport

from config import AppConfig, load_config, save_config, calculate_wrap_angle_deg
from storage import StorageManager

# ============================================================================
# COLOR THEME
# ============================================================================

class Theme:
    """Modern industrial dark theme colors"""
    
    # Base colors
    BG_DARKEST = "#05080c"
    BG_PRIMARY = "#0a0e14"
    BG_SECONDARY = "#0f1419"
    BG_CARD = "#151b23"
    BG_ELEVATED = "#1a222d"
    BG_HOVER = "#1f2937"
    
    # Accent colors
    ACCENT_PRIMARY = "#00d4aa"
    ACCENT_SECONDARY = "#00b894"
    ACCENT_GLOW = "#00ffcc"
    CYAN = "#00cec9"
    BLUE = "#0984e3"
    PURPLE = "#6c5ce7"
    
    # Text colors
    TEXT_PRIMARY = "#e6e6e6"
    TEXT_SECONDARY = "#8b949e"
    TEXT_MUTED = "#5c6470"
    TEXT_DISABLED = "#3a4250"
    
    # Status colors
    SUCCESS = "#00d68f"
    SUCCESS_GLOW = "#00ff9f"
    WARNING = "#ffaa00"
    WARNING_GLOW = "#ffcc44"
    ERROR = "#ff6b6b"
    ERROR_GLOW = "#ff8888"
    INFO = "#339af0"
    INFO_GLOW = "#66bbff"
    
    # Borders
    BORDER = "#2d3748"
    BORDER_LIGHT = "#3d4a5c"
    BORDER_FOCUS = "#00d4aa"


# ============================================================================
# ANIMATED WIDGETS
# ============================================================================

class AnimatedButton(QPushButton):
    """Button with hover animations and glow effects"""
    
    def __init__(self, text: str, color: str, glow_color: str, parent=None):
        super().__init__(text, parent)
        self.base_color = color
        self.glow_color = glow_color
        self._glow_intensity = 0
        
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        self.setMinimumHeight(44)
        
        self._update_style()
        
        # Glow animation
        self._glow_anim = QPropertyAnimation(self, b"glowIntensity")
        self._glow_anim.setDuration(200)
        self._glow_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
    @pyqtProperty(int)
    def glowIntensity(self):
        return self._glow_intensity
        
    @glowIntensity.setter
    def glowIntensity(self, value):
        self._glow_intensity = value
        self._update_shadow()
        
    def _update_style(self):
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.base_color};
                color: {'#000000' if self.base_color in [Theme.SUCCESS, Theme.WARNING] else '#ffffff'};
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {self._lighten_color(self.base_color, 15)};
            }}
            QPushButton:pressed {{
                background-color: {self._darken_color(self.base_color, 10)};
            }}
            QPushButton:disabled {{
                background-color: {Theme.BG_SECONDARY};
                color: {Theme.TEXT_DISABLED};
            }}
        """)
        
    def _update_shadow(self):
        if self._glow_intensity > 0:
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(self._glow_intensity)
            shadow.setColor(QColor(self.glow_color))
            shadow.setOffset(0, 0)
            self.setGraphicsEffect(shadow)
        else:
            self.setGraphicsEffect(None)
            
    def enterEvent(self, event):
        self._glow_anim.stop()
        self._glow_anim.setStartValue(self._glow_intensity)
        self._glow_anim.setEndValue(25)
        self._glow_anim.start()
        super().enterEvent(event)
        
    def leaveEvent(self, event):
        self._glow_anim.stop()
        self._glow_anim.setStartValue(self._glow_intensity)
        self._glow_anim.setEndValue(0)
        self._glow_anim.start()
        super().leaveEvent(event)
        
    @staticmethod
    def _lighten_color(hex_color: str, percent: int) -> str:
        color = QColor(hex_color)
        h, s, l, a = color.getHsl()
        l = min(255, l + int(255 * percent / 100))
        color.setHsl(h, s, l, a)
        return color.name()
        
    @staticmethod
    def _darken_color(hex_color: str, percent: int) -> str:
        color = QColor(hex_color)
        h, s, l, a = color.getHsl()
        l = max(0, l - int(255 * percent / 100))
        color.setHsl(h, s, l, a)
        return color.name()


class GlowingCard(QFrame):
    """Card widget with subtle glow on hover"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_style()
        self._setup_shadow()
        
    def _setup_style(self):
        self.setStyleSheet(f"""
            GlowingCard {{
                background-color: {Theme.BG_CARD};
                border: 1px solid {Theme.BORDER};
                border-radius: 12px;
            }}
            GlowingCard:hover {{
                border-color: {Theme.BORDER_LIGHT};
            }}
        """)
        
    def _setup_shadow(self):
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)


class PulsingIndicator(QWidget):
    """Animated pulsing status indicator"""
    
    def __init__(self, color: str = Theme.SUCCESS, parent=None):
        super().__init__(parent)
        self.color = color
        self._pulse = 0
        self.setFixedSize(12, 12)
        
        self._anim = QPropertyAnimation(self, b"pulse")
        self._anim.setDuration(1500)
        self._anim.setStartValue(0)
        self._anim.setEndValue(100)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        
    def start(self):
        self._anim.start()
        
    def stop(self):
        self._anim.stop()
        self._pulse = 0
        self.update()
        
    @pyqtProperty(int)
    def pulse(self):
        return self._pulse
        
    @pulse.setter
    def pulse(self, value):
        self._pulse = value
        self.update()
        
    def set_color(self, color: str):
        self.color = color
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        from PyQt6.QtCore import QPointF
        center = QPointF(self.rect().center())
        
        # Outer glow (pulsing)
        if self._pulse > 0:
            glow_alpha = int(50 * (1 - self._pulse / 100))
            glow_size = 6 + int(6 * self._pulse / 100)
            
            gradient = QRadialGradient(center, glow_size)
            glow_color = QColor(self.color)
            glow_color.setAlpha(glow_alpha)
            gradient.setColorAt(0, glow_color)
            glow_color.setAlpha(0)
            gradient.setColorAt(1, glow_color)
            
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawEllipse(center, glow_size, glow_size)
        
        # Main indicator
        painter.setBrush(QColor(self.color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, 5, 5)
        
        painter.end()


class AnimatedMetricValue(QLabel):
    """Label that animates value changes"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_value = 0.0
        self._target_value = 0.0
        self._unit = ""
        self._decimals = 1
        
        self.setFont(QFont("Consolas", 18, QFont.Weight.Bold))
        
        self._anim_timer = QTimer()
        self._anim_timer.setInterval(16)  # ~60fps
        self._anim_timer.timeout.connect(self._animate_step)
        
    def set_value(self, value: float, unit: str = "", decimals: int = 1, animate: bool = True):
        self._target_value = value
        self._unit = unit
        self._decimals = decimals
        
        if animate and abs(self._target_value - self._current_value) > 0.01:
            self._anim_timer.start()
        else:
            self._current_value = value
            self._update_display()
            
    def _animate_step(self):
        diff = self._target_value - self._current_value
        step = diff * 0.15
        
        if abs(diff) < 0.01:
            self._current_value = self._target_value
            self._anim_timer.stop()
        else:
            self._current_value += step
            
        self._update_display()
        
    def _update_display(self):
        self.setText(f"{self._current_value:.{self._decimals}f} {self._unit}")


# ============================================================================
# METRICS PANEL
# ============================================================================

class MotorMetricPanel(GlowingCard):
    """Motor metrics display panel with optional manual speed input."""

    # Emitted when user edits the manual speed field (float value).
    manual_speed_changed = pyqtSignal(float)

    def __init__(self, motor_name: str, target_rpm: float,
                 speed_min: float = 0.0, speed_max: float = 3000.0,
                 parent=None):
        super().__init__(parent)
        self.target_rpm = target_rpm

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # Header with status indicator
        header_layout = QHBoxLayout()

        self.status_indicator = PulsingIndicator(Theme.TEXT_MUTED)
        header_layout.addWidget(self.status_indicator)

        header = QLabel(motor_name)
        header.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold))
        header.setStyleSheet(f"color: {Theme.ACCENT_PRIMARY};")
        header_layout.addWidget(header)
        header_layout.addStretch()

        layout.addLayout(header_layout)

        # Metrics
        metrics = QGridLayout()
        metrics.setSpacing(16)

        # Target
        self._target_label = self._add_metric(metrics, 0, "TARGET", f"{target_rpm:.0f} RPM", Theme.TEXT_SECONDARY)

        # Actual
        actual_label = QLabel("ACTUAL")
        actual_label.setFont(QFont("Segoe UI", 9))
        actual_label.setStyleSheet(f"color: {Theme.TEXT_MUTED};")
        metrics.addWidget(actual_label, 0, 1)

        self.actual_value = AnimatedMetricValue()
        self.actual_value.setText("-- RPM")
        metrics.addWidget(self.actual_value, 1, 1)

        # Error
        error_label = QLabel("ERROR")
        error_label.setFont(QFont("Segoe UI", 9))
        error_label.setStyleSheet(f"color: {Theme.TEXT_MUTED};")
        metrics.addWidget(error_label, 0, 2)

        self.error_value = QLabel("--")
        self.error_value.setFont(QFont("Consolas", 18, QFont.Weight.Bold))
        metrics.addWidget(self.error_value, 1, 2)

        layout.addLayout(metrics)

        # --- Manual speed input row (hidden by default) ---
        self.manual_row = QWidget()
        manual_layout = QHBoxLayout(self.manual_row)
        manual_layout.setContentsMargins(0, 4, 0, 0)
        manual_layout.setSpacing(8)

        manual_label = QLabel("MANUAL SPEED")
        manual_label.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        manual_label.setStyleSheet(f"color: {Theme.WARNING};")
        manual_layout.addWidget(manual_label)

        self.manual_input = QLineEdit()
        self.manual_input.setPlaceholderText(f"{speed_min:.0f} – {speed_max:.0f} RPM")
        self.manual_input.setFont(QFont("Consolas", 14, QFont.Weight.Bold))
        self.manual_input.setFixedWidth(160)
        self.manual_input.setValidator(QDoubleValidator(speed_min, speed_max, 2))
        self.manual_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {Theme.BG_SECONDARY};
                color: {Theme.WARNING};
                border: 2px solid {Theme.WARNING};
                border-radius: 6px;
                padding: 6px 10px;
            }}
            QLineEdit:focus {{
                border-color: {Theme.ACCENT_PRIMARY};
                color: {Theme.ACCENT_PRIMARY};
            }}
        """)
        # Enter key in the input also triggers SET
        self.manual_input.returnPressed.connect(self._on_set_clicked)
        manual_layout.addWidget(self.manual_input)

        rpm_suffix = QLabel("RPM")
        rpm_suffix.setFont(QFont("Segoe UI", 10))
        rpm_suffix.setStyleSheet(f"color: {Theme.TEXT_MUTED};")
        manual_layout.addWidget(rpm_suffix)

        # SET button — user must click this to commit the speed to hardware
        self.set_btn = QPushButton("SET")
        self.set_btn.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.set_btn.setFixedSize(70, 38)
        self.set_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.ACCENT_PRIMARY};
                color: #000000;
                border: none;
                border-radius: 6px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: {Theme.ACCENT_GLOW};
            }}
            QPushButton:pressed {{
                background-color: {Theme.ACCENT_SECONDARY};
            }}
        """)
        self.set_btn.clicked.connect(self._on_set_clicked)
        manual_layout.addWidget(self.set_btn)

        manual_layout.addStretch()

        layout.addWidget(self.manual_row)
        self.manual_row.hide()

    def _add_metric(self, layout, col, label_text, value_text, color):
        label = QLabel(label_text)
        label.setFont(QFont("Segoe UI", 9))
        label.setStyleSheet(f"color: {Theme.TEXT_MUTED};")
        layout.addWidget(label, 0, col)

        value = QLabel(value_text)
        value.setFont(QFont("Consolas", 18, QFont.Weight.Bold))
        value.setStyleSheet(f"color: {color};")
        layout.addWidget(value, 1, col)
        return value

    def set_target(self, rpm: float) -> None:
        """Update the TARGET setpoint shown in the panel header."""
        self.target_rpm = rpm
        self._target_label.setText(f"{rpm:.0f} RPM")

    def update_metrics(self, actual: float):
        if self.target_rpm == 0.0:
            self.actual_value.set_value(actual, "RPM", 1)
            self.error_value.setText("--")
            return
        error = abs((actual - self.target_rpm) / self.target_rpm * 100)

        self.actual_value.set_value(actual, "RPM", 1)
        self.error_value.setText(f"{error:.1f}%")

        # Color based on error
        if error > 10:
            color = Theme.ERROR
            self.status_indicator.set_color(Theme.ERROR)
        elif error > 5:
            color = Theme.WARNING
            self.status_indicator.set_color(Theme.WARNING)
        else:
            color = Theme.SUCCESS
            self.status_indicator.set_color(Theme.SUCCESS)

        self.actual_value.setStyleSheet(f"color: {color};")
        self.error_value.setStyleSheet(f"color: {color};")

    def set_running(self, running: bool):
        if running:
            self.status_indicator.start()
        else:
            self.status_indicator.stop()

    def set_manual_mode(self, enabled: bool):
        """Show/hide manual speed input field."""
        if enabled:
            self.manual_row.show()
        else:
            self.manual_row.hide()

    def _on_set_clicked(self):
        """User clicked SET button — commit the entered speed to hardware."""
        text = self.manual_input.text().strip()
        if text:
            try:
                value = float(text)
                self.manual_speed_changed.emit(value)
            except ValueError:
                pass


# ============================================================================
# PITCH GRAPH
# ============================================================================

class PitchGraph(GlowingCard):
    """Enhanced pitch history graph"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        
        self.data: List[Tuple[float, float]] = []
        self.max_points = 100
        self.max_distance = 500
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        
        header = QLabel("Pitch History")
        header.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold))
        header.setStyleSheet(f"color: {Theme.ACCENT_PRIMARY};")
        layout.addWidget(header)
        
        self.canvas = QWidget()
        self.canvas.setMinimumHeight(160)
        layout.addWidget(self.canvas, 1)
        
    def add_point(self, distance: float, pitch: float):
        self.data.append((distance, pitch))
        if len(self.data) > self.max_points:
            self.data.pop(0)
        self.update()
        
    def clear(self):
        self.data.clear()
        self.update()
        
    def paintEvent(self, event):
        super().paintEvent(event)
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        margin = 24
        header_h = 50
        graph = self.rect().adjusted(margin + 30, header_h, -margin, -margin - 20)
        
        if graph.width() < 50 or graph.height() < 50:
            painter.end()
            return
            
        # Background
        painter.fillRect(graph, QColor(Theme.BG_SECONDARY))
        
        # Grid
        pen = QPen(QColor(Theme.BORDER))
        pen.setWidth(1)
        painter.setPen(pen)
        
        for i in range(6):
            x = graph.left() + graph.width() * i // 5
            painter.drawLine(x, graph.top(), x, graph.bottom())
            
        for i in range(5):
            y = graph.top() + graph.height() * i // 4
            painter.drawLine(graph.left(), y, graph.right(), y)
            
        # Labels
        painter.setFont(QFont("Consolas", 8))
        painter.setPen(QColor(Theme.TEXT_MUTED))
        
        for i in range(6):
            x = graph.left() + graph.width() * i // 5
            painter.drawText(x - 12, graph.bottom() + 15, f"{int(self.max_distance * i / 5)}")
            
        for i in range(5):
            y = graph.bottom() - graph.height() * i // 4
            painter.drawText(graph.left() - 28, y + 4, f"{i * 0.5:.1f}")
            
        # Axis titles
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(graph.center().x() - 35, graph.bottom() + 32, "Distance (mm)")
        
        painter.save()
        painter.translate(graph.left() - 50, graph.center().y() + 35)
        painter.rotate(-90)
        painter.drawText(0, 0, "Pitch (mm)")
        painter.restore()
        
        # Data line with gradient
        if len(self.data) > 1:
            path = QPainterPath()
            first = True
            
            for dist, pitch in self.data:
                x = graph.left() + (dist / self.max_distance) * graph.width()
                y = graph.bottom() - (pitch / 2.0) * graph.height()
                x = max(graph.left(), min(graph.right(), x))
                y = max(graph.top(), min(graph.bottom(), y))
                
                if first:
                    path.moveTo(x, y)
                    first = False
                else:
                    path.lineTo(x, y)
                    
            # Glow effect
            glow_pen = QPen(QColor(Theme.ACCENT_PRIMARY))
            glow_pen.setWidth(6)
            painter.setPen(glow_pen)
            painter.setOpacity(0.3)
            painter.drawPath(path)
            
            # Main line
            painter.setOpacity(1.0)
            pen = QPen(QColor(Theme.ACCENT_PRIMARY))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawPath(path)
            
        # Empty state
        if not self.data:
            painter.setFont(QFont("Segoe UI", 11))
            painter.setPen(QColor(Theme.TEXT_MUTED))
            text = "Awaiting pitch data..."
            tr = painter.fontMetrics().boundingRect(text)
            painter.drawText(graph.center().x() - tr.width() // 2, graph.center().y(), text)
            
        # Border
        painter.setPen(QPen(QColor(Theme.BORDER), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(graph)
        
        painter.end()


# ============================================================================
# ALERT LOG
# ============================================================================

class AlertLog(GlowingCard):
    """System alert log with styled entries"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)
        
        header = QLabel("System Log")
        header.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold))
        header.setStyleSheet(f"color: {Theme.ACCENT_PRIMARY};")
        layout.addWidget(header)
        
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: {Theme.BG_SECONDARY};
                border: 1px solid {Theme.BORDER};
                border-radius: 6px;
            }}
            QScrollBar:vertical {{
                background-color: {Theme.BG_SECONDARY};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {Theme.BORDER_LIGHT};
                border-radius: 4px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {Theme.ACCENT_PRIMARY};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
        """)
        
        self.container = QWidget()
        self.log_layout = QVBoxLayout(self.container)
        self.log_layout.setContentsMargins(8, 8, 8, 8)
        self.log_layout.setSpacing(2)
        self.log_layout.addStretch()
        
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll, 1)
        
    def log(self, message: str, level: str = "info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        colors = {
            "info": Theme.TEXT_SECONDARY,
            "success": Theme.SUCCESS,
            "warning": Theme.WARNING,
            "error": Theme.ERROR
        }
        
        icons = {
            "info": "ℹ",
            "success": "✓",
            "warning": "⚠",
            "error": "✕"
        }
        
        entry = QLabel(f"{icons.get(level, '•')} [{timestamp}] {message}")
        entry.setFont(QFont("Consolas", 10))
        entry.setWordWrap(True)
        entry.setStyleSheet(f"color: {colors.get(level, Theme.TEXT_SECONDARY)}; padding: 3px;")
        
        self.log_layout.insertWidget(self.log_layout.count() - 1, entry)
        
        QTimer.singleShot(50, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()
        ))


# ============================================================================
# CONTROL PANEL
# ============================================================================

class ControlPanel(GlowingCard):
    """Control buttons panel with Manual Mode toggle."""

    start_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    snapshot_clicked = pyqtSignal()
    recalibrate_clicked = pyqtSignal()
    manual_mode_toggled = pyqtSignal(bool)  # True = manual ON

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        header = QLabel("Controls")
        header.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold))
        header.setStyleSheet(f"color: {Theme.ACCENT_PRIMARY};")
        layout.addWidget(header)

        grid = QGridLayout()
        grid.setSpacing(12)

        self.start_btn = AnimatedButton("START", Theme.SUCCESS, Theme.SUCCESS_GLOW)
        self.start_btn.clicked.connect(self.start_clicked.emit)

        self.stop_btn = AnimatedButton("STOP", Theme.ERROR, Theme.ERROR_GLOW)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_clicked.emit)

        self.snapshot_btn = AnimatedButton("SNAPSHOT", Theme.INFO, Theme.INFO_GLOW)
        self.snapshot_btn.clicked.connect(self.snapshot_clicked.emit)

        self.recalibrate_btn = AnimatedButton("RECALIBRATE", Theme.WARNING, Theme.WARNING_GLOW)
        self.recalibrate_btn.clicked.connect(self.recalibrate_clicked.emit)

        grid.addWidget(self.start_btn, 0, 0)
        grid.addWidget(self.stop_btn, 0, 1)
        grid.addWidget(self.snapshot_btn, 1, 0)
        grid.addWidget(self.recalibrate_btn, 1, 1)

        layout.addLayout(grid)

        # --- Manual Mode toggle button ---
        self._manual_mode_on = False
        self.manual_btn = QPushButton("MANUAL MODE: OFF")
        self.manual_btn.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        self.manual_btn.setMinimumHeight(44)
        self.manual_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.manual_btn.setCheckable(True)
        self._apply_manual_btn_style(False)
        self.manual_btn.clicked.connect(self._on_manual_toggled)
        layout.addWidget(self.manual_btn)

    def _on_manual_toggled(self):
        checked = self.manual_btn.isChecked()
        self.set_manual_mode(checked)
        self.manual_mode_toggled.emit(checked)

    def set_manual_mode(self, on: bool):
        """Update button appearance to reflect manual mode state."""
        self._manual_mode_on = on
        self.manual_btn.setChecked(on)
        self.manual_btn.setText(f"MANUAL MODE: {'ON' if on else 'OFF'}")
        self._apply_manual_btn_style(on)

    def _apply_manual_btn_style(self, on: bool):
        if on:
            self.manual_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Theme.WARNING};
                    color: #000000;
                    border: none;
                    border-radius: 8px;
                    padding: 10px 20px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background-color: {Theme.WARNING_GLOW};
                }}
            """)
        else:
            self.manual_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Theme.BG_ELEVATED};
                    color: {Theme.TEXT_SECONDARY};
                    border: 1px solid {Theme.BORDER};
                    border-radius: 8px;
                    padding: 10px 20px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background-color: {Theme.BG_HOVER};
                    border-color: {Theme.BORDER_LIGHT};
                }}
            """)

    def set_running(self, running: bool):
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)


# ============================================================================
# MAIN WINDOW
# ============================================================================

class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self, config: AppConfig):
        super().__init__()
        self.setWindowTitle("Silverworm Control System")
        self.setMinimumSize(1400, 900)
        self.resize(1600, 1000)

        self.config = config
        self._is_running = False
        self._distance = 0
        self._calibrated_scale_um_per_px: float = config.scale_um_per_px
        # True once user has clicked Apply in ManualOverlayPanel.
        # Prevents pipeline results from overwriting a manually-committed value.
        self._calibration_manually_applied: bool = config.scale_um_per_px > 0

        # Camera and processing components
        self.camera_worker: Optional[CameraWorker] = None          # active worker (alias)
        self._primary_worker: Optional[CameraWorker] = None        # microscope
        self._secondary_worker: Optional[CameraWorker] = None      # external webcam
        self._active_camera: str = "microscope"
        self._current_raw_frame: Optional[np.ndarray] = None       # latest frame for auto-capture
        self.pitch_pipeline = PitchDetectionPipeline(interval_ms=2000, parent=self)
        self.manual_banner: Optional[ManualModeBanner] = None

        # Rolling 5-minute incident buffer + file storage
        self.rolling_buffer = RollingBuffer(window_seconds=300.0)
        self.storage = StorageManager()

        # Controller + comms (MockTransport for dev; swap for SerialTransport on Pi)
        self.controller = SetpointController()
        self.transport: Transport = MockTransport()
        self.transport.open()
        self._last_comms_ok = True

        # New protocol layer (PUI over I2C, motors over SPI). MockPUITransport
        # and MockSPITransport are used until we're on the Pi.
        from comms import (
            MockPUITransport, MockSPITransport, PUIListener, MotorController,
        )
        from app_state import AppState
        self._pui_transport = MockPUITransport()
        self.pui_listener = PUIListener(self._pui_transport, parent=self)
        self._wrap_spi = MockSPITransport()
        self._feed_spi = MockSPITransport()
        self.wrap_motor = MotorController(self._wrap_spi, parent=self)
        self.feed_motor = MotorController(self._feed_spi, parent=self)
        self.wrap_motor.open()
        self.feed_motor.open()
        self.app_state = AppState(
            self.config,
            wrap_motor=self.wrap_motor,
            feed_motor=self.feed_motor,
            parent=self,
        )
        self.pui_listener.start()

        # Snapshot default directory: OS-specific Pictures folder
        self._snapshot_dir = self._get_default_pictures_dir()

        self._setup_ui()
        self._setup_menu_bar()
        self._setup_timers()
        self._connect_signals()
        self._setup_controller()
        self._apply_styles()

        self.alert_log.log("System initialized", "success")
        self.alert_log.log("Awaiting camera connection...", "info")

        # Setup camera after UI is ready
        self._setup_camera()
        self._connect_camera_signals()
        
    @staticmethod
    def _get_default_pictures_dir() -> str:
        """
        Return the OS-specific Pictures directory.

        - macOS:  ~/Pictures
        - Windows: C:\\Users\\<user>\\Pictures
        - Linux:  ~/Pictures (or XDG equivalent)

        Falls back to home directory if Pictures doesn't exist.
        """
        pictures = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.PicturesLocation
        )
        if pictures and os.path.isdir(pictures):
            return pictures
        return str(Path.home())

    def _setup_menu_bar(self):
        """Create a standard menu bar with File menu for snapshot settings."""
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("File")

        snapshot_folder_action = file_menu.addAction("Set Default Snapshot Folder...")
        snapshot_folder_action.triggered.connect(self._on_set_snapshot_folder)

        file_menu.addSeparator()

        snapshot_action = file_menu.addAction("Save Snapshot")
        snapshot_action.setShortcut("Ctrl+S")
        snapshot_action.triggered.connect(self._on_snapshot)

        recording_action = file_menu.addAction("Save Last 5-Minute Recording")
        recording_action.setShortcut("Ctrl+R")
        recording_action.triggered.connect(self._on_save_recording)

        # Debug menu: simulate PUI messages from the GUI. Useful on macOS where
        # there's no real I2C device. Remove once a hardware PUI is connected.
        debug_menu = menu_bar.addMenu("Debug")
        debug_menu.addSection("PUI injection")
        for raw in ("D1+1", "D1+2", "D1+3", "D1-1", "D1-2", "D1-3"):
            debug_menu.addAction(
                f"Inject {raw}",
                lambda r=raw: self._inject_pui_message(r),
            )
        debug_menu.addSeparator()
        for raw in ("D2+1", "D2+2", "D2+3", "D2-1", "D2-2", "D2-3"):
            debug_menu.addAction(
                f"Inject {raw}",
                lambda r=raw: self._inject_pui_message(r),
            )
        debug_menu.addSeparator()
        for raw in ("AS0 (manual)", "AS1 (auto)", "TP (toggle power)"):
            label = raw.split(" ")[0]
            debug_menu.addAction(
                f"Inject {raw}",
                lambda r=label: self._inject_pui_message(r),
            )

        self._connect_app_state_signals()

    def _inject_pui_message(self, raw: str) -> None:
        self._pui_transport.inject(raw)

    def _connect_app_state_signals(self) -> None:
        """AppState is the single source of truth. The GUI buttons call into
        AppState; AppState emits signals; UI handlers (defined here) react.
        PUI events from the listener take the same path, so the GUI and the
        physical panel exercise identical code."""
        from app_state import Mode

        # Mode signal: log + propagate to manual-mode UI toggles.
        def on_mode(mode: Mode):
            self.alert_log.log(f"Mode → {mode.value.upper()}", "info")
            is_manual = mode == Mode.MANUAL
            self.controls.set_manual_mode(is_manual)
            self.feed_motor.set_manual_mode(is_manual)
            self.wrapper_motor.set_manual_mode(is_manual)
            if is_manual:
                self._manual_overlay_panel.show()
                self._recompute_pitch_overlay()
            else:
                self._manual_overlay_panel.hide()
                self.camera.clear_pitch_overlay()

        # Power signal: log + drive the running/stopped UI state.
        def on_power(on: bool):
            self.alert_log.log(
                f"Machine power → {'ON' if on else 'OFF'}",
                "success" if on else "warning",
            )
            self._apply_running_ui_state(on)

        # Speed signals: log only. Motor panel actual-value readouts are
        # driven by the existing metrics_timer; this is for diagnostics.
        def on_wrap(rpm: float):
            self.alert_log.log(f"Wrap speed: {rpm:.2f} rpm", "info")

        def on_feed(mms: float):
            self.alert_log.log(f"Feed speed: {mms:.3f} mm/s", "info")

        self.app_state.mode_changed.connect(on_mode)
        self.app_state.machine_power_changed.connect(on_power)
        self.app_state.wrap_speed_changed.connect(on_wrap)
        self.app_state.feed_speed_changed.connect(on_feed)

        # Route PUI events into AppState.
        self.pui_listener.dial_changed.connect(self.app_state.apply_dial_change)
        self.pui_listener.mode_switched.connect(self.app_state.apply_mode_switch)
        self.pui_listener.power_toggled.connect(self.app_state.apply_power_toggle)

        # Log raw PUI traffic for diagnostics.
        self.pui_listener.raw_message.connect(
            lambda raw: self.alert_log.log(f"PUI: {raw}", "info")
        )
        self.pui_listener.parse_error.connect(
            lambda raw: self.alert_log.log(f"PUI parse error: {raw}", "warning")
        )

    def _on_set_snapshot_folder(self):
        """Let user pick a new default snapshot folder via native directory picker."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Default Snapshot Folder",
            self._snapshot_dir,
            QFileDialog.Option.ShowDirsOnly,
        )
        if folder:
            self._snapshot_dir = folder
            self.alert_log.log(
                f"Default snapshot folder set to: {folder}", "info"
            )

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main = QHBoxLayout(central)
        main.setContentsMargins(24, 24, 24, 24)
        main.setSpacing(24)
        
        # Left column
        left = QVBoxLayout()
        left.setSpacing(20)
        
        # Header
        header_widget = QWidget()
        header = QHBoxLayout(header_widget)
        header.setContentsMargins(0, 0, 0, 12)
        
        title = QLabel("Silverworm Control System")
        title.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {Theme.TEXT_PRIMARY};")
        
        self.status_indicator = PulsingIndicator(Theme.WARNING)
        self.status_label = QLabel("STANDBY")
        self.status_label.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        self.status_label.setStyleSheet(f"color: {Theme.WARNING};")
        
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.status_indicator)
        header.addWidget(self.status_label)
        
        left.addWidget(header_widget)
        
        # Camera
        camera_card = GlowingCard()
        camera_layout = QVBoxLayout(camera_card)
        camera_layout.setContentsMargins(16, 12, 16, 12)
        
        cam_header = QHBoxLayout()
        cam_title = QLabel("Live Camera View")
        cam_title.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold))
        cam_title.setStyleSheet(f"color: {Theme.ACCENT_PRIMARY};")

        cam_hint = QLabel("Click to focus • Arrow keys move crosshair • Shift for faster")
        cam_hint.setFont(QFont("Segoe UI", 9))
        cam_hint.setStyleSheet(f"color: {Theme.TEXT_MUTED};")

        # Camera source toggle button (microscope ↔ webcam)
        self._cam_toggle_btn = QPushButton("Switch to Webcam")
        self._cam_toggle_btn.setFixedHeight(26)
        self._cam_toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.BG_ELEVATED};
                color: {Theme.TEXT_SECONDARY};
                border: 1px solid {Theme.BORDER};
                border-radius: 4px;
                padding: 0 10px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {Theme.BG_HOVER};
                color: {Theme.ACCENT_PRIMARY};
                border-color: {Theme.ACCENT_PRIMARY};
            }}
            QPushButton:disabled {{
                color: {Theme.TEXT_DISABLED};
            }}
        """)
        self._cam_toggle_btn.setEnabled(False)  # enabled once second camera found
        self._cam_toggle_btn.clicked.connect(self._on_camera_toggle)

        # Label shown when camera feed is degraded/unavailable
        self._cam_warning_label = QLabel()
        self._cam_warning_label.setStyleSheet(f"color: {Theme.WARNING}; font-size: 11px;")
        self._cam_warning_label.hide()

        cam_header.addWidget(cam_title)
        cam_header.addStretch()
        cam_header.addWidget(self._cam_warning_label)
        cam_header.addWidget(cam_hint)
        cam_header.addWidget(self._cam_toggle_btn)
        camera_layout.addLayout(cam_header)
        
        self.camera = EnhancedCameraView()
        camera_layout.addWidget(self.camera)
        
        left.addWidget(camera_card, 2)

        # Manual mode overlay calibration panel (hidden until manual mode is active)
        self._manual_overlay_panel = ManualOverlayPanel()
        self._manual_overlay_panel.scale_applied.connect(self._on_overlay_scale_applied)
        self._manual_overlay_panel.set_scale(self._calibrated_scale_um_per_px)
        self._manual_overlay_panel.hide()
        left.addWidget(self._manual_overlay_panel)

        # Graph
        self.graph = PitchGraph()
        left.addWidget(self.graph, 1)
        
        main.addLayout(left, 3)
        
        # Right column
        right = QVBoxLayout()
        right.setSpacing(20)
        
        self.feed_motor = MotorMetricPanel(
            "Feed Motor", 1.0,
            speed_min=SPEED_A_MIN, speed_max=SPEED_A_MAX
        )
        self.wrapper_motor = MotorMetricPanel(
            "Wrapper Motor", 1000.0,
            speed_min=SPEED_B_MIN, speed_max=SPEED_B_MAX
        )
        
        right.addWidget(self.feed_motor)
        right.addWidget(self.wrapper_motor)
        
        # Pitch metrics
        pitch_card = GlowingCard()
        pitch_layout = QVBoxLayout(pitch_card)
        pitch_layout.setContentsMargins(20, 16, 20, 16)
        
        pitch_header = QLabel("Pitch Metrics")
        pitch_header.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold))
        pitch_header.setStyleSheet(f"color: {Theme.ACCENT_PRIMARY};")
        pitch_layout.addWidget(pitch_header)
        
        pitch_grid = QGridLayout()
        pitch_grid.setSpacing(16)
        
        for col, (label, default) in enumerate([("TARGET", "1.00 mm"), ("ACTUAL", "-- mm"), ("ERROR", "--")]):
            lbl = QLabel(label)
            lbl.setFont(QFont("Segoe UI", 9))
            lbl.setStyleSheet(f"color: {Theme.TEXT_MUTED};")
            pitch_grid.addWidget(lbl, 0, col)
            
            val = QLabel(default)
            val.setFont(QFont("Consolas", 18, QFont.Weight.Bold))
            pitch_grid.addWidget(val, 1, col)
            
            if label == "ACTUAL":
                self.pitch_actual = val
            elif label == "ERROR":
                self.pitch_error = val
                
        pitch_layout.addLayout(pitch_grid)
        right.addWidget(pitch_card)
        
        # Controls
        self.controls = ControlPanel()
        right.addWidget(self.controls)
        
        # Log
        self.alert_log = AlertLog()
        right.addWidget(self.alert_log, 1)
        
        main.addLayout(right, 1)
        
    def _setup_timers(self):
        self.metrics_timer = QTimer()
        self.metrics_timer.timeout.connect(self._update_metrics)
        
        self.graph_timer = QTimer()
        self.graph_timer.timeout.connect(self._update_graph)
        
    def _connect_signals(self):
        self.controls.start_clicked.connect(self._on_start)
        self.controls.stop_clicked.connect(self._on_stop)
        self.controls.snapshot_clicked.connect(self._on_snapshot)
        self.controls.recalibrate_clicked.connect(self._on_recalibrate)
        self.camera.position_changed.connect(self._on_position_changed)

        # Manual mode toggle from UI button
        self.controls.manual_mode_toggled.connect(self._on_manual_mode_button)

        # Manual speed SET buttons from motor panels
        self.feed_motor.manual_speed_changed.connect(self._on_feed_motor_set)
        self.wrapper_motor.manual_speed_changed.connect(self._on_wrapper_motor_set)

    def _setup_controller(self):
        """Wire controller callbacks to comms and UI."""
        self.controller.on_setpoints_changed = self._on_setpoints_changed
        self.controller.on_mode_changed = self._on_controller_mode_changed

    def _on_setpoints_changed(self, setpoints: Setpoints):
        """Send updated setpoints to hardware via transport."""
        self._last_comms_ok = True
        try:
            self.transport.send_speeds(setpoints.speed_a, setpoints.speed_b)
        except IOError as e:
            self._last_comms_ok = False
            self.alert_log.log(f"Comms error: {e}", "error")

    def _on_feed_motor_set(self, value: float):
        """User clicked SET on feed motor panel — routes through AppState,
        which forwards a SET_SPEED packet to the feed-motor SPI transport
        if the machine is running.

        Note: AppState's feed_speed is in mm/s but the existing motor panel
        labels its input "RPM". This unit mismatch will be reconciled once
        we know the Arduino's accepted units. For now the value is passed
        through verbatim.
        """
        self.app_state.gui_set_feed_speed(value)
        self.feed_motor.set_target(value)
        # Legacy path — kept so the controller-driven banners still fire.
        if self.controller.set_manual_speed_a(value):
            if self._last_comms_ok:
                self.camera.show_overlay_message(
                    f"Feed motor speed set to {value:.1f}"
                )
                self.alert_log.log(
                    f"Feed motor speed manually set: {value:.1f}", "success"
                )

    def _on_wrapper_motor_set(self, value: float):
        """User clicked SET on wrapper motor panel."""
        self.app_state.gui_set_wrap_speed(value)
        self.wrapper_motor.set_target(value)
        if self.controller.set_manual_speed_b(value):
            if self._last_comms_ok:
                self.camera.show_overlay_message(
                    f"Wrapper motor speed set to {value:.1f} RPM"
                )
                self.alert_log.log(
                    f"Wrapper motor speed manually set: {value:.1f} RPM", "success"
                )

    def _on_overlay_scale_applied(self, um_per_px: float) -> None:
        """User clicked Apply in the overlay panel."""
        self._calibrated_scale_um_per_px = um_per_px
        self._calibration_manually_applied = True
        self.config.scale_um_per_px = um_per_px
        save_config(self.config)
        self._recompute_pitch_overlay()
        self.alert_log.log(f"Overlay scale set: {um_per_px:.4g} µm/px", "info")

    def _recompute_pitch_overlay(self) -> None:
        """Compute overlay from current scale and config geometry, then push to camera.

        The spool is always horizontal so lines are always nearly vertical.
        Tilt = helix advance angle from config (arctan(P / π(D+2t))).
        Only scale is unknown — if it hasn't been set yet, clear the overlay.
        """
        scale = self._calibrated_scale_um_per_px
        if scale <= 0:
            scale = 2.0  # fallback until user enters a calibrated value
        spacing_px = self.config.target_pitch_um / scale
        tilt_deg = calculate_wrap_angle_deg(
            self.config.target_pitch_um,
            self.config.tube_diameter_mm,
            self.config.wire_thickness_um,
        )
        self.camera.set_pitch_overlay(spacing_px, tilt_deg)

    def _on_controller_mode_changed(self, mode: OperatingMode):
        """React to mode changes from the controller."""
        is_manual = mode == OperatingMode.MANUAL
        self.controls.set_manual_mode(is_manual)
        self.feed_motor.set_manual_mode(is_manual)
        self.wrapper_motor.set_manual_mode(is_manual)

        if is_manual:
            self.alert_log.log("Manual mode ON — enter motor speeds manually", "warning")
        else:
            self.alert_log.log("Auto mode ON — using vision-computed setpoints", "info")

    def _on_manual_mode_button(self, checked: bool):
        """User clicked the manual mode toggle button.

        Routes through AppState (single source of truth) and also through
        the legacy SetpointController so the low-confidence auto-trigger
        path continues to work."""
        from app_state import Mode
        self.app_state.gui_set_mode(Mode.MANUAL if checked else Mode.AUTO)
        if checked:
            self.controller.set_mode(OperatingMode.MANUAL)
        else:
            self.controller.set_mode(OperatingMode.AUTO)
        
    def _apply_styles(self):
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {Theme.BG_PRIMARY};
            }}
            QWidget {{
                color: {Theme.TEXT_PRIMARY};
                font-family: 'Segoe UI', -apple-system, sans-serif;
            }}
            QLabel {{
                background: transparent;
            }}
            QMenuBar {{
                background-color: {Theme.BG_SECONDARY};
                color: {Theme.TEXT_PRIMARY};
                border-bottom: 1px solid {Theme.BORDER};
                padding: 2px 0px;
                font-size: 13px;
            }}
            QMenuBar::item {{
                padding: 6px 14px;
                border-radius: 4px;
            }}
            QMenuBar::item:selected {{
                background-color: {Theme.BG_HOVER};
            }}
            QMenu {{
                background-color: {Theme.BG_CARD};
                color: {Theme.TEXT_PRIMARY};
                border: 1px solid {Theme.BORDER};
                border-radius: 8px;
                padding: 6px 0px;
            }}
            QMenu::item {{
                padding: 8px 30px 8px 20px;
            }}
            QMenu::item:selected {{
                background-color: {Theme.BG_HOVER};
                color: {Theme.ACCENT_PRIMARY};
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {Theme.BORDER};
                margin: 4px 12px;
            }}
        """)

    def _setup_camera(self):
        """Detect and initialize up to two camera workers (microscope + webcam)."""
        detector = CameraDetector()
        diag = detector.detect_all_devices()

        print(detector.format_diagnostic_report())
        self.alert_log.log("Running camera diagnostics...", "info")

        if not diag.devices:
            self.alert_log.log("No camera detected — running in demo mode", "warning")
            for err in diag.errors:
                self.alert_log.log(err, "error")
            for warn in diag.warnings[:2]:
                self.alert_log.log(warn, "warning")
            return

        # Rank all detected devices by priority (highest first)
        sorted_devices = sorted(diag.devices, key=lambda d: d.priority, reverse=True)
        primary_device = sorted_devices[0]
        secondary_device = sorted_devices[1] if len(sorted_devices) > 1 else None

        cam_cfg = CameraConfig.amscope_8300p_lowres()
        webcam_cfg = CameraConfig.default()

        # Primary (microscope / best-priority) worker
        self._primary_worker = CameraWorker(
            device_index=primary_device.index,
            config=cam_cfg,
            parent=self,
        )
        self._primary_worker.start()
        self.alert_log.log(
            f"Primary camera: {primary_device.name} ({primary_device.path})", "success"
        )

        # Secondary (external webcam) worker — started but not yet displayed
        if secondary_device:
            self._secondary_worker = CameraWorker(
                device_index=secondary_device.index,
                config=webcam_cfg,
                parent=self,
            )
            self._secondary_worker.start()
            self.alert_log.log(
                f"Secondary camera: {secondary_device.name} ({secondary_device.path})", "info"
            )
            self._cam_toggle_btn.setEnabled(True)
        else:
            self._cam_toggle_btn.setEnabled(False)

        # Default active camera is the microscope (primary)
        self._active_camera = "microscope"
        self.camera_worker = self._primary_worker  # keep alias current

    def _connect_camera_signals(self):
        """Connect the active camera worker to the display and rolling buffer."""
        self._first_frame_logged = False

        if self._primary_worker:
            self._primary_worker.frame_ready.connect(self.camera.update_frame)
            self._primary_worker.frame_ready.connect(self.rolling_buffer.add_frame)
            self._primary_worker.frame_ready.connect(self._on_raw_frame)

            def log_first_frame(frame):
                if not self._first_frame_logged:
                    self._first_frame_logged = True
                    self.alert_log.log(
                        f"Camera feed active — {frame.shape[1]}x{frame.shape[0]}", "success"
                    )
            self._primary_worker.frame_ready.connect(log_first_frame)
            self._primary_worker.status_changed.connect(
                lambda msg: self.alert_log.log(msg, "info")
            )
            self._primary_worker.error_occurred.connect(
                lambda err: self._handle_camera_error("microscope", err)
            )
            self._primary_worker.fps_updated.connect(self._on_fps_updated)

        if self._secondary_worker:
            # Secondary worker is started but its frames go nowhere yet;
            # _on_camera_toggle connects them to the display when selected.
            self._secondary_worker.error_occurred.connect(
                lambda err: self._handle_camera_error("webcam", err)
            )

        # Pitch detection signals - these will be connected when START is clicked
        self.pitch_pipeline.pitch_result_ready.connect(self._on_pitch_result)
        self.pitch_pipeline.manual_mode_triggered.connect(self._on_manual_mode)
        self.pitch_pipeline.detection_error.connect(
            lambda err: self.alert_log.log(err, "error")
        )

        # Manual mode banner (create when needed)
        # Will be created on first manual mode trigger

    def _on_fps_updated(self, fps: float):
        """Handle FPS updates from camera"""
        # Could display FPS in UI if desired
        pass

    def _on_pitch_result(self, result):
        """Handle pitch detection result"""
        try:
            # Capture scale from pipeline; keep panel field current.
            # If the user has already clicked Apply, only pre-fill the panel
            # (never overwrite a manually-committed value).
            # Auto-apply pipeline scale only until the user has committed a value.
            # After that, the panel field belongs to the user.
            detected_scale = getattr(result, "scale_um_per_px", 0.0)
            if not self._calibration_manually_applied:
                if detected_scale > 0 and detected_scale != self._calibrated_scale_um_per_px:
                    self._calibrated_scale_um_per_px = detected_scale
                    self._manual_overlay_panel.set_scale(detected_scale)
                    from app_state import Mode
                    if self.app_state.mode == Mode.MANUAL:
                        self._recompute_pitch_overlay()

            # Update UI metrics
            self.pitch_actual.setText(f"{result.mean_pitch_um:.2f} μm")

            # Calculate error from target (assume 1.00 mm = 1000 μm)
            target_um = 1000.0
            error_pct = abs((result.mean_pitch_um - target_um) / target_um * 100)
            self.pitch_error.setText(f"{error_pct:.1f}%")

            # Update graph
            if self._is_running:
                self.graph.add_point(self._distance, result.mean_pitch_um / 1000.0)  # Convert to mm

            # Log confidence
            confidence_colors = {
                "HIGH": "success",
                "MEDIUM": "info",
                "LOW": "warning",
                "FAILED": "error"
            }
            self.alert_log.log(
                f"Pitch: {result.mean_pitch_um:.1f}μm ({result.num_wraps} wraps), Confidence: {result.confidence}",
                confidence_colors.get(result.confidence, "info")
            )

            # Auto-capture on degraded confidence
            if result.confidence in ("LOW", "FAILED"):
                self._auto_capture(
                    alert_type=f"low_confidence_{result.confidence.lower()}",
                    confidence=result.confidence,
                    pitch_um=result.mean_pitch_um,
                )
        except Exception as e:
            self.alert_log.log(f"Error processing pitch result: {e}", "error")
            print(f"ERROR in _on_pitch_result: {e}")
            import traceback
            traceback.print_exc()

    def _on_manual_mode(self, confidence: str):
        """Manual mode triggered due to low confidence from vision pipeline."""
        # Use controller to trigger manual mode (sets ack-required flag)
        self.controller.trigger_manual_from_low_confidence()

        # Create manual mode banner if not exists
        if self.manual_banner is None:
            self.manual_banner = ManualModeBanner(self)
            self.manual_banner.setParent(self.centralWidget())
            self.manual_banner.setGeometry(24, 24, self.width() - 48, 60)
            self.manual_banner.acknowledged.connect(self._on_manual_mode_acknowledged)

        # Show banner
        self.manual_banner.show_banner()
        self.alert_log.log(
            f"Manual mode auto-triggered — confidence: {confidence}. "
            "Adjust alignment/focus and set speeds manually.",
            "warning"
        )
        self._auto_capture(alert_type="manual_mode_trigger", confidence=confidence)

    def _on_manual_mode_acknowledged(self):
        """User acknowledged manual mode banner."""
        self.controller.acknowledge_manual_mode()
        self.alert_log.log("Manual mode acknowledged — continuing operation", "info")

    def _on_start(self):
        # Single entry point for "begin running" — both this and PUI TP route
        # through AppState. The actual UI/pitch-pipeline updates happen in
        # _apply_running_ui_state, connected to machine_power_changed.
        self.app_state.gui_set_machine_on(True)

    def _on_stop(self):
        self.app_state.gui_set_machine_on(False)

    def _apply_running_ui_state(self, running: bool):
        """Mirror AppState.machine_on changes into the UI.

        Connected to AppState.machine_power_changed so GUI button clicks
        AND PUI TP events both land here. The SPI start/stop packet is
        emitted by AppState itself before this handler runs.
        """
        if running:
            try:
                self._is_running = True
                self.controls.set_running(True)
                self.feed_motor.set_running(True)
                self.wrapper_motor.set_running(True)

                self.status_indicator.set_color(Theme.SUCCESS)
                self.status_indicator.start()
                self.status_label.setText("RUNNING")
                self.status_label.setStyleSheet(f"color: {Theme.SUCCESS};")

                self.metrics_timer.start(150)
                self.graph_timer.start(500)

                if self.camera_worker and not hasattr(self, '_pitch_connected'):
                    try:
                        self.camera_worker.frame_ready.connect(self.pitch_pipeline.update_frame)
                        self._pitch_connected = True
                        self.alert_log.log("Pitch detection connected to camera", "info")
                    except Exception as e:
                        self.alert_log.log(f"Failed to connect pitch detection: {e}", "warning")

                try:
                    self.pitch_pipeline.start()
                    self.alert_log.log("Pitch detection started", "info")
                except Exception as e:
                    self.alert_log.log(f"Failed to start pitch detection: {e}", "warning")
                    print(f"Pitch detection error: {e}")
                    import traceback
                    traceback.print_exc()

                self.alert_log.log("System started — wrapping process initiated", "success")

            except Exception as e:
                self.alert_log.log(f"Error starting system: {e}", "error")
                print(f"ERROR in _apply_running_ui_state(True): {e}")
                import traceback
                traceback.print_exc()
                # Roll back via AppState so SPI also gets a stop packet
                try:
                    self.app_state.gui_set_machine_on(False)
                except Exception:
                    pass
        else:
            self._is_running = False
            self.controls.set_running(False)
            self.feed_motor.set_running(False)
            self.wrapper_motor.set_running(False)

            self.status_indicator.set_color(Theme.ERROR)
            self.status_indicator.stop()
            self.status_label.setText("STOPPED")
            self.status_label.setStyleSheet(f"color: {Theme.ERROR};")

            self.metrics_timer.stop()
            self.graph_timer.stop()

            try:
                self.pitch_pipeline.stop()
                self.alert_log.log("Pitch detection stopped", "info")
            except Exception as e:
                print(f"Error stopping pitch detection: {e}")

            self.alert_log.log("System stopped", "warning")
        
    def _on_snapshot(self):
        """Capture current camera frame and open native Save As dialog."""
        # Grab the current frame from the camera widget
        pixmap = self.camera._display_pixmap
        if pixmap is None or pixmap.isNull():
            self.alert_log.log("No camera frame to capture", "warning")
            return

        # Build a default filename with timestamp
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"snapshot_{ts}.png"
        default_path = os.path.join(self._snapshot_dir, default_name)

        # Open native Save As dialog
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Snapshot",
            default_path,
            "PNG Images (*.png);;JPEG Images (*.jpg *.jpeg);;All Files (*)",
        )

        if not file_path:
            # User cancelled
            return

        # Save the pixmap
        saved = pixmap.save(file_path)
        if saved:
            filename = os.path.basename(file_path)
            folder = os.path.dirname(file_path)
            self.alert_log.log(
                f"{filename} saved! — location: {folder}", "success"
            )
            # Update default dir to wherever user just saved
            self._snapshot_dir = folder
        else:
            self.alert_log.log(
                f"Failed to save snapshot to {file_path}", "error"
            )
        
    def _on_recalibrate(self):
        self.camera.h_offset = 0
        self.camera.v_offset = 0
        self.camera.update()
        
        self._distance = 0
        self.graph.clear()
        
        self.alert_log.log("Calibration reset - crosshair centered", "info")
        
    def _on_position_changed(self, x: int, y: int):
        if abs(x) > 50 or abs(y) > 50:
            self.alert_log.log(f"Large offset detected: ({x}, {y})", "warning")
            
    def _update_metrics(self):
        if not self._is_running:
            return

        from app_state import Mode
        if self.app_state.mode == Mode.MANUAL:
            # In manual mode we have no real feedback yet (mock transport).
            # Show the setpoint as both target and actual so error reads 0%.
            self.feed_motor.update_metrics(self.app_state.feed_speed_mms)
            self.wrapper_motor.update_metrics(self.app_state.wrap_speed_rpm)
            return

        # AUTO demo simulation (no real motor feedback yet)
        feed = 1.0 + random.gauss(0.5, 0.3)
        feed = max(0.5, min(3.0, feed))
        self.feed_motor.update_metrics(feed)

        t = datetime.now().timestamp()
        osc = math.sin(t * 0.5) * 50 + math.sin(t * 1.3) * 25
        wrapper = 925 + osc + random.gauss(0, 10)
        wrapper = max(850, min(1000, wrapper))
        self.wrapper_motor.update_metrics(wrapper)

        if abs(feed - 1.0) > 1.0:
            self.alert_log.log(f"Feed motor deviation: {feed:.1f} RPM", "warning")
            
    def _update_graph(self):
        if not self._is_running:
            return

        self._distance += random.uniform(2, 5)
        if self._distance > 500:
            self._distance = 0
            self.graph.clear()

        # Graph is now updated by pitch detection results
        # This is just for distance tracking

    # ------------------------------------------------------------------
    # Camera toggle
    # ------------------------------------------------------------------

    def _on_raw_frame(self, frame: np.ndarray) -> None:
        """Keep a reference to the latest frame for auto-capture."""
        self._current_raw_frame = frame

    def _on_camera_toggle(self):
        """Switch the displayed feed between microscope and external webcam."""
        if self._active_camera == "microscope":
            if self._secondary_worker is None:
                self.alert_log.log("No secondary camera available", "warning")
                return
            # Disconnect primary from display/buffer; connect secondary
            self._primary_worker.frame_ready.disconnect(self.camera.update_frame)
            self._primary_worker.frame_ready.disconnect(self.rolling_buffer.add_frame)
            self._primary_worker.frame_ready.disconnect(self._on_raw_frame)
            self._secondary_worker.frame_ready.connect(self.camera.update_frame)
            self._secondary_worker.frame_ready.connect(self.rolling_buffer.add_frame)
            self._secondary_worker.frame_ready.connect(self._on_raw_frame)
            self._active_camera = "webcam"
            self.camera_worker = self._secondary_worker
            self._cam_toggle_btn.setText("Switch to Microscope")
            self.alert_log.log("Camera feed → webcam", "info")
            self._cam_warning_label.hide()
        else:
            if self._primary_worker is None:
                self.alert_log.log("No microscope camera available", "warning")
                return
            self._secondary_worker.frame_ready.disconnect(self.camera.update_frame)
            self._secondary_worker.frame_ready.disconnect(self.rolling_buffer.add_frame)
            self._secondary_worker.frame_ready.disconnect(self._on_raw_frame)
            self._primary_worker.frame_ready.connect(self.camera.update_frame)
            self._primary_worker.frame_ready.connect(self.rolling_buffer.add_frame)
            self._primary_worker.frame_ready.connect(self._on_raw_frame)
            self._active_camera = "microscope"
            self.camera_worker = self._primary_worker
            self._cam_toggle_btn.setText("Switch to Webcam")
            self.alert_log.log("Camera feed → microscope", "info")
            self._cam_warning_label.hide()

    def _handle_camera_error(self, role: str, err: str):
        """Handle a camera error from the given role ('microscope' or 'webcam')."""
        self.alert_log.log(f"Camera error ({role}): {err}", "error")
        if role == self._active_camera:
            self._cam_warning_label.setText(f"Camera error: {role}")
            self._cam_warning_label.show()

    # ------------------------------------------------------------------
    # Rolling-buffer recording
    # ------------------------------------------------------------------

    def _on_save_recording(self):
        """Save the rolling 5-minute buffer to a timestamped MP4 file."""
        if self.rolling_buffer.frame_count == 0:
            self.alert_log.log("No frames in buffer yet — nothing to save", "warning")
            return

        path = self.storage.timestamped_path(
            self.storage.recordings_dir, "recording", "mp4"
        )
        dur = self.rolling_buffer.duration_seconds
        self.alert_log.log(
            f"Saving recording ({dur:.0f}s, {self.rolling_buffer.frame_count} frames)...",
            "info",
        )

        ok = self.rolling_buffer.save(path)
        if ok:
            self.alert_log.log(f"Recording saved: {path.name}", "success")
        else:
            self.alert_log.log("Recording save failed (cv2 or no frames)", "error")

    # ------------------------------------------------------------------
    # Auto-capture screenshots on significant events
    # ------------------------------------------------------------------

    def _auto_capture(
        self,
        alert_type: str,
        confidence: Optional[str] = None,
        pitch_um: Optional[float] = None,
    ) -> None:
        """Save a screenshot and linked alert log entry for a significant event.

        Called internally when errors, warnings, low-confidence results, or
        manual-mode triggers occur.
        """
        frame = self._current_raw_frame
        if frame is None:
            return

        prefix = f"auto_{alert_type.lower().replace(' ', '_')}"
        screenshot_path = self.storage.save_screenshot(frame, prefix=prefix)

        entry = {
            "timestamp": datetime.now().isoformat(),
            "alert_type": alert_type,
            "confidence": confidence,
            "pitch_um": pitch_um,
            "active_camera": self._active_camera,
            "screenshot": str(screenshot_path) if screenshot_path else None,
        }
        self.storage.save_alert_entry(entry)

    def closeEvent(self, event):
        """Clean up camera workers, transport, and storage on window close."""
        if self._primary_worker:
            self._primary_worker.stop()
        if self._secondary_worker:
            self._secondary_worker.stop()
        self.pitch_pipeline.stop()
        self.storage.shutdown()
        try:
            self.transport.close()
        except Exception:
            pass
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Silverworm")
    app.setOrganizationName("Silverworm")

    # Pre-populate startup dialog with saved config if present and the user
    # previously opted to remember settings. Otherwise show defaults.
    saved = load_config()
    initial = saved if (saved and saved.remember_settings) else None

    dialog = StartupConfigDialog(initial=initial)
    if dialog.exec() != StartupConfigDialog.DialogCode.Accepted:
        sys.exit(0)

    config = dialog.config()
    if config.remember_settings:
        save_config(config)

    window = MainWindow(config)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

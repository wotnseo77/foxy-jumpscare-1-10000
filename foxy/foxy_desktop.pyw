"""Standalone Foxy jumpscare app for Windows desktop.

Place foxy.png, foxy.xml, and jumpscare.wav in the same folder as this file.
Requires: Python 3.10+ and PyQt6 (including Qt Multimedia).
"""

import json
import os
import random
import sys
import time
import logging
import xml.etree.ElementTree as ET
from fractions import Fraction

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QGuiApplication, QPainter, QPixmap, QAction
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
    QStyle,
)
from PyQt6.QtMultimedia import QMediaDevices, QSoundEffect

ANIMATION_DURATION_SECONDS = 0.5
APP_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_PATH = os.path.join(APP_DIR, "foxy.png")
XML_PATH = os.path.join(APP_DIR, "foxy.xml")
SOUND_PATH = os.path.join(APP_DIR, "jumpscare.wav")
CONFIG_PATH = os.path.join(APP_DIR, "foxy_desktop_config.json")
LOG_PATH = os.path.join(APP_DIR, "foxy_desktop.log")
logging.basicConfig(filename=LOG_PATH, level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
DEFAULT_CONFIG = {"volume": 0.5, "chance": "1/10000", "jumpscare_count": 0}


def load_config():
    config = DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as file:
            saved = json.load(file)
        if isinstance(saved, dict):
            config.update(saved)
    except FileNotFoundError:
        pass
    except Exception:
        # Keep defaults if the config file is malformed.
        pass

    try:
        config["volume"] = max(0.0, min(1.0, float(config.get("volume", 0.5))))
    except (TypeError, ValueError):
        config["volume"] = 0.5
    try:
        config["jumpscare_count"] = max(0, int(config.get("jumpscare_count", 0)))
    except (TypeError, ValueError):
        config["jumpscare_count"] = 0
    config["chance"] = str(config.get("chance", "1/10000"))
    return config


def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as file:
        json.dump(config, file, ensure_ascii=False, indent=2)


def parse_chance(value):
    try:
        chance = float(Fraction(str(value).strip().replace(" ", "")))
        return max(0.0, min(1.0, chance))
    except (ValueError, ZeroDivisionError, TypeError):
        return 1 / 10000


def load_frames():
    for path in (IMAGE_PATH, XML_PATH, SOUND_PATH):
        if not os.path.isfile(path):
            raise FileNotFoundError(
                f"Required file not found:\n{path}\n\n"
                "Put foxy.png, foxy.xml, and jumpscare.wav in the same folder "
                "as foxy_desktop.pyw."
            )

    sheet = QPixmap(IMAGE_PATH)
    if sheet.isNull():
        raise ValueError(f"Could not open the sprite image:\n{IMAGE_PATH}")

    tree = ET.parse(XML_PATH)
    root = tree.getroot()
    result = []

    for sub in root.findall("SubTexture"):
        x = int(sub.get("x"))
        y = int(sub.get("y"))
        width = int(sub.get("width"))
        height = int(sub.get("height"))
        frame_x = int(sub.get("frameX", 0))
        frame_y = int(sub.get("frameY", 0))
        frame_width = int(sub.get("frameWidth", width))
        frame_height = int(sub.get("frameHeight", height))

        sprite = sheet.copy(x, y, width, height)
        frame = QPixmap(frame_width, frame_height)
        frame.fill(Qt.GlobalColor.transparent)
        painter = QPainter(frame)
        painter.drawPixmap(-frame_x, -frame_y, sprite)
        painter.end()
        result.append(frame)

    if not result:
        raise ValueError("No SubTexture frames were found in foxy.xml.")
    return result


class FoxyDesktopApp:
    def __init__(self, app, frames):
        self.app = app
        self.frames = frames
        self.config = load_config()
        self.is_playing = False
        self.overlay = None
        self.animation_timer = None

        self.sound = QSoundEffect(self.app)
        self.sound.setSource(QUrl.fromLocalFile(SOUND_PATH))
        self.sound.setVolume(self.config["volume"])
        self.sound.setAudioDevice(QMediaDevices.defaultAudioOutput())

        self.tray = QSystemTrayIcon(self.app)
        self.tray.setIcon(self.app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self.tray.setToolTip("Foxy Desktop Jumpscare")

        menu = QMenu()
        settings_action = QAction("Settings", menu)
        settings_action.triggered.connect(self.show_settings)
        test_action = QAction("Test jumpscare", menu)
        test_action.triggered.connect(lambda checked=False: self.play_jumpscare())
        quit_action = QAction("Exit", menu)
        quit_action.triggered.connect(self.app.quit)
        menu.addAction(test_action)
        menu.addAction(settings_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)

        self.timer = QTimer(self.app)
        self.timer.timeout.connect(self.check_random)
        self.timer.start(1000)

        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        else:
            self.show_fallback_window()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_settings()

    def check_random(self):
        if self.is_playing:
            return
        if random.random() < parse_chance(self.config.get("chance", "1/10000")):
            self.play_jumpscare()

    def play_jumpscare(self):
        if self.is_playing:
            return

        self.is_playing = True
        self.config["jumpscare_count"] = int(self.config.get("jumpscare_count", 0)) + 1
        try:
            save_config(self.config)
        except OSError:
            logging.exception("Could not save the jumpscare count")

        try:
            # Sound is optional: a playback-device problem should not prevent the image.
            try:
                self.sound.setVolume(float(self.config.get("volume", 0.5)))
                self.sound.setAudioDevice(QMediaDevices.defaultAudioOutput())
                self.sound.stop()
                self.sound.play()
            except Exception:
                logging.exception("Sound playback failed; showing the animation anyway")

            screen = QGuiApplication.primaryScreen()
            if screen is None:
                raise RuntimeError("Windows did not report a primary display.")

            overlay = QLabel()
            overlay.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.SubWindow
            )
            overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            overlay.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            overlay.setStyleSheet("background-color: transparent; border: none;")
            overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            overlay.setScaledContents(True)
            self.overlay = overlay
            self.animation_started_at = time.monotonic()

            overlay.showFullScreen()
            overlay.raise_()
            overlay.activateWindow()

            index = {"value": 0}
            self.animation_timer = QTimer(overlay)

            def next_frame():
                try:
                    if overlay.isHidden():
                        self.animation_timer.stop()
                        self.is_playing = False
                        self.overlay = None
                        return

                    if index["value"] < len(self.frames):
                        overlay.setPixmap(self.frames[index["value"]])
                        index["value"] += 1
                        return

                    minimum_duration = ANIMATION_DURATION_SECONDS
                    elapsed = time.monotonic() - self.animation_started_at
                    if elapsed < minimum_duration:
                        overlay.setPixmap(self.frames[-1])
                        return

                    self.animation_timer.stop()
                    overlay.close()
                    self.is_playing = False
                    self.overlay = None
                except Exception:
                    logging.exception("Animation frame update failed")
                    try:
                        self.animation_timer.stop()
                        overlay.close()
                    except Exception:
                        pass
                    self.is_playing = False
                    self.overlay = None
                    QMessageBox.critical(None, "Foxy Desktop", f"Could not display the animation. See the log file:\n{LOG_PATH}")

            self.animation_timer.timeout.connect(next_frame)
            # Spread every sprite frame across the 0.5-second animation window.
            frame_interval_ms = max(1, int(ANIMATION_DURATION_SECONDS * 1000 / len(self.frames)))
            self.animation_timer.start(frame_interval_ms)
            next_frame()
            logging.info("Jumpscare started successfully")

        except Exception as error:
            logging.exception("Could not start the jumpscare overlay")
            self.is_playing = False
            if self.overlay is not None:
                try:
                    self.overlay.close()
                except Exception:
                    pass
                self.overlay = None
            QMessageBox.critical(
                None,
                "Foxy Desktop - display error",
                f"Could not show the jumpscare:\n{error}\n\nDetails saved to:\n{LOG_PATH}",
            )

    def show_settings(self):
        dialog = QDialog()
        dialog.setWindowTitle("Foxy Desktop Settings")
        layout = QVBoxLayout(dialog)

        volume_box = QDoubleSpinBox()
        volume_box.setRange(0.0, 1.0)
        volume_box.setSingleStep(0.1)
        volume_box.setDecimals(2)
        volume_box.setValue(float(self.config.get("volume", 0.5)))
        layout.addWidget(QLabel("Volume (0.0 = mute, 1.0 = max)"))
        layout.addWidget(volume_box)

        chance_edit = QLineEdit(str(self.config.get("chance", "1/10000")))
        layout.addWidget(QLabel("Chance per second (example: 0.0001 or 1/10000)"))
        layout.addWidget(chance_edit)

        count_label = QLabel(f"Total Foxy jumpscares: {self.config.get('jumpscare_count', 0)}")
        layout.addWidget(count_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        layout.addWidget(buttons)

        def save_and_close():
            chance_text = chance_edit.text().strip()
            try:
                Fraction(chance_text.replace(" ", ""))
                if not chance_text:
                    raise ValueError
            except (ValueError, ZeroDivisionError):
                QMessageBox.warning(
                    dialog,
                    "Invalid chance",
                    "Enter a number like 0.0001 or a fraction like 1/10000.",
                )
                return

            self.config["volume"] = float(volume_box.value())
            self.config["chance"] = chance_text
            self.sound.setVolume(self.config["volume"])
            try:
                save_config(self.config)
            except OSError as error:
                QMessageBox.warning(dialog, "Could not save settings", str(error))
                return
            dialog.accept()

        buttons.accepted.connect(save_and_close)
        buttons.rejected.connect(dialog.reject)
        dialog.exec()

    def show_fallback_window(self):
        window = QWidget()
        window.setWindowTitle("Foxy Desktop Jumpscare")
        layout = QVBoxLayout(window)
        layout.addWidget(QLabel("Foxy is running. This window can stay minimized."))
        from PyQt6.QtWidgets import QPushButton
        settings = QPushButton("Settings")
        settings.clicked.connect(self.show_settings)
        test = QPushButton("Test jumpscare")
        test.clicked.connect(self.play_jumpscare)
        quit_button = QPushButton("Exit")
        quit_button.clicked.connect(self.app.quit)
        layout.addWidget(settings)
        layout.addWidget(test)
        layout.addWidget(quit_button)
        window.show()
        self.fallback_window = window


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Foxy Desktop Jumpscare")
    app.setQuitOnLastWindowClosed(False)

    try:
        frames = load_frames()
    except Exception as error:
        logging.exception("Startup failed")
        QMessageBox.critical(None, "Foxy Desktop - startup error", f"{error}\n\nDetails saved to:\n{LOG_PATH}")
        return 1

    FoxyDesktopApp(app, frames)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
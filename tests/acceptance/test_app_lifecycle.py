"""Exercise the application event loop in isolation from pytest's QApplication."""

import os
import subprocess
import sys


def test_cancel_initial_login_exits_without_hidden_process():
    code = """
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog
from parking_app.ui.app import ParkingApplication
from parking_app.ui.login_window import LoginDialog

app = QApplication([])
controller = ParkingApplication.__new__(ParkingApplication)
controller.auth_service = None
controller.main_window = None
LoginDialog.exec = lambda self: QDialog.DialogCode.Rejected
watchdog = QTimer()
watchdog.setSingleShot(True)
watchdog.timeout.connect(lambda: app.exit(99))
watchdog.start(1500)
assert controller.run() == 0, 'Initial login cancellation left event loop running'
"""
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": "src"}
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr

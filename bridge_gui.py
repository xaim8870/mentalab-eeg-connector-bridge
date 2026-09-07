# bridge_gui.py

import logging
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from tkinter import (
    BOTH,
    END,
    LEFT,
    RIGHT,
    X,
    Button,
    Frame,
    Label,
    Text,
    Tk,
)

import uvicorn

from app.main import app


# ============================================================
# CONFIG
# ============================================================

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 8765

HEALTH_URL = (
    f"http://{BRIDGE_HOST}:{BRIDGE_PORT}/api/health"
)

DEVICE_STATUS_URL = (
    f"http://{BRIDGE_HOST}:{BRIDGE_PORT}/api/device/status"
)

COMPASS_PORTAL_URL = (
    "https://zeamhealthprovidersdashboard.netlify.app"
    "/admin/mentalab-connector"
)


logger = logging.getLogger(
    "mentalab.gui"
)


# ============================================================
# UVICORN THREAD
# ============================================================

class BridgeServer:
    def __init__(self):
        self.server = None
        self.thread = None
        self.error = None

    def start(self):
        if (
            self.thread is not None
            and self.thread.is_alive()
        ):
            logger.warning(
                "Bridge server is already running."
            )
            return

        try:
            config = uvicorn.Config(
                app,
                host=BRIDGE_HOST,
                port=BRIDGE_PORT,
                log_level="info",

                # Our application handles request logging.
                access_log=False,

                # Do not let Uvicorn configure console
                # formatters inside a windowed PyInstaller app.
                log_config=None,
            )

            self.server = uvicorn.Server(
                config
            )

            self.thread = threading.Thread(
                target=self._run_server,
                name="MentalabBridgeServer",
                daemon=True,
            )

            logger.info(
                "Starting Mentalab Bridge server..."
            )

            self.thread.start()

        except Exception as exc:
            self.error = str(exc)

            logger.exception(
                "Unable to initialize Mentalab Bridge server."
            )

    def _run_server(self):
        try:
            if self.server is None:
                raise RuntimeError(
                    "Uvicorn server was not initialized."
                )

            self.server.run()

        except Exception as exc:
            self.error = str(exc)

            logger.exception(
                "Mentalab Bridge server terminated unexpectedly."
            )

    def stop(self):
        if self.server is None:
            return

        logger.info(
            "Stopping Mentalab Bridge server..."
        )

        self.server.should_exit = True

# ============================================================
# GUI
# ============================================================

class MentalabBridgeGUI:
    def __init__(self):
        self.root = Tk()

        self.root.title(
            "Compass Mentalab Bridge"
        )

        self.root.geometry(
            "620x520"
        )

        self.root.minsize(
            560,
            480,
        )

        self.root.configure(
            bg="#F8F6F1"
        )

        self.server = BridgeServer()

        self.bridge_online = False
        self.device_connected = False

        self._build_ui()

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self.quit_application,
        )

        self.append_log(
            "Starting Compass Mentalab Bridge..."
        )

        self.server.start()

        self.root.after(
            1000,
            self.refresh_status,
        )

    # ========================================================
    # UI
    # ========================================================

    def _build_ui(self):
        header = Frame(
            self.root,
            bg="#1E293B",
            padx=24,
            pady=22,
        )

        header.pack(
            fill=X
        )

        Label(
            header,
            text="Compass",
            font=(
                "Helvetica",
                22,
                "bold",
            ),
            fg="#F8F6F1",
            bg="#1E293B",
        ).pack(
            anchor="w"
        )

        Label(
            header,
            text="Mentalab EEG Bridge",
            font=(
                "Helvetica",
                13,
            ),
            fg="#C9A84C",
            bg="#1E293B",
        ).pack(
            anchor="w",
            pady=(4, 0),
        )

        content = Frame(
            self.root,
            bg="#F8F6F1",
            padx=24,
            pady=24,
        )

        content.pack(
            fill=BOTH,
            expand=True,
        )

        Label(
            content,
            text="Connection Status",
            font=(
                "Helvetica",
                17,
                "bold",
            ),
            fg="#1E293B",
            bg="#F8F6F1",
        ).pack(
            anchor="w",
            pady=(0, 16),
        )

        self.bridge_status = self._status_row(
            content,
            "Local Bridge",
            "Starting...",
        )

        self.portal_status = self._status_row(
            content,
            "Compass Portal",
            "Waiting for bridge",
        )

        self.device_status = self._status_row(
            content,
            "Mentalab Device",
            "Not connected",
        )

        button_frame = Frame(
            content,
            bg="#F8F6F1",
        )

        button_frame.pack(
            fill=X,
            pady=(22, 12),
        )

        Button(
            button_frame,
            text="Open Compass Portal",
            command=self.open_compass,
            bg="#C9A84C",
            fg="#1E293B",
            activebackground="#B99A42",
            activeforeground="#1E293B",
            relief="flat",
            padx=18,
            pady=10,
            font=(
                "Helvetica",
                11,
                "bold",
            ),
            cursor="hand2",
        ).pack(
            side=LEFT
        )

        Button(
            button_frame,
            text="Refresh Status",
            command=self.refresh_status,
            bg="#FFFFFF",
            fg="#1E293B",
            relief="solid",
            borderwidth=1,
            padx=18,
            pady=10,
            font=(
                "Helvetica",
                11,
            ),
            cursor="hand2",
        ).pack(
            side=LEFT,
            padx=(10, 0),
        )

        Button(
            button_frame,
            text="Quit Bridge",
            command=self.quit_application,
            bg="#FFFFFF",
            fg="#8B2E2E",
            relief="solid",
            borderwidth=1,
            padx=18,
            pady=10,
            font=(
                "Helvetica",
                11,
            ),
            cursor="hand2",
        ).pack(
            side=RIGHT
        )

        Label(
            content,
            text=(
                "Technical Status"
            ),
            font=(
                "Helvetica",
                12,
                "bold",
            ),
            fg="#1E293B",
            bg="#F8F6F1",
        ).pack(
            anchor="w",
            pady=(14, 8),
        )

        self.log_box = Text(
            content,
            height=9,
            bg="#FFFFFF",
            fg="#475569",
            relief="solid",
            borderwidth=1,
            font=(
                "Courier",
                9,
            ),
            padx=10,
            pady=10,
        )

        self.log_box.pack(
            fill=BOTH,
            expand=True,
        )

        self.log_box.configure(
            state="disabled"
        )

    def _status_row(
        self,
        parent,
        label_text,
        initial_value,
    ):
        row = Frame(
            parent,
            bg="#FFFFFF",
            padx=16,
            pady=13,
            highlightbackground="#DDD8CC",
            highlightthickness=1,
        )

        row.pack(
            fill=X,
            pady=5,
        )

        Label(
            row,
            text=label_text,
            font=(
                "Helvetica",
                11,
                "bold",
            ),
            fg="#1E293B",
            bg="#FFFFFF",
        ).pack(
            side=LEFT
        )

        value = Label(
            row,
            text=initial_value,
            font=(
                "Helvetica",
                11,
            ),
            fg="#64748B",
            bg="#FFFFFF",
        )

        value.pack(
            side=RIGHT
        )

        return value

    # ========================================================
    # STATUS
    # ========================================================

    def refresh_status(self):
        self._check_bridge()
        self._check_device()

        self.root.after(
            3000,
            self.refresh_status,
        )

    def _check_bridge(self):
        try:
            with urllib.request.urlopen(
                HEALTH_URL,
                timeout=2,
            ) as response:
                if response.status == 200:
                    if not self.bridge_online:
                        self.append_log(
                            "Local bridge is online."
                        )

                    self.bridge_online = True

                    self.bridge_status.config(
                        text="● Running",
                        fg="#3F8A6E",
                    )

                    self.portal_status.config(
                        text="● Ready",
                        fg="#3F8A6E",
                    )

                    return

        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
        ):
            pass

        if self.bridge_online:
            self.append_log(
                "Local bridge became unavailable."
            )

        self.bridge_online = False

        self.bridge_status.config(
            text="● Offline",
            fg="#B45353",
        )

        self.portal_status.config(
            text="Waiting for bridge",
            fg="#64748B",
        )

    def _check_device(self):
        if not self.bridge_online:
            self.device_status.config(
                text="Not available",
                fg="#64748B",
            )
            return

        try:
            with urllib.request.urlopen(
                DEVICE_STATUS_URL,
                timeout=2,
            ) as response:
                if response.status != 200:
                    raise RuntimeError(
                        "Unexpected status response."
                    )

                import json

                payload = json.loads(
                    response.read()
                )

                connected = bool(
                    payload.get(
                        "connected"
                    )
                )

                device = payload.get(
                    "device"
                )

                if connected:
                    name = (
                        device.get("name")
                        if isinstance(device, dict)
                        else "Mentalab"
                    )

                    self.device_status.config(
                        text=f"● {name}",
                        fg="#3F8A6E",
                    )

                    if not self.device_connected:
                        self.append_log(
                            f"Mentalab device connected: {name}"
                        )

                    self.device_connected = True

                else:
                    self.device_status.config(
                        text="○ Not connected",
                        fg="#64748B",
                    )

                    self.device_connected = False

        except Exception as exc:
            logger.debug(
                "Unable to read device status: %s",
                exc,
            )

            self.device_status.config(
                text="Status unavailable",
                fg="#64748B",
            )

    # ========================================================
    # ACTIONS
    # ========================================================

    def open_compass(self):
        logger.info(
            "Opening Compass portal."
        )

        webbrowser.open(
            COMPASS_PORTAL_URL
        )

    def append_log(
        self,
        message: str,
    ):
        timestamp = time.strftime(
            "%H:%M:%S"
        )

        self.log_box.configure(
            state="normal"
        )

        self.log_box.insert(
            END,
            f"[{timestamp}] {message}\n",
        )

        self.log_box.see(
            END
        )

        self.log_box.configure(
            state="disabled"
        )

    def quit_application(self):
        self.append_log(
            "Stopping bridge..."
        )

        self.server.stop()

        self.root.after(
            500,
            self.root.destroy,
        )

    def run(self):
        self.root.mainloop()


# ============================================================
# ENTRYPOINT
# ============================================================

if __name__ == "__main__":
    gui = MentalabBridgeGUI()
    gui.run()
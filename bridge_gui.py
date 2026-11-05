"""Compass Mentalab Bridge desktop launcher."""

import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from tkinter import BOTH, END, LEFT, RIGHT, X, Button, Frame, Label, Text, Tk

import uvicorn

from app.main import app

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 8765
BASE_URL = f"http://{BRIDGE_HOST}:{BRIDGE_PORT}"
HEALTH_URL = f"{BASE_URL}/api/health"
DEVICE_STATUS_URL = f"{BASE_URL}/api/device/status"
DEVICE_CONNECT_URL = f"{BASE_URL}/api/device/connect"
DEVICE_DISCONNECT_URL = f"{BASE_URL}/api/device/disconnect"
COMPASS_PORTAL_URL = (
    "https://zeamhealthprovidersdashboard.netlify.app"
    "/admin/mentalab-connector"
)

COLORS = {
    "navy": "#1E293B",
    "navy_hover": "#334155",
    "gold": "#D4A94B",
    "gold_hover": "#E4BB62",
    "green": "#176B52",
    "green_hover": "#238364",
    "surface": "#F8F6F1",
    "white": "#FFFFFF",
    "border": "#DDD8CC",
    "muted": "#64748B",
    "red": "#B45353",
    "red_hover": "#FDE8E8",
    "disabled": "#E5E7EB",
    "disabled_text": "#374151",
}

logger = logging.getLogger("mentalab.gui")


class BridgeServer:
    def __init__(self):
        self.server = None
        self.thread = None
        self.error = None

    def start(self):
        if self.thread is not None and self.thread.is_alive():
            logger.warning("Bridge server is already running.")
            return
        try:
            config = uvicorn.Config(
                app,
                host=BRIDGE_HOST,
                port=BRIDGE_PORT,
                log_level="info",
                access_log=False,
                log_config=None,
            )
            self.server = uvicorn.Server(config)
            self.thread = threading.Thread(
                target=self._run_server,
                name="MentalabBridgeServer",
                daemon=True,
            )
            logger.info("Starting Mentalab Bridge server...")
            self.thread.start()
        except Exception as exc:
            self.error = str(exc)
            logger.exception("Unable to initialize Mentalab Bridge server.")

    def _run_server(self):
        try:
            if self.server is None:
                raise RuntimeError("Uvicorn server was not initialized.")
            self.server.run()
        except Exception as exc:
            self.error = str(exc)
            logger.exception("Mentalab Bridge server terminated unexpectedly.")

    def stop(self):
        if self.server is not None:
            logger.info("Stopping Mentalab Bridge server...")
            self.server.should_exit = True


class MentalabBridgeGUI:
    STATUS_INTERVAL_MS = 3000
    QUEUE_INTERVAL_MS = 100

    def __init__(self):
        self.root = Tk()
        self.root.title("Compass Mentalab Bridge")
        self.root.geometry("640x590")
        self.root.minsize(570, 540)
        self.root.configure(bg=COLORS["surface"])

        self.server = BridgeServer()
        self.bridge_online = False
        self.device_connected = False
        self.device_connecting = False
        self.closed = False
        self.status_in_flight = False
        self.events = queue.Queue()

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.quit_application)
        self.append_log("Starting Compass Mentalab Bridge...")
        self.server.start()
        self.root.after(self.QUEUE_INTERVAL_MS, self._drain_events)
        self.root.after(1000, self._scheduled_status_refresh)

    def _button(self, parent, text, command, bg, fg, hover, bold=True):
        return Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=hover,
            activeforeground=fg,
            disabledforeground=COLORS["disabled_text"],
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=12,
            pady=11,
            font=("Helvetica", 11, "bold" if bold else "normal"),
            cursor="hand2",
        )

    def _build_ui(self):
        header = Frame(self.root, bg=COLORS["navy"], padx=24, pady=20)
        header.pack(fill=X)
        Label(
            header, text="Compass", font=("Helvetica", 22, "bold"),
            fg=COLORS["white"], bg=COLORS["navy"],
        ).pack(anchor="w")
        Label(
            header, text="Mentalab EEG Bridge", font=("Helvetica", 13),
            fg=COLORS["gold"], bg=COLORS["navy"],
        ).pack(anchor="w", pady=(4, 0))

        content = Frame(self.root, bg=COLORS["surface"], padx=24, pady=18)
        content.pack(fill=BOTH, expand=True)
        Label(
            content, text="Connection Status", font=("Helvetica", 17, "bold"),
            fg=COLORS["navy"], bg=COLORS["surface"],
        ).pack(anchor="w", pady=(0, 12))

        self.bridge_status = self._status_row(content, "Local Bridge", "Starting...")
        self.portal_status = self._status_row(content, "Compass Portal", "Waiting for bridge")
        self.device_status = self._status_row(content, "Mentalab Device", "Not connected")

        actions = Frame(content, bg=COLORS["surface"])
        actions.pack(fill=X, pady=(18, 6))
        top_actions = Frame(actions, bg=COLORS["surface"])
        top_actions.pack(fill=X, pady=(0, 8))
        bottom_actions = Frame(actions, bg=COLORS["surface"])
        bottom_actions.pack(fill=X)

        self.connect_button = self._button(
            top_actions, "Connect Mentalab", self.toggle_device_connection,
            COLORS["navy"], COLORS["white"], COLORS["navy_hover"],
        )
        self.connect_button.pack(side=LEFT, fill=X, expand=True, padx=(0, 5))

        self.portal_button = self._button(
            top_actions, "Open Compass Portal", self.open_compass,
            COLORS["gold"], COLORS["navy"], COLORS["gold_hover"],
        )
        self.portal_button.pack(side=LEFT, fill=X, expand=True, padx=(5, 0))

        self.refresh_button = self._button(
            bottom_actions, "Refresh Status", self.refresh_status,
            COLORS["white"], COLORS["navy"], COLORS["disabled"], False,
        )
        self.refresh_button.config(relief="solid", borderwidth=1)
        self.refresh_button.pack(side=LEFT, fill=X, expand=True, padx=(0, 5))

        self.quit_button = self._button(
            bottom_actions, "Quit Bridge", self.quit_application,
            COLORS["white"], COLORS["red"], COLORS["red_hover"], False,
        )
        self.quit_button.config(relief="solid", borderwidth=1)
        self.quit_button.pack(side=LEFT, fill=X, expand=True, padx=(5, 0))

        Label(
            content, text="Technical Status", font=("Helvetica", 12, "bold"),
            fg=COLORS["navy"], bg=COLORS["surface"],
        ).pack(anchor="w", pady=(14, 8))
        self.log_box = Text(
            content, height=8, bg=COLORS["white"], fg=COLORS["navy"],
            relief="solid", borderwidth=1, font=("Courier", 10),
            padx=10, pady=10, wrap="word",
        )
        self.log_box.pack(fill=BOTH, expand=True)
        self.log_box.configure(state="disabled")

    def _status_row(self, parent, label_text, initial_value):
        row = Frame(
            parent, bg=COLORS["white"], padx=16, pady=12,
            highlightbackground=COLORS["border"], highlightthickness=1,
        )
        row.pack(fill=X, pady=4)
        Label(
            row, text=label_text, font=("Helvetica", 11, "bold"),
            fg=COLORS["navy"], bg=COLORS["white"],
        ).pack(side=LEFT)
        value = Label(
            row, text=initial_value, font=("Helvetica", 11),
            fg=COLORS["muted"], bg=COLORS["white"],
        )
        value.pack(side=RIGHT)
        return value

    def _scheduled_status_refresh(self):
        if self.closed:
            return
        self.refresh_status()
        self.root.after(self.STATUS_INTERVAL_MS, self._scheduled_status_refresh)

    def refresh_status(self):
        """One-shot status refresh; does not create additional timer loops."""
        if self.closed or self.status_in_flight:
            return
        self.status_in_flight = True
        threading.Thread(
            target=self._status_worker, name="MentalabStatusCheck", daemon=True,
        ).start()

    @staticmethod
    def _get_json(url, timeout=2):
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError(f"Unexpected HTTP status: {response.status}")
            return json.loads(response.read().decode("utf-8"))

    def _status_worker(self):
        try:
            health = self._get_json(HEALTH_URL)
            online = bool(health.get("ok"))
        except Exception:
            online = False

        device_payload = None
        device_error = None
        if online:
            try:
                device_payload = self._get_json(DEVICE_STATUS_URL)
            except Exception as exc:
                device_error = str(exc)
        self.events.put(("status", online, device_payload, device_error))

    def _apply_status(self, online, device_payload, device_error):
        self.status_in_flight = False
        if online and not self.bridge_online:
            self.append_log("Local bridge is online.")
        if not online and self.bridge_online:
            self.append_log("Local bridge became unavailable.")
        self.bridge_online = online
        self.bridge_status.config(
            text="â— Running" if online else "â— Offline",
            fg=COLORS["green"] if online else COLORS["red"],
        )
        self.portal_status.config(
            text="â— Ready" if online else "Waiting for bridge",
            fg=COLORS["green"] if online else COLORS["muted"],
        )

        if not online:
            self.device_connected = False
            if not self.device_connecting:
                self.device_status.config(text="Not available", fg=COLORS["muted"])
                self._set_connect_button()
            return

        if device_error is not None or not isinstance(device_payload, dict):
            if not self.device_connecting:
                self.device_status.config(text="Status unavailable", fg=COLORS["muted"])
            return

        connected = bool(device_payload.get("connected"))
        device = device_payload.get("device")
        name = device.get("name") if isinstance(device, dict) else None
        name = name or "Mentalab"
        if connected and not self.device_connected:
            self.append_log(f"Mentalab device connected: {name}")
        self.device_connected = connected
        if not self.device_connecting:
            self.device_status.config(
                text=f"â— {name}" if connected else "â—‹ Not connected",
                fg=COLORS["green"] if connected else COLORS["muted"],
            )
            self._set_connect_button()

    def _set_connect_button(self):
        if self.device_connecting:
            return
        connected = self.device_connected
        self.connect_button.config(
            text="Disconnect Mentalab" if connected else "Connect Mentalab",
            bg=COLORS["green"] if connected else COLORS["navy"],
            fg=COLORS["white"],
            activebackground=COLORS["green_hover"] if connected else COLORS["navy_hover"],
            activeforeground=COLORS["white"],
            state="normal" if self.bridge_online else "disabled",
        )
        if not self.bridge_online:
            self.connect_button.config(
                bg=COLORS["disabled"],
                fg=COLORS["disabled_text"],
                disabledforeground=COLORS["disabled_text"],
            )

    def toggle_device_connection(self):
        if self.closed or self.device_connecting:
            return
        if not self.bridge_online:
            self.append_log("Cannot connect: local bridge is offline.")
            return
        self._start_device_action("disconnect" if self.device_connected else "connect")

    def _start_device_action(self, action):
        self.device_connecting = True
        busy_text = "Disconnecting..." if action == "disconnect" else "Connecting..."
        self.connect_button.config(
            text=busy_text, bg=COLORS["gold"], fg=COLORS["navy"],
            disabledforeground=COLORS["navy"], state="disabled",
        )
        self.device_status.config(text=busy_text, fg=COLORS["navy"])
        self.append_log(
            "Disconnecting Mentalab device..." if action == "disconnect"
            else "Connecting to Mentalab device..."
        )
        threading.Thread(
            target=self._device_action_worker, args=(action,),
            name="MentalabDeviceAction", daemon=True,
        ).start()

    def _device_action_worker(self, action):
        url = DEVICE_DISCONNECT_URL if action == "disconnect" else DEVICE_CONNECT_URL
        error = None
        try:
            request = urllib.request.Request(url, method="POST")
            with urllib.request.urlopen(request, timeout=45) as response:
                if response.status != 200:
                    raise RuntimeError(f"Unexpected HTTP status: {response.status}")
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                error = str(payload.get("detail") or exc)
            except Exception:
                error = str(exc)
        except Exception as exc:
            error = str(exc)
        self.events.put(("action", action, error))

    def _finish_device_action(self, action, error):
        self.device_connecting = False
        if error:
            self.append_log(f"Mentalab {action} failed: {error}")
            self.device_status.config(text="Connection failed", fg=COLORS["red"])
        else:
            self.device_connected = action == "connect"
            self.append_log(
                "Mentalab connection request succeeded." if action == "connect"
                else "Mentalab device disconnected."
            )
            self.device_status.config(
                text="â— Connected" if self.device_connected else "â—‹ Not connected",
                fg=COLORS["green"] if self.device_connected else COLORS["muted"],
            )
        self._set_connect_button()
        self.refresh_status()

    def _drain_events(self):
        if self.closed:
            return
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "status":
                    self._apply_status(*event[1:])
                elif event[0] == "action":
                    self._finish_device_action(*event[1:])
        except queue.Empty:
            pass
        self.root.after(self.QUEUE_INTERVAL_MS, self._drain_events)

    def open_compass(self):
        logger.info("Opening Compass portal.")
        webbrowser.open(COMPASS_PORTAL_URL)

    def append_log(self, message):
        if self.closed:
            return
        timestamp = time.strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert(END, f"[{timestamp}] {message}\n")
        self.log_box.see(END)
        self.log_box.configure(state="disabled")

    def quit_application(self):
        if self.closed:
            return
        self.append_log("Stopping bridge...")
        self.closed = True
        self.server.stop()
        self.root.after(500, self.root.destroy)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    MentalabBridgeGUI().run()

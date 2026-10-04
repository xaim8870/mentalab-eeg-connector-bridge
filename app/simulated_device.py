# app/simulated_device.py

import asyncio
import csv
from importlib.resources import files
import logging
import math
import random
import threading
import time
import uuid

from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from statistics import pstdev
from typing import Optional

from .models import MentalabDevice


logger = logging.getLogger("mentalab.simulator")


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = BASE_DIR / "recordings" / "simulated"
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

SIMULATED_DEVICE_NAME = "SIMULATED_AABH"
SIMULATED_MODEL = "Mentalab Explore Simulator"
SIMULATED_CHANNEL_COUNT = 8
SIMULATED_SAMPLING_RATE = 250
SIMULATED_BATTERY_PERCENT = 95

LIVE_WINDOW_SECONDS = 2
LIVE_BUFFER_SIZE = SIMULATED_SAMPLING_RATE * LIVE_WINDOW_SECONDS


# ============================================================
# SIMULATED DEVICE MANAGER
# ============================================================

class SimulatedMentalabDeviceManager:
    """
    Development-only replacement for the physical Mentalab Explore device.

    Synthetic EEG must never be interpreted or stored as clinical EEG.
    """

    def __init__(self):
        logger.warning("====================================================")
        logger.warning("MENTALAB SIMULATOR INITIALIZED")
        logger.warning("NO PHYSICAL EEG DEVICE WILL BE USED")
        logger.warning("SIMULATED RECORDINGS MUST NOT BE USED AS CLINICAL DATA")
        logger.warning("====================================================")

        self.connected = False
        self.recording = False
        self.device: Optional[MentalabDevice] = None

        self.recording_id: Optional[str] = None
        self.recording_started_at: Optional[str] = None
        self.recording_stopped_at: Optional[str] = None
        self.recording_file_prefix: Optional[Path] = None
        self.recording_file: Optional[Path] = None
        self.recording_error: Optional[str] = None
        self.recording_task: Optional[asyncio.Task] = None
        self._stop_event: Optional[threading.Event] = None

        self._live_lock = threading.Lock()
        self._live_channels = [
            deque(maxlen=LIVE_BUFFER_SIZE)
            for _ in range(SIMULATED_CHANNEL_COUNT)
        ]
        self._live_sample_index = 0
        self._live_updated_at: Optional[str] = None

    # ========================================================
    # STATUS
    # ========================================================

    def get_status(self):
        return {
            "connected": self.connected,
            "recording": self.recording,
            "device": self.device,
        }

    def get_recording_status(self):
        return {
            "recording": self.recording,
            "recordingId": self.recording_id,
            "startedAt": self.recording_started_at,
            "stoppedAt": self.recording_stopped_at,
            "filePrefix": (
                str(self.recording_file_prefix)
                if self.recording_file_prefix
                else None
            ),
            "files": self._find_recording_files(),
            "error": self.recording_error,
        }

    def get_live_data(self):
        with self._live_lock:
            channels = [
                list(channel_buffer)
                for channel_buffer in self._live_channels
            ]

            sample_index = self._live_sample_index
            updated_at = self._live_updated_at

        channel_payload = []

        for index, samples in enumerate(channels):
            quality = self._calculate_signal_quality(samples)

            channel_payload.append({
                "channel": index + 1,
                "samples": samples,
                "quality": quality,
            })

        return {
            "ok": True,
            "streaming": self.recording,
            "simulated": True,
            "samplingRate": SIMULATED_SAMPLING_RATE,
            "channelCount": SIMULATED_CHANNEL_COUNT,
            "windowSeconds": LIVE_WINDOW_SECONDS,
            "sampleIndex": sample_index,
            "updatedAt": updated_at,
            "channels": channel_payload,
        }

    # ========================================================
    # CONNECTION
    # ========================================================

    async def connect(self) -> MentalabDevice:
        logger.info("Simulator connection requested.")

        if self.connected and self.device is not None:
            return self.device

        await asyncio.sleep(0.75)

        self.device = MentalabDevice(
            name=SIMULATED_DEVICE_NAME,
            model=SIMULATED_MODEL,
            channelCount=SIMULATED_CHANNEL_COUNT,
            samplingRate=SIMULATED_SAMPLING_RATE,
            batteryPercent=SIMULATED_BATTERY_PERCENT,
            simulated=True,
        )

        self.connected = True

        logger.warning(
            "SIMULATED DEVICE CONNECTED: %s",
            SIMULATED_DEVICE_NAME,
        )

        return self.device

    # ========================================================
    # DISCONNECT
    # ========================================================

    async def disconnect(self) -> None:
        logger.info("Simulator disconnect requested.")

        if self.recording:
            raise RuntimeError(
                "Stop the active recording before disconnecting."
            )

        self.connected = False
        self.device = None
        self._clear_live_buffer()

        logger.info("Simulated device disconnected.")

    # ========================================================
    # RECORDING START
    # ========================================================

    async def start_recording(self) -> dict:
        logger.info("Simulator recording start requested.")

        if not self.connected:
            raise RuntimeError(
                "Simulated Mentalab device is not connected."
            )

        if self.recording:
            raise RuntimeError(
                "A simulated Mentalab recording is already active."
            )

        recording_id = str(uuid.uuid4())

        timestamp = datetime.now(timezone.utc).strftime(
            "%Y%m%d_%H%M%S"
        )

        filename = (
            f"SIMULATED_mentalab_{timestamp}_{recording_id[:8]}"
        )

        file_prefix = RECORDINGS_DIR / filename
        csv_file = Path(f"{file_prefix}.csv")

        self.recording_id = recording_id
        self.recording_started_at = datetime.now(timezone.utc).isoformat()
        self.recording_stopped_at = None
        self.recording_file_prefix = file_prefix
        self.recording_file = csv_file
        self.recording_error = None
        self._stop_event = threading.Event()

        self._clear_live_buffer()
        self.recording = True

        logger.warning("SIMULATED EEG RECORDING STARTED")
        logger.info("Recording ID: %s", recording_id)
        logger.info("Synthetic EEG output: %s", csv_file)

        self.recording_task = asyncio.create_task(
            asyncio.to_thread(
                self._generate_eeg,
                csv_file,
                self._stop_event,
            )
        )

        self.recording_task.add_done_callback(
            self._recording_task_finished
        )

        await asyncio.sleep(0.1)

        if self.recording_task.done():
            exception = self.recording_task.exception()

            if exception:
                self.recording = False
                raise exception

        return {
                "recordingId": self.recording_id,
                "startedAt": self.recording_started_at,
                "stoppedAt": self.recording_stopped_at,
                "files": files,
            }

    # ========================================================
    # SYNTHETIC EEG GENERATOR
    # ========================================================

    def _generate_eeg(
        self,
        csv_file: Path,
        stop_event: threading.Event,
    ):
        sample_rate = SIMULATED_SAMPLING_RATE
        channel_count = SIMULATED_CHANNEL_COUNT

        csv_file.parent.mkdir(parents=True, exist_ok=True)

        start_time = time.perf_counter()
        sample_index = 0

        with csv_file.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.writer(file)

            header = ["sample", "timestamp"]
            header.extend(
                f"ch_{channel + 1}"
                for channel in range(channel_count)
            )

            writer.writerow(header)

            while not stop_event.is_set():
                elapsed = sample_index / sample_rate
                wall_clock = datetime.now(timezone.utc).isoformat()

                values = [
                    self._synthetic_channel_value(elapsed, channel)
                    for channel in range(channel_count)
                ]

                row = [
                    sample_index,
                    wall_clock,
                    *[round(value, 6) for value in values],
                ]

                writer.writerow(row)
                self._append_live_sample(
                    sample_index,
                    wall_clock,
                    values,
                )

                sample_index += 1

                expected_time = (
                    start_time + sample_index / sample_rate
                )

                sleep_duration = (
                    expected_time - time.perf_counter()
                )

                if sleep_duration > 0:
                    time.sleep(sleep_duration)

        logger.info(
            "Synthetic EEG generator stopped after %s samples.",
            sample_index,
        )

    def _synthetic_channel_value(
        self,
        elapsed: float,
        channel: int,
    ) -> float:
        phase = channel * 0.35

        alpha = 20.0 * math.sin(
            2 * math.pi * 10.0 * elapsed + phase
        )

        theta = 8.0 * math.sin(
            2 * math.pi * 6.0 * elapsed + phase * 0.7
        )

        beta = 5.0 * math.sin(
            2 * math.pi * 18.0 * elapsed + phase * 1.2
        )

        noise = random.gauss(0.0, 3.0)

        return alpha + theta + beta + noise

    # ========================================================
    # LIVE BUFFER
    # ========================================================

    def _append_live_sample(
        self,
        sample_index: int,
        updated_at: str,
        values: list[float],
    ):
        with self._live_lock:
            for index, value in enumerate(values):
                self._live_channels[index].append(
                    round(float(value), 6)
                )

            self._live_sample_index = sample_index
            self._live_updated_at = updated_at

    def _clear_live_buffer(self):
        with self._live_lock:
            for channel_buffer in self._live_channels:
                channel_buffer.clear()

            self._live_sample_index = 0
            self._live_updated_at = None

    # ========================================================
    # TECHNICAL SIGNAL QUALITY
    # ========================================================

    def _calculate_signal_quality(
        self,
        samples: list[float],
    ):
        """
        Development-only acquisition quality indicator.

        This is NOT a clinical EEG score.

        The simulator normally produces GOOD quality. The calculation
        exists so the frontend/API contract can be completed before
        the real-device quality algorithm is introduced.
        """

        if len(samples) < 50:
            return {
                "state": "WAITING",
                "score": None,
                "rms": None,
                "peakToPeak": None,
                "standardDeviation": None,
            }

        mean_square = sum(
            sample * sample for sample in samples
        ) / len(samples)

        rms = math.sqrt(mean_square)
        peak_to_peak = max(samples) - min(samples)
        standard_deviation = pstdev(samples)

        # Simulator-only quality heuristic.
        if peak_to_peak < 1.0 or standard_deviation < 0.5:
            state = "POOR"
            score = 0.25
        elif peak_to_peak > 250.0 or standard_deviation > 80.0:
            state = "NOISY"
            score = 0.45
        else:
            state = "GOOD"
            score = 0.95

        return {
            "state": state,
            "score": score,
            "rms": round(rms, 3),
            "peakToPeak": round(peak_to_peak, 3),
            "standardDeviation": round(
                standard_deviation,
                3,
            ),
        }

    # ========================================================
    # RECORDING STOP
    # ========================================================

    async def stop_recording(self) -> dict:
        logger.info("Simulator recording stop requested.")

        if not self.recording:
            raise RuntimeError(
                "No simulated Mentalab recording is active."
            )

        if self._stop_event is None:
            raise RuntimeError(
                "Simulator recording stop event is missing."
            )

        self._stop_event.set()

        if self.recording_task:
            try:
                await asyncio.wait_for(
                    self.recording_task,
                    timeout=5,
                )
            except asyncio.TimeoutError as exc:
                self.recording_error = (
                    "Synthetic EEG generator did not stop in time."
                )
                raise RuntimeError(
                    self.recording_error
                ) from exc

        self.recording = False
        self.recording_stopped_at = (
            datetime.now(timezone.utc).isoformat()
        )

        files = self._find_recording_files()

        logger.warning("SIMULATED EEG RECORDING STOPPED")
        logger.info("Generated files: %s", files)

        return {
            "recordingId": self.recording_id,
            "files": files,
        }

    # ========================================================
    # TASK CALLBACK
    # ========================================================

    def _recording_task_finished(
        self,
        task: asyncio.Task,
    ):
        try:
            exception = task.exception()
        except asyncio.CancelledError:
            logger.warning(
                "Simulator recording task was cancelled."
            )
            return

        if exception:
            self.recording_error = str(exception)
            self.recording = False

            logger.error(
                "Synthetic EEG generator terminated with an error: %s",
                exception,
            )

    # ========================================================
    # FILE DISCOVERY
    # ========================================================

    def _find_recording_files(self) -> list[str]:
        if self.recording_file_prefix is None:
            return []

        parent = self.recording_file_prefix.parent
        prefix = self.recording_file_prefix.name

        files = sorted(parent.glob(f"{prefix}*"))

        return [
            str(file.resolve())
            for file in files
            if file.is_file()
        ]


simulated_mentalab_device_manager = (
    SimulatedMentalabDeviceManager()
)
# app/mentalab_device.py

import asyncio
import logging
import os
import threading
import time
import uuid

from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import explorepy

from dotenv import load_dotenv
from explorepy.explore import TOPICS

from .models import MentalabDevice


load_dotenv()

logger = logging.getLogger("mentalab.device")


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

RECORDINGS_DIR = BASE_DIR / "recordings"
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


DEVICE_NAME = os.getenv(
    "MENTALAB_DEVICE_NAME",
    "Explore_AABH",
)

DEFAULT_CHANNEL_COUNT = int(
    os.getenv(
        "MENTALAB_DEFAULT_CHANNELS",
        "8",
    )
)

DEFAULT_SAMPLING_RATE = int(
    os.getenv(
        "MENTALAB_DEFAULT_SAMPLING_RATE",
        "250",
    )
)

LIVE_WINDOW_SECONDS = float(
    os.getenv(
        "MENTALAB_LIVE_WINDOW_SECONDS",
        "2",
    )
)


# ============================================================
# DEVICE MANAGER
# ============================================================

class MentalabDeviceManager:

    def __init__(self):
        logger.info(
            "Initializing MentalabDeviceManager"
        )

        logger.info(
            "Configured device name: %s",
            DEVICE_NAME,
        )

        logger.info(
            "Configured default channels: %s",
            DEFAULT_CHANNEL_COUNT,
        )

        logger.info(
            "Configured default sampling rate: %s Hz",
            DEFAULT_SAMPLING_RATE,
        )

        logger.info(
            "Live EEG window: %s seconds",
            LIVE_WINDOW_SECONDS,
        )

        logger.info(
            "Recording directory: %s",
            RECORDINGS_DIR,
        )

        self.connected = False
        self.recording = False

        self.device: Optional[MentalabDevice] = None

        self.explorer: Optional[
            explorepy.Explore
        ] = None

        # ----------------------------------------------------
        # Recording state
        # ----------------------------------------------------

        self.recording_id: Optional[str] = None
        self.recording_started_at: Optional[str] = None
        self.recording_stopped_at: Optional[str] = None

        self.recording_file_prefix: Optional[
            Path
        ] = None

        self.recording_task: Optional[
            asyncio.Task
        ] = None

        self.recording_error: Optional[str] = None

        # ----------------------------------------------------
        # Live EEG state
        # ----------------------------------------------------

        self.live_window_seconds = (
            LIVE_WINDOW_SECONDS
        )

        self.live_buffer_size = max(
            1,
            int(
                DEFAULT_SAMPLING_RATE
                * LIVE_WINDOW_SECONDS
            ),
        )

        self.live_buffers = [
            deque(
                maxlen=self.live_buffer_size
            )
            for _ in range(
                DEFAULT_CHANNEL_COUNT
            )
        ]

        self.live_lock = threading.Lock()

        self.live_subscribed = False

        self.live_sample_index = 0

        self.live_updated_at: Optional[
            str
        ] = None

        self.live_error: Optional[str] = None

    # ========================================================
    # STATUS
    # ========================================================

    def get_status(self):
        logger.debug(
            "Device status requested: "
            "connected=%s recording=%s device=%s",
            self.connected,
            self.recording,
            self.device.name if self.device else None,
        )

        return {
            "connected": self.connected,
            "recording": self.recording,
            "device": self.device,
        }

    def get_recording_status(self):
        files = self._find_recording_files()

        logger.debug(
            "Recording status requested: "
            "recording=%s id=%s files=%s error=%s",
            self.recording,
            self.recording_id,
            len(files),
            self.recording_error,
        )

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
            "files": files,
            "error": self.recording_error,
        }

    # ========================================================
    # CONNECTION
    # ========================================================

    async def connect(
        self,
    ) -> MentalabDevice:

        logger.info(
            "CONNECT requested for device %s",
            DEVICE_NAME,
        )

        if (
            self.connected
            and self.device is not None
        ):
            logger.warning(
                "Connect requested while device "
                "already marked connected."
            )

            return self.device

        start_time = time.monotonic()

        try:
            logger.debug(
                "Creating explorepy.Explore instance..."
            )

            explorer = explorepy.Explore()

            logger.info(
                "ExplorePy instance created successfully."
            )

            logger.info(
                "Attempting ExplorePy connection to %s",
                DEVICE_NAME,
            )

            logger.info(
                "IMPORTANT: Device must be powered on, "
                "advertising, and not actively connected "
                "to Explore Desktop."
            )

            # ExplorePy connection is blocking.
            await asyncio.to_thread(
                explorer.connect,
                device_name=DEVICE_NAME,
            )

            elapsed = (
                time.monotonic()
                - start_time
            )

            logger.info(
                "ExplorePy connection returned successfully "
                "after %.2f seconds.",
                elapsed,
            )

            self.explorer = explorer
            self.connected = True

            self.device = MentalabDevice(
                name=DEVICE_NAME,
                model=None,
                channelCount=DEFAULT_CHANNEL_COUNT,
                samplingRate=DEFAULT_SAMPLING_RATE,
                batteryPercent=None,
            )

            self._reset_live_data()

            try:
                self._subscribe_live_eeg()

            except Exception:
                logger.exception(
                    "Device connected, but live EEG "
                    "subscription could not be started."
                )

                try:
                    await asyncio.to_thread(
                        explorer.disconnect
                    )
                except Exception:
                    logger.exception(
                        "Failed to disconnect after "
                        "live EEG subscription failure."
                    )

                self._clear_connection_state()

                raise

            logger.info(
                "DEVICE CONNECTED: "
                "name=%s channels=%s samplingRate=%s",
                self.device.name,
                self.device.channelCount,
                self.device.samplingRate,
            )

            return self.device

        except Exception as exc:
            elapsed = (
                time.monotonic()
                - start_time
            )

            logger.exception(
                "FAILED to connect to %s "
                "after %.2f seconds. "
                "Exception type=%s message=%s",
                DEVICE_NAME,
                elapsed,
                type(exc).__name__,
                str(exc),
            )

            self._clear_connection_state()

            raise RuntimeError(
                f"Unable to connect to "
                f"{DEVICE_NAME}: {exc}"
            ) from exc

    # ========================================================
    # LIVE EEG SUBSCRIPTION
    # ========================================================

    def _subscribe_live_eeg(
        self,
    ) -> None:

        if self.explorer is None:
            raise RuntimeError(
                "Cannot subscribe to live EEG because "
                "ExplorePy is not connected."
            )

        if self.explorer.stream_processor is None:
            raise RuntimeError(
                "ExplorePy stream processor is not "
                "available after connection."
            )

        if self.live_subscribed:
            logger.debug(
                "Live EEG subscriber is already active."
            )
            return

        logger.info(
            "Subscribing Compass live monitor "
            "to ExplorePy raw_ExG stream."
        )

        self.explorer.stream_processor.subscribe(
            callback=self._handle_exg_packet,
            topic=TOPICS.raw_ExG,
        )

        self.live_subscribed = True
        self.live_error = None

        logger.info(
            "Live raw_ExG subscription started."
        )

    def _unsubscribe_live_eeg(
        self,
    ) -> None:

        explorer = self.explorer

        if (
            explorer is None
            or explorer.stream_processor is None
            or not self.live_subscribed
        ):
            self.live_subscribed = False
            return

        logger.info(
            "Unsubscribing Compass live monitor "
            "from ExplorePy raw_ExG stream."
        )

        try:
            explorer.stream_processor.unsubscribe(
                callback=self._handle_exg_packet,
                topic=TOPICS.raw_ExG,
            )

        except Exception as exc:
            logger.exception(
                "Unable to unsubscribe live EEG "
                "callback: %s",
                exc,
            )

        finally:
            self.live_subscribed = False

    # ========================================================
    # LIVE EEG CALLBACK
    # ========================================================

    def _handle_exg_packet(
        self,
        packet: Any,
    ) -> None:
        """
        ExplorePy raw_ExG callback.

        ExplorePy 4.3.1 may dispatch either a single
        EEG packet or a list/tuple containing a batch
        of EEG packets.
        """

        try:
            packets = (
                packet
                if isinstance(
                    packet,
                    (list, tuple),
                )
                else [packet]
            )

            for eeg_packet in packets:
                self._append_eeg_packet(
                    eeg_packet
                )

        except Exception as exc:
            self.live_error = str(exc)

            logger.exception(
                "Failed to process raw EEG packet: %s",
                exc,
            )

    def _append_eeg_packet(
        self,
        packet: Any,
    ) -> None:

        data = getattr(
            packet,
            "data",
            None,
        )

        if data is None:
            try:
                _, data = packet.get_data()
            except Exception:
                logger.warning(
                    "Received raw_ExG packet without "
                    "readable EEG data."
                )
                return

        if data is None:
            return

        # ExplorePy EEG data is channel-major:
        #
        #     channels x samples
        #
        # Convert through basic sequence operations
        # so this bridge does not depend on NumPy
        # outside ExplorePy itself.

        try:
            channel_count = len(data)
        except TypeError:
            logger.warning(
                "Received EEG data with unexpected "
                "shape/type: %s",
                type(data).__name__,
            )
            return

        if channel_count <= 0:
            return

        usable_channels = min(
            channel_count,
            DEFAULT_CHANNEL_COUNT,
        )

        samples_added = 0

        with self.live_lock:
            for channel_index in range(
                usable_channels
            ):
                channel_data = data[
                    channel_index
                ]

                try:
                    values = (
                        channel_data.tolist()
                        if hasattr(
                            channel_data,
                            "tolist",
                        )
                        else list(channel_data)
                    )
                except TypeError:
                    values = [
                        channel_data
                    ]

                for value in values:
                    try:
                        self.live_buffers[
                            channel_index
                        ].append(
                            float(value)
                        )
                    except (
                        TypeError,
                        ValueError,
                    ):
                        continue

                if channel_index == 0:
                    samples_added = len(values)

            self.live_sample_index += (
                samples_added
            )

            self.live_updated_at = (
                datetime.now(
                    timezone.utc
                ).isoformat()
            )

            self.live_error = None

    # ========================================================
    # LIVE EEG API DATA
    # ========================================================

    def get_live_data(
        self,
    ) -> dict:

        with self.live_lock:
            channels = []

            for channel_index, buffer in enumerate(
                self.live_buffers
            ):
                samples = list(buffer)

                channels.append(
                    {
                        "channel":
                            channel_index + 1,

                        "samples":
                            samples,

                        # Real-device clinical signal-quality
                        # thresholds are intentionally not
                        # inferred from simulator thresholds.
                        "quality": {
                            "state": (
                                "WAITING"
                                if not samples
                                else "GOOD"
                            ),
                            "score": None,
                            "rms": None,
                            "peakToPeak": None,
                            "standardDeviation": None,
                        },
                    }
                )

            return {
                "ok": True,
                "streaming": (
                    self.connected
                    and self.live_subscribed
                ),
                "simulated": False,
                "samplingRate":
                    DEFAULT_SAMPLING_RATE,
                "channelCount":
                    DEFAULT_CHANNEL_COUNT,
                "windowSeconds":
                    self.live_window_seconds,
                "sampleIndex":
                    self.live_sample_index,
                "updatedAt":
                    self.live_updated_at,
                "channels":
                    channels,
            }

    # ========================================================
    # DISCONNECT
    # ========================================================

    async def disconnect(
        self,
    ) -> None:

        logger.info(
            "DISCONNECT requested."
        )

        if self.recording:
            logger.warning(
                "Disconnect rejected because "
                "recording is active."
            )

            raise RuntimeError(
                "Stop the active recording "
                "before disconnecting."
            )

        if self.explorer is None:
            logger.warning(
                "Disconnect requested but no "
                "ExplorePy instance exists."
            )

            self._clear_connection_state()

            return

        try:
            self._unsubscribe_live_eeg()

            logger.info(
                "Calling ExplorePy disconnect..."
            )

            await asyncio.to_thread(
                self.explorer.disconnect
            )

            logger.info(
                "ExplorePy disconnect completed."
            )

        except Exception as exc:
            logger.exception(
                "Error while disconnecting "
                "Mentalab device: %s",
                exc,
            )

            raise RuntimeError(
                f"Unable to disconnect "
                f"Mentalab device: {exc}"
            ) from exc

        finally:
            self._clear_connection_state()

    # ========================================================
    # RECORDING START
    # ========================================================

    async def start_recording(
        self,
    ) -> dict:

        logger.info(
            "START RECORDING requested."
        )

        if (
            not self.connected
            or self.explorer is None
        ):
            logger.error(
                "Recording rejected: "
                "device is not connected."
            )

            raise RuntimeError(
                "Mentalab device is not connected."
            )

        if self.recording:
            logger.warning(
                "Recording start rejected: "
                "recording already active."
            )

            raise RuntimeError(
                "A Mentalab recording "
                "is already active."
            )

        self.recording_error = None

        recording_id = str(
            uuid.uuid4()
        )

        timestamp = datetime.now(
            timezone.utc
        ).strftime(
            "%Y%m%d_%H%M%S"
        )

        filename = (
            f"mentalab_"
            f"{DEVICE_NAME}_"
            f"{timestamp}_"
            f"{recording_id[:8]}"
        )

        file_prefix = (
            RECORDINGS_DIR / filename
        )

        self.recording_id = recording_id

        self.recording_started_at = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        self.recording_stopped_at = None

        self.recording_file_prefix = (
            file_prefix
        )

        logger.info(
            "Recording session created."
        )

        logger.info(
            "recording_id=%s",
            recording_id,
        )

        logger.info(
            "file_prefix=%s",
            file_prefix,
        )

        try:
            self.recording = True

            logger.info(
                "Starting ExplorePy recording "
                "in background thread."
            )

            self.recording_task = (
                asyncio.create_task(
                    asyncio.to_thread(
                        self._run_recording,
                        str(file_prefix),
                    )
                )
            )

            self.recording_task.add_done_callback(
                self._recording_task_finished
            )

            # Give the background thread a brief
            # opportunity to fail immediately.
            await asyncio.sleep(0.25)

            if self.recording_task.done():
                exception = (
                    self.recording_task.exception()
                )

                if exception:
                    raise exception

            logger.info(
                "Recording background task started."
            )

            return {
                "recordingId":
                    recording_id,

                "startedAt":
                    self.recording_started_at,
            }

        except Exception as exc:
            self.recording = False

            self.recording_error = str(exc)

            logger.exception(
                "Failed to start recording: %s",
                exc,
            )

            raise RuntimeError(
                f"Unable to start Mentalab "
                f"recording: {exc}"
            ) from exc

    # ========================================================
    # RECORDING WORKER
    # ========================================================

    def _run_recording(
        self,
        file_prefix: str,
    ):
        """
        Runs inside a background thread.

        ExplorePy's record_data call is intentionally
        isolated from FastAPI's event loop.
        """

        logger.info(
            "[RECORDING THREAD] Started."
        )

        logger.info(
            "[RECORDING THREAD] "
            "file_prefix=%s",
            file_prefix,
        )

        if self.explorer is None:
            raise RuntimeError(
                "ExplorePy instance disappeared "
                "before recording started."
            )

        try:
            logger.info(
                "[RECORDING THREAD] "
                "Calling ExplorePy record_data()."
            )

            self.explorer.record_data(
                file_name=file_prefix,
                file_type="csv",
            )

            logger.info(
                "[RECORDING THREAD] "
                "ExplorePy record_data() returned."
            )

        except Exception as exc:
            logger.exception(
                "[RECORDING THREAD] "
                "ExplorePy recording failed: %s",
                exc,
            )

            raise

    # ========================================================
    # RECORDING STOP
    # ========================================================

    async def stop_recording(
        self,
    ) -> dict:

        logger.info(
            "STOP RECORDING requested."
        )

        if not self.recording:
            logger.warning(
                "Stop rejected because no "
                "recording is active."
            )

            raise RuntimeError(
                "No Mentalab recording is active."
            )

        if self.explorer is None:
            logger.error(
                "Recording marked active but "
                "ExplorePy instance is missing."
            )

            raise RuntimeError(
                "Mentalab connection was lost."
            )

        try:
            logger.info(
                "Calling ExplorePy stop_recording()..."
            )

            await asyncio.to_thread(
                self.explorer.stop_recording
            )

            logger.info(
                "ExplorePy stop_recording() returned."
            )

            if self.recording_task:
                logger.info(
                    "Waiting for background "
                    "recording task to finalize..."
                )

                try:
                    await asyncio.wait_for(
                        self.recording_task,
                        timeout=10,
                    )

                except asyncio.TimeoutError:
                    logger.error(
                        "Recording task did not "
                        "finalize within 10 seconds."
                    )

                    raise RuntimeError(
                        "Mentalab recording did not "
                        "finalize within the expected "
                        "time."
                    )

            self.recording = False

            self.recording_stopped_at = (
                datetime.now(
                    timezone.utc
                ).isoformat()
            )

            files = (
                self._find_recording_files()
            )

            logger.info(
                "Recording stopped successfully."
            )

            logger.info(
                "Generated %s recording files.",
                len(files),
            )

            for file in files:
                logger.info(
                    "Generated file: %s",
                    file,
                )

            if not files:
                logger.warning(
                    "ExplorePy stopped without any "
                    "matching recording files being "
                    "detected."
                )

            return {
                "recordingId":
                    self.recording_id,

                "files":
                    files,
            }

        except Exception as exc:
            self.recording_error = str(exc)

            logger.exception(
                "Failed to stop recording: %s",
                exc,
            )

            raise RuntimeError(
                f"Unable to stop Mentalab "
                f"recording: {exc}"
            ) from exc

    # ========================================================
    # RECORDING CALLBACK
    # ========================================================

    def _recording_task_finished(
        self,
        task: asyncio.Task,
    ):
        try:
            exception = task.exception()

        except asyncio.CancelledError:
            logger.warning(
                "Recording task was cancelled."
            )
            return

        if exception:
            self.recording_error = (
                str(exception)
            )

            self.recording = False

            logger.error(
                "Recording background task "
                "terminated with error: %s",
                exception,
            )

        else:
            logger.info(
                "Recording background task "
                "finished normally."
            )

    # ========================================================
    # FILE DISCOVERY
    # ========================================================

    def _find_recording_files(
        self,
    ) -> list[str]:

        if (
            self.recording_file_prefix
            is None
        ):
            return []

        parent = (
            self.recording_file_prefix.parent
        )

        prefix = (
            self.recording_file_prefix.name
        )

        files = sorted(
            parent.glob(
                f"{prefix}*"
            )
        )

        return [
            str(file.resolve())
            for file in files
            if file.is_file()
        ]

    # ========================================================
    # LIVE DATA HELPERS
    # ========================================================

    def _reset_live_data(
        self,
    ) -> None:

        with self.live_lock:
            for buffer in self.live_buffers:
                buffer.clear()

            self.live_sample_index = 0
            self.live_updated_at = None
            self.live_error = None

    # ========================================================
    # CONNECTION HELPERS
    # ========================================================

    def _clear_connection_state(
        self,
    ) -> None:

        logger.debug(
            "Clearing Mentalab "
            "connection state."
        )

        self.explorer = None
        self.device = None

        self.connected = False
        self.recording = False
        self.live_subscribed = False

        self._reset_live_data()


mentalab_device_manager = (
    MentalabDeviceManager()
)
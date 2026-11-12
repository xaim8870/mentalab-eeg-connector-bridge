# app/main.py

import logging
import os
import secrets
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import ( CORSMiddleware, )
from .logging_config import ( configure_logging, )
from .device_manager import ( mentalab_device_manager, )
from .models import ( HealthResponse, DeviceStatusResponse, DeviceConnectResponse, ActionResponse, RecordingStartResponse, RecordingStatusResponse, )
from fastapi.responses import FileResponse


# ============================================================
# LOGGING
# ============================================================

configure_logging()

logger = logging.getLogger(
    "mentalab.api"
)


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="Mentalab EEG Bridge",
    version="0.3.0",
)


app.add_middleware(
    CORSMiddleware,

    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://zeamhealthprovidersdashboard.netlify.app"   ],

    allow_credentials=False,

    allow_methods=[
        "GET",
        "POST",
        "OPTIONS",
    ],

    allow_headers=["*"],
)


# ============================================================
# REQUEST LOGGING
# ============================================================

@app.middleware("http")
async def log_requests(
    request: Request,
    call_next,
):
    logger.info(
        "HTTP %s %s",
        request.method,
        request.url.path,
    )

    try:
        response = await call_next(
            request
        )

        logger.info(
            "HTTP %s %s -> %s",
            request.method,
            request.url.path,
            response.status_code,
        )

        return response

    except Exception:
        logger.exception(
            "Unhandled API error: %s %s",
            request.method,
            request.url.path,
        )

        raise


# ============================================================
# ROOT
# ============================================================

@app.get("/")
async def root():
    return {
        "ok": True,
        "service": "mentalab-bridge",
        "version": "0.3.0",
    }
# ============================================================
# HEALTH
# ============================================================

@app.get(
    "/api/health",
    response_model=HealthResponse,
)
async def health():
    return HealthResponse(
        ok=True,
        service="mentalab-bridge",
        version="0.3.0",
    )

# ============================================================
# DEVICE STATUS
# ============================================================

@app.get(
    "/api/device/status",
    response_model=DeviceStatusResponse,
)
async def device_status():

    status = (
        mentalab_device_manager
        .get_status()
    )

    return DeviceStatusResponse(
        ok=True,

        connected=status[
            "connected"
        ],

        recording=status[
            "recording"
        ],

        device=status[
            "device"
        ],
    )

def _history_token_valid(candidate: str | None) -> bool:
    expected = os.getenv("MENTALAB_HISTORY_API_TOKEN", "")
    return len(expected) >= 32 and bool(candidate) and secrets.compare_digest(candidate, expected)


@app.get("/api/recordings")
async def list_recordings(
    x_mentalab_history_token: str | None = Header(default=None),
):
    if not os.getenv("MENTALAB_HISTORY_API_TOKEN"):
        raise HTTPException(status_code=503, detail="Recording history is not configured")
    if not _history_token_valid(x_mentalab_history_token):
        raise HTTPException(status_code=403, detail="Recording history access denied")
    return {"ok": True, "recordings": mentalab_device_manager.get_recording_history()}


@app.get("/api/recording/{recording_id}/download")
async def download_recording_file(
    recording_id: str,
    filename: str,
    x_mentalab_history_token: str | None = Header(default=None),
):
    try:
        file_path = (
            mentalab_device_manager.get_recording_file(
                recording_id,
                filename,
                allow_history=_history_token_valid(x_mentalab_history_token),
            )
        )

        return FileResponse(
            path=file_path,
            filename=file_path.name,
            media_type="text/csv",
        )

    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid recording filename.",
        )

    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Recording file not found.",
        )

# ============================================================
# DEVICE CONNECT
# ============================================================

@app.post(
    "/api/device/connect",
    response_model=DeviceConnectResponse,
)
async def connect_device():

    logger.info(
        "API device connection requested."
    )

    try:
        device = (
            await mentalab_device_manager
            .connect()
        )

        return DeviceConnectResponse(
            ok=True,
            device=device,
        )

    except Exception as exc:
        logger.exception(
            "API device connection failed."
        )

        raise HTTPException(
            status_code=503,
            detail=str(exc),
        )


# ============================================================
# DEVICE DISCONNECT
# ============================================================

@app.post(
    "/api/device/disconnect",
    response_model=ActionResponse,
)
async def disconnect_device():

    try:
        await (
            mentalab_device_manager
            .disconnect()
        )

        return ActionResponse(
            ok=True,
            message=(
                "Mentalab device disconnected."
            ),
        )

    except Exception as exc:
        logger.exception(
            "API disconnect failed."
        )

        raise HTTPException(
            status_code=409,
            detail=str(exc),
        )


# ============================================================
# RECORDING START
# ============================================================

@app.post(
    "/api/recording/start",
    response_model=RecordingStartResponse,
)
async def start_recording():

    logger.info(
        "API recording start requested."
    )

    try:
        result = await (
            mentalab_device_manager
            .start_recording()
        )

        return RecordingStartResponse(
            ok=True,

            recordingId=result[
                "recordingId"
            ],

            startedAt=result[
                "startedAt"
            ],

            message=(
                "Mentalab recording started."
            ),
        )

    except Exception as exc:
        logger.exception(
            "API recording start failed."
        )

        raise HTTPException(
            status_code=409,
            detail=str(exc),
        )


# ============================================================
# RECORDING STOP
# ============================================================

@app.post(
    "/api/recording/stop",
    response_model=ActionResponse,
)
async def stop_recording():

    logger.info(
        "API recording stop requested."
    )

    try:
        result = await (
            mentalab_device_manager
            .stop_recording()
        )

        logger.info(
            "Recording completed. "
            "recording_id=%s files=%s",
            result.get(
                "recordingId"
            ),
            len(
                result.get(
                    "files",
                    [],
                )
            ),
        )

        return ActionResponse(
            ok=True,
            message=(
                "Mentalab recording "
                "stopped successfully."
            ),
        )

    except Exception as exc:
        logger.exception(
            "API recording stop failed."
        )

        raise HTTPException(
            status_code=409,
            detail=str(exc),
        )


# ============================================================
# RECORDING STATUS
# ============================================================

@app.get(
    "/api/recording/status",
    response_model=RecordingStatusResponse,
)
async def recording_status():

    result = (
        mentalab_device_manager
        .get_recording_status()
    )

    return RecordingStatusResponse(
        ok=True,

        recording=result[
            "recording"
        ],

        recordingId=result[
            "recordingId"
        ],

        startedAt=result[
            "startedAt"
        ],

        stoppedAt=result[
            "stoppedAt"
        ],

        filePrefix=result[
            "filePrefix"
        ],

        files=result[
            "files"
        ],

        error=result[
            "error"
        ],
    )

# ============================================================
# LIVE EEG
# ============================================================

@app.get("/api/eeg/live")
async def live_eeg():
    try:
        return mentalab_device_manager.get_live_data()

    except AttributeError:
        raise HTTPException(
            status_code=501,
            detail=(
                "Live EEG streaming is not implemented "
                "for the active Mentalab device mode."
            ),
        )

    except Exception as exc:
        logger.exception(
            "Unable to retrieve live EEG data."
        )

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )
# app/models.py

from typing import List, Optional

from pydantic import BaseModel, Field


class MentalabDevice(BaseModel):
    name: str
    model: Optional[str] = None
    channelCount: int
    samplingRate: int
    batteryPercent: Optional[int] = None

    # True only when the development simulator is being used.
    simulated: bool = False


class HealthResponse(BaseModel):
    ok: bool
    service: str
    version: str


class DeviceStatusResponse(BaseModel):
    ok: bool
    connected: bool
    recording: bool
    device: Optional[MentalabDevice] = None


class DeviceConnectResponse(BaseModel):
    ok: bool
    device: MentalabDevice


class ActionResponse(BaseModel):
    ok: bool
    message: Optional[str] = None


class RecordingStartResponse(BaseModel):
    ok: bool
    recordingId: str
    startedAt: str
    message: Optional[str] = None


class RecordingStatusResponse(BaseModel):
    ok: bool

    recording: bool

    recordingId: Optional[str] = None

    startedAt: Optional[str] = None
    stoppedAt: Optional[str] = None

    filePrefix: Optional[str] = None

    files: List[str] = Field(
        default_factory=list
    )

    error: Optional[str] = None
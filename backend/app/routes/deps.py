from fastapi import Request

from ..config import Settings
from ..hooks import Hooks
from ..jobs import JobManager
from ..ollama import OllamaClient
from ..whisper_manager import WhisperManager


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_whisper(request: Request) -> WhisperManager:
    return request.app.state.whisper


def get_ollama(request: Request) -> OllamaClient:
    return request.app.state.ollama


def get_jobs(request: Request) -> JobManager:
    return request.app.state.jobs


def get_hooks(request: Request) -> Hooks:
    return request.app.state.hooks

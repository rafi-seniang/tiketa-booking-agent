"""How the chat feature is reached per request: the service built at startup, then a controller around it."""

from typing import Annotated

from fastapi import Depends

from app.features.chat.controller import ChatController
from app.features.chat.service import ChatService
from app.platform.dependencies import get_resources
from app.platform.resources import Resources


def get_chat_service(resources: Annotated[Resources, Depends(get_resources)]) -> ChatService:
    return resources.chat


def get_chat_controller(service: Annotated[ChatService, Depends(get_chat_service)]) -> ChatController:
    return ChatController(service)

"""How the chat feature is reached per request: the service built at startup, then a controller around it."""

from typing import Annotated

from fastapi import Depends

from app.core.dependencies import get_resources
from app.core.lifespan import Resources
from app.features.chat.controller import ChatController
from app.features.chat.service import ChatService


def get_chat_service(resources: Annotated[Resources, Depends(get_resources)]) -> ChatService:
    return resources.chat


def get_chat_controller(service: Annotated[ChatService, Depends(get_chat_service)]) -> ChatController:
    return ChatController(service)

"""What the service says about itself."""

from pydantic import BaseModel


class ServiceMeta(BaseModel):
    id: str
    name: str
    summary: str
    version: str
    engine: str
    own_ui_path: str
    docs_path: str

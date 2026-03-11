"""
Minimal pydantic compatibility layer for this environment.
"""
from __future__ import annotations


class BaseModel:
    def __init__(self, **data):
        annotations = getattr(self.__class__, "__annotations__", {})
        for field_name in annotations:
            if field_name in data:
                value = data[field_name]
            else:
                value = getattr(self.__class__, field_name, None)
            setattr(self, field_name, value)

    def dict(self):
        return self.__dict__.copy()

    def model_dump(self):
        return self.__dict__.copy()

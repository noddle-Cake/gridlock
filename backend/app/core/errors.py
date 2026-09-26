"""Domain exceptions and their mapping to the shared JSON error shape.

Every error response looks like::

    {"error": {"code": str, "message": str, "field"?: str, "fields"?: [str],
               "detected_format"?: str}}
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class GridLockError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        fields: list[str] | None = None,
        detected_format: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.field = field
        self.fields = fields
        self.detected_format = detected_format

    def to_body(self) -> dict:
        err: dict = {"code": self.code, "message": self.message}
        if self.field is not None:
            err["field"] = self.field
        if self.fields is not None:
            err["fields"] = self.fields
        if self.detected_format is not None:
            err["detected_format"] = self.detected_format
        return {"error": err}


class UnsupportedFormatError(GridLockError):
    status_code = 415
    code = "unsupported_format"


class FileTooLargeError(GridLockError):
    status_code = 413
    code = "file_too_large"


class CorruptFileError(GridLockError):
    status_code = 422
    code = "unreadable_file"


class MissingMetadataError(GridLockError):
    status_code = 422
    code = "missing_metadata"


class TooManyUtilitiesError(GridLockError):
    status_code = 422
    code = "too_many_utilities"


class ExtractionFailedError(GridLockError):
    status_code = 502
    code = "extraction_failed"


class PairNotFoundError(GridLockError):
    status_code = 404
    code = "pair_not_found"


class PlanNotFoundError(GridLockError):
    status_code = 404
    code = "plan_not_found"


class ProjectNotFoundError(GridLockError):
    status_code = 404
    code = "project_not_found"


class BriefTimeoutError(GridLockError):
    status_code = 504
    code = "brief_timeout"


class BriefGenerationError(GridLockError):
    status_code = 502
    code = "brief_generation_failed"


class InvalidFieldError(GridLockError):
    status_code = 422
    code = "invalid_fields"


class InvalidParameterError(GridLockError):
    status_code = 422
    code = "invalid_parameters"


class InvalidExportError(GridLockError):
    status_code = 422
    code = "invalid_export"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(GridLockError)
    async def _handle(_: Request, exc: GridLockError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_body())

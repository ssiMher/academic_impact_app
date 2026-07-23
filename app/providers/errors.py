"""Provider error classification helpers."""

from app.schemas.provider import ProviderError, ProviderErrorCode


RETRYABLE_ERROR_CODES = {
    ProviderErrorCode.RATE_LIMITED,
    ProviderErrorCode.RATE_LIMIT,
    ProviderErrorCode.TIMEOUT,
    ProviderErrorCode.UPSTREAM_UNAVAILABLE,
    ProviderErrorCode.TRANSIENT_PROVIDER_ERROR,
    ProviderErrorCode.TRANSIENT_NETWORK_ERROR,
}


class ProviderException(Exception):
    def __init__(
        self,
        code: ProviderErrorCode,
        message: str,
        provider_name: str,
        *,
        raw_output_preview: str = "",
        parse_error: str = "",
        schema_error: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.provider_name = provider_name
        self.raw_output_preview = raw_output_preview
        self.parse_error = parse_error
        self.schema_error = schema_error

    def to_error(self) -> ProviderError:
        return ProviderError(
            provider_name=self.provider_name,
            code=self.code,
            message=self.message,
            is_retryable=self.code in RETRYABLE_ERROR_CODES,
        )

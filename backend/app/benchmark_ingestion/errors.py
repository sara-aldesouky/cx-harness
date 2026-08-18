"""Structured failures raised by benchmark analytics ingestion."""


class BenchmarkIngestionError(RuntimeError):
    code = "ingestion_error"


class IngestionValidationError(BenchmarkIngestionError):
    code = "validation_error"


class IngestionSanitizationError(BenchmarkIngestionError):
    code = "sanitization_error"


class IngestionConflictError(BenchmarkIngestionError):
    code = "identity_conflict"


class IngestionLifecycleError(BenchmarkIngestionError):
    code = "lifecycle_error"


class IngestionRepositoryError(BenchmarkIngestionError):
    code = "repository_failure"


class IngestionTransactionError(BenchmarkIngestionError):
    code = "transaction_failure"


class UnsupportedArtifactError(BenchmarkIngestionError):
    code = "unsupported_artifact"


class IngestionPricingError(BenchmarkIngestionError):
    code = "pricing_error"


class IncompleteRunError(BenchmarkIngestionError):
    code = "incomplete_run"

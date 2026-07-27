"""Stable presentation-layer failures."""


class BenchmarkPresentationError(RuntimeError):
    code = "report_generation_failed"
    status_code = 500
    public_message = "The benchmark report could not be generated."

    def __init__(self, details: tuple[str, ...] = ()):
        super().__init__(self.public_message)
        self.details = details


class InvalidScoringPolicyError(BenchmarkPresentationError):
    code = "invalid_scoring_policy"
    status_code = 400
    public_message = "The requested scoring policy is not available."


class ExportGenerationError(BenchmarkPresentationError):
    code = "export_generation_failed"
    public_message = "The benchmark export could not be generated."

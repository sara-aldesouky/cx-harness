"""Structured read-only reporting failures."""

class BenchmarkReportingError(RuntimeError): pass
class RunNotFoundError(BenchmarkReportingError): pass
class IncompleteReportingDataError(BenchmarkReportingError): pass
class IncompatibleComparisonError(BenchmarkReportingError): pass
class ScoringPolicyError(BenchmarkReportingError): pass

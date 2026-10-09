"""The ingestion module (Mark IX).

Deliberately import-light: adapters/*.py will import ingestion.kinds.base, and importing
that runs this file first. B4 adds the public surface (run_ingestion, FetchRequest,
SourceSelector, Trigger, RunReport) with the runner imported inside the function.
"""

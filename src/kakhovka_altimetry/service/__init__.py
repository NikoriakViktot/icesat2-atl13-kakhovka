"""ATL13 ingest service: FastAPI + RQ worker, raw/processed parquet in S3, results in PostGIS.

    POST /jobs -> queue -> worker: discover -> acquire -> process -> load
"""

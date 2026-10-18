"""ETL configuration from environment variables.

Uses a plain namespace — not a Pydantic model — to keep ETL scripts
independent of the FastAPI dependency stack.
"""

import os

SAMPLE_MODE: bool = os.environ.get("SAMPLE_MODE", "false").lower() == "true"
SAMPLE_DATA_DIR: str = os.environ.get("SAMPLE_DATA_DIR", "data/sample")
DATABASE_URL_SYNC: str = os.environ.get("DATABASE_URL_SYNC", "")

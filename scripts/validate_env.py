"""Validate required environment variables before running the pipeline.

Stdlib only — no project imports. Called by `make full` before pipeline runs.
"""
import os
import sys


ALWAYS_REQUIRED = [
    "CORS_ORIGINS",
]

FULL_MODE_REQUIRED = [
    "DATABASE_URL",
    "DATABASE_URL_SYNC",
]


def validate_env() -> int:
    sample_mode = os.environ.get("SAMPLE_MODE", "false").lower() == "true"
    errors: list[str] = []

    for var in ALWAYS_REQUIRED:
        val = os.environ.get(var, "")
        if not val:
            errors.append(f"  Missing: {var}")

    if not sample_mode:
        for var in FULL_MODE_REQUIRED:
            val = os.environ.get(var, "")
            if not val:
                errors.append(f"  Missing: {var} (required when SAMPLE_MODE != 'true')")

    if errors:
        print("Environment validation FAILED:")
        for err in errors:
            print(err)
        print("\nCopy .env.example to .env and fill in the required values.")
        return 1

    cors = os.environ.get("CORS_ORIGINS", "")
    if cors.strip() == "*":
        print(
            "WARNING: CORS_ORIGINS='*' detected. "
            "The FastAPI app will raise ValueError at startup if allow_credentials=True is set. "
            "Set CORS_ORIGINS to explicit origins (e.g. 'http://localhost:5173')."
        )

    print("Environment OK")
    return 0


if __name__ == "__main__":
    sys.exit(validate_env())

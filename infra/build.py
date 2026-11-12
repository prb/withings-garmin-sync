"""Build script to create a standalone deployment zip for the AWS Lambda function."""

import os
import shutil
import subprocess
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = DIST_DIR / "lambda_build"
ZIP_PATH = DIST_DIR / "function.zip"

RUNTIME_DEPS = [
    "garminconnect>=0.3.20",
    "requests>=2.32.3",
    "boto3>=1.35.0",
]


def build_lambda_package() -> Path:
    """Bundle dependencies and withings_garmin_sync source code into dist/function.zip."""
    print("Building AWS Lambda deployment package...")

    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Install runtime dependencies using uv into build dir
    print("Installing runtime dependencies with uv...")
    cmd = [
        "uv",
        "pip",
        "install",
        "--target",
        str(BUILD_DIR),
        *RUNTIME_DEPS,
    ]
    subprocess.run(cmd, check=True)

    # 2. Copy withings_garmin_sync package code into build dir
    target_pkg = BUILD_DIR / "withings_garmin_sync"
    shutil.copytree(PROJECT_ROOT / "withings_garmin_sync", target_pkg)

    # Clean up __pycache__ and test artifacts
    for p in BUILD_DIR.rglob("__pycache__"):
        shutil.rmtree(p, ignore_errors=True)
    for p in BUILD_DIR.rglob("*.dist-info"):
        pass

    # 3. Create zip file
    print(f"Creating zip archive at {ZIP_PATH}...")
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(BUILD_DIR):
            for file in files:
                file_path = Path(root) / file
                archive_name = file_path.relative_to(BUILD_DIR)
                zf.write(file_path, archive_name)

    size_mb = ZIP_PATH.stat().st_size / (1024 * 1024)
    print(f"Deployment package created successfully: {ZIP_PATH} ({size_mb:.2f} MB)")
    return ZIP_PATH


if __name__ == "__main__":
    build_lambda_package()

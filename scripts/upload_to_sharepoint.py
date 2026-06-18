"""
SharePoint File Upload Script
"""

import argparse
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from office365.runtime.auth.authentication_context import AuthenticationContext
from office365.runtime.client_request_exception import ClientRequestException
from office365.sharepoint.client_context import ClientContext

# Redirect stdout and stderr to a log file
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "upload_to_sharepoint.log"

class LoggerWriter:
    def __init__(self, file_path):
        self.terminal = sys.stdout
        self.file_path = file_path
        self.new_line = True

    def write(self, message):
        self.terminal.write(message)
        try:
            with open(self.file_path, "a", encoding="utf-8") as f:
                for line in message.splitlines(keepends=True):
                    if self.new_line and line.strip():
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S ")
                        f.write(timestamp)
                    f.write(line)
                    self.new_line = line.endswith("\n")
        except Exception:
            pass

    def flush(self):
        self.terminal.flush()

sys.stdout = LoggerWriter(LOG_FILE)
sys.stderr = LoggerWriter(LOG_FILE)

load_dotenv(verbose=True)

# SharePoint Configurations
TENANT_ID = os.getenv("SHAREPOINT_TENANT_ID")
SITE_URL = os.getenv("SHAREPOINT_SITE_URL")
CLIENT_ID = os.getenv("SHAREPOINT_CLIENT_ID")
CLIENT_SECRET = os.getenv("SHAREPOINT_CLIENT_SECRET")
TARGET_FOLDER = os.getenv("SHAREPOINT_TARGET_FOLDER")

# Local Reports Directory
REPORTS_DIR = Path(__file__).parent.parent / "NDC_Reports"


def connect_sharepoint():
    """Authenticate and connect to SharePoint using client credentials."""
    if not all([SITE_URL, CLIENT_ID, CLIENT_SECRET]):
        raise ValueError(
            "Missing SharePoint configuration in environment variables. "
            "Please ensure SHAREPOINT_SITE_URL, SHAREPOINT_CLIENT_ID, and "
            "SHAREPOINT_CLIENT_SECRET are set in your .env file."
        )

    ctx_auth = AuthenticationContext(SITE_URL)
    
    if ctx_auth.acquire_token_for_app(CLIENT_ID, CLIENT_SECRET):
        ctx = ClientContext(SITE_URL, ctx_auth)
        return ctx
    else:
        error = ctx_auth.get_last_error()
        raise RuntimeError(f"Acquire app-only access token failed: {error}")


def get_latest_report(directory: Path, pattern: str = "*.xls") -> Path:
    """Find the most recently modified file matching the pattern in the directory."""
    if not directory.exists():
        raise FileNotFoundError(f"Local reports directory '{directory}' does not exist.")

    files = list(directory.glob(pattern))
    if not files:
        # Fallback to check for .xlsx if no .xls files are found
        files = list(directory.glob("*.xlsx"))
        if not files:
            raise FileNotFoundError(f"No files matching '{pattern}' or '*.xlsx' found in '{directory}'.")

    # Sort files by modification time (most recent first)
    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return files[0]


def upload_file_to_sharepoint(ctx: ClientContext, local_file_path: Path, target_folder_url: str):
    """Upload a local file to a target SharePoint folder."""
    file_name = local_file_path.name
    print(f"[UPLOAD] Uploading {file_name} to SharePoint...")

    # Get target folder and upload using absolute local path
    target_folder = ctx.web.get_folder_by_server_relative_url(target_folder_url)
    target_folder.files.upload(str(local_file_path))
    
    # Execute query to commit the upload
    ctx.execute_query()
    
    print(f"[SUCCESS] Upload completed: {file_name}")


def main():
    parser = argparse.ArgumentParser(description="Upload report files to SharePoint.")
    parser.add_argument(
        "--file",
        type=str,
        help="Path to a specific file to upload. If not specified, the latest report in NDC_Reports/ will be used.",
    )
    args = parser.parse_args()

    try:
        # Determine which file to upload
        if args.file:
            local_file = Path(args.file)
            if not local_file.exists():
                raise FileNotFoundError(f"Specified file not found: {args.file}")
        else:
            local_file = get_latest_report(REPORTS_DIR)

        # Connect to SharePoint
        ctx = connect_sharepoint()

        # Upload file
        upload_file_to_sharepoint(ctx, local_file, TARGET_FOLDER)

    except ValueError as e:
        print(f"\n[ERROR] Configuration Error: {e}")
    except FileNotFoundError as e:
        print(f"\n[ERROR] File Not Found: {e}")
    except PermissionError as e:
        print(f"\n[ERROR] Local Permission Error: {e}")
    except ClientRequestException as e:
        print(f"\n[ERROR] SharePoint API Error: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        print(f"\n[ERROR] Unexpected Error: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()

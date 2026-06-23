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

    def write(self, message):
        self.terminal.write(message)
        try:
            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write(message)
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

# Local Reports Directories
UPLOADS_DIR = Path(__file__).parent.parent / "uploads"
NDC_REPORTS_DIR = UPLOADS_DIR / "NDC_Reports"
FF_REPORTS_DIR = UPLOADS_DIR / "FF_Reports"

# Ensure local directories exist
NDC_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
FF_REPORTS_DIR.mkdir(parents=True, exist_ok=True)

def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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


def ensure_folder_exists(ctx: ClientContext, folder_relative_url: str):
    """Ensure a SharePoint folder path exists, creating subfolders one-by-one if needed."""
    url = "/" + folder_relative_url.strip("/")
    parts = [p for p in url.split("/") if p]
    
    current_path = ""
    for idx, part in enumerate(parts):
        if idx == 0:
            current_path = "/" + part
            continue
        current_path = f"{current_path}/{part}"
        
        # Skip checking the site prefix (e.g. /sites/AGEL-Automation/Shared Documents)
        if idx < 3:
            continue
            
        try:
            folder = ctx.web.get_folder_by_server_relative_url(current_path)
            ctx.load(folder)
            ctx.execute_query()
        except Exception:
            parent_path = current_path.rsplit("/", 1)[0]
            try:
                parent_folder = ctx.web.get_folder_by_server_relative_url(parent_path)
                parent_folder.folders.add(part)
                ctx.execute_query()
            except Exception as ex:
                raise RuntimeError(f"Failed to create folder '{part}' in '{parent_path}': {ex}")


def get_latest_report(directory: Path, pattern: str = "*.xls") -> Path:
    """Find the most recently modified file matching the pattern in the directory."""
    if not directory.exists():
        raise FileNotFoundError(f"Local reports directory '{directory}' does not exist.")

    files = list(directory.glob(pattern))
    if not files:
        files = list(directory.glob("*.xlsx"))
        if not files:
            raise FileNotFoundError(f"No files matching '{pattern}' or '*.xlsx' found in '{directory}'.")

    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return files[0]


def upload_file_to_sharepoint(ctx: ClientContext, local_file_path: Path, target_folder_url: str):
    """Upload a local file to a target SharePoint folder."""
    file_name = local_file_path.name

    ensure_folder_exists(ctx, target_folder_url)

    target_folder = ctx.web.get_folder_by_server_relative_url(target_folder_url)
    target_folder.files.upload(str(local_file_path))
    ctx.execute_query()
    
    print(f"[{ts()}] Uploaded: {file_name}")


def cleanup_old_ndc_reports(latest_file: Path):
    """Delete all files in uploads/NDC_Reports except for the latest_file."""
    try:
        for f in NDC_REPORTS_DIR.iterdir():
            if f.is_file() and f.resolve() != latest_file.resolve():
                f.unlink()
    except Exception as e:
        print(f"[{ts()}] [CLEANUP] Error: {traceback.format_exc()}")


def upload_ndc_reports(ctx: ClientContext, target_base: str):
    """Upload only the latest Excel file from local uploads/NDC_Reports to SharePoint."""
    if not NDC_REPORTS_DIR.exists():
        return

    try:
        latest_file = get_latest_report(NDC_REPORTS_DIR)
    except FileNotFoundError:
        print(f"[{ts()}] No NDC report files found.")
        return

    cleanup_old_ndc_reports(latest_file)

    target_folder_url = f"{target_base}/NDC_Reports"
    
    ensure_folder_exists(ctx, target_folder_url)
    try:
        target_folder = ctx.web.get_folder_by_server_relative_url(target_folder_url)
        files = target_folder.files.get().execute_query()
        for f in files:
            f.delete_object()
        ctx.execute_query()
    except Exception as e:
        print(f"[{ts()}] [CLEANUP] SharePoint cleanup error: {traceback.format_exc()}")

    print(f"[{ts()}] NDC report: {latest_file.name}")
    upload_file_to_sharepoint(ctx, latest_file, target_folder_url)


def upload_ff_reports(ctx: ClientContext, target_base: str):
    """Upload all F&F documents from local uploads/FF_Reports to SharePoint."""
    if not FF_REPORTS_DIR.exists():
        return

    subdirs = [d for d in FF_REPORTS_DIR.iterdir() if d.is_dir()]
    if not subdirs:
        print(f"[{ts()}] No F&F employee folders found.")
        return

    target_base_url = f"{target_base}/F&F_Documents"
    print(f"[{ts()}] F&F documents: {len(subdirs)} employee(s)")
    
    for subdir in subdirs:
        emp_id = subdir.name
        files = [f for f in subdir.iterdir() if f.is_file()]
        if not files:
            continue

        emp_target_url = f"{target_base_url}/{emp_id}"
        for f in files:
            try:
                upload_file_to_sharepoint(ctx, f, emp_target_url)
            except Exception as e:
                print(f"[{ts()}] [ERROR] Failed to upload {f.name} for employee {emp_id}: {e}\n{traceback.format_exc()}")


def main():
    parser = argparse.ArgumentParser(description="Upload report files to SharePoint.")
    parser.add_argument(
        "--type",
        choices=["ndc", "ff", "all"],
        default="all",
        help="Type of reports to upload: 'ndc' (Excel files), 'ff' (Employee F&F folders), or 'all' (default).",
    )
    parser.add_argument(
        "--file",
        type=str,
        help="Path to a specific file to upload. If provided, uploads directly to the main target folder.",
    )
    args = parser.parse_args()

    try:
        # Connect to SharePoint
        ctx = connect_sharepoint()

        if args.file:
            # Upload a single specific file to the base target folder
            local_file = Path(args.file)
            if not local_file.exists():
                raise FileNotFoundError(f"Specified file not found: {args.file}")
            upload_file_to_sharepoint(ctx, local_file, TARGET_FOLDER)
        else:
            # Standard directory based upload
            if not TARGET_FOLDER:
                raise ValueError("SHAREPOINT_TARGET_FOLDER environment variable is not set.")

            if args.type in ["ndc", "all"]:
                try:
                    upload_ndc_reports(ctx, TARGET_FOLDER)
                except Exception as e:
                    print(f"[{ts()}] [ERROR] NDC reports upload failed: {e}\n{traceback.format_exc()}")

            if args.type in ["ff", "all"]:
                try:
                    upload_ff_reports(ctx, TARGET_FOLDER)
                except Exception as e:
                    print(f"[{ts()}] [ERROR] F&F reports upload failed: {e}\n{traceback.format_exc()}")

    except ValueError as e:
        print(f"\n[{ts()}] [ERROR] Configuration Error: {traceback.format_exc()}")
    except FileNotFoundError as e:
        print(f"\n[{ts()}] [ERROR] File Not Found: {traceback.format_exc()}")
    except PermissionError as e:
        print(f"\n[{ts()}] [ERROR] Local Permission Error: {traceback.format_exc()}")
    except ClientRequestException as e:
        print(f"\n[{ts()}] [ERROR] SharePoint API Error: {e.response.status_code}\n{traceback.format_exc()}")
    except Exception as e:
        print(f"\n[{ts()}] [ERROR] Unexpected Error: {traceback.format_exc()}")


if __name__ == "__main__":
    main()

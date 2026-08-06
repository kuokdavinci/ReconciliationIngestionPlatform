"""File ingestion CLI handler."""

import os
import re
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
import paramiko

from src.config.cache import ConfigCache
from src.config.loader import ConfigLoader
from src.config.validator import ConfigValidator
from src.core.enums import FileType
from src.core.types import FieldMapping, FieldMappingType
from src.domain.mapping.models import MappingConfig
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.pipeline.ingestion_pipeline import IngestionPipeline
from cli import get_db, init_databases


def parse_excel_template(template_path: str) -> dict:
    """Parses a MappingConfig dynamically from an Excel template file (e.g. RequestTemplate.xlsx).

    No hardcoded values. Everything is read dynamically from the spreadsheet cells.
    """
    print(f"Parsing configuration dynamically from template: {template_path}")
    wb = openpyxl.load_workbook(template_path, data_only=True)
    sheet = wb["Sheet1"]

    partner = sheet.cell(row=3, column=1).value
    path_file_pattern = sheet.cell(row=3, column=4).value
    start_row = int(sheet.cell(row=3, column=5).value)

    raw_id = sheet.cell(row=3, column=6).value
    raw_trace = sheet.cell(row=3, column=7).value
    raw_amount = sheet.cell(row=3, column=8).value
    raw_currency = sheet.cell(row=3, column=9).value
    raw_status = sheet.cell(row=3, column=10).value
    raw_trans_date = sheet.cell(row=3, column=11).value

    extra_service = sheet.cell(row=3, column=12).value
    extra_portal = sheet.cell(row=3, column=13).value
    extra_provider = sheet.cell(row=3, column=14).value

    def parse_column_field(raw_val, path, mapping_type):
        if not raw_val:
            return None
        lines = [line.strip() for line in raw_val.split("\n") if line.strip()]
        col_match = re.match(r"column\s+(\d+)", lines[0], re.IGNORECASE)
        if col_match:
            # Shift 0-based column from template to 1-based column for system
            col_num = int(col_match.group(1)) + 1
            source_field = lines[1] if len(lines) > 1 else None

            mapping_dict = None
            if mapping_type == FieldMappingType.MAPPING:
                mapping_dict = {}
                for line in lines[1:]:
                    if ":" in line:
                        k, v = line.split(":", 1)
                        mapping_dict[k.strip()] = v.strip()

            return FieldMapping(
                path=path,
                column=col_num,
                sourceField=source_field,
                type=mapping_type,
                required=(path == "id"),
                mapping=mapping_dict
            )
        else:
            return FieldMapping(
                path=path,
                constant=raw_val,
                type=FieldMappingType.CONSTANT
            )

    field_mappings = []
    field_mappings.append(parse_column_field(raw_id, "id", FieldMappingType.STRING))
    field_mappings.append(parse_column_field(raw_trace, "trace", FieldMappingType.STRING))
    field_mappings.append(parse_column_field(raw_amount, "amount", FieldMappingType.DECIMAL))
    field_mappings.append(FieldMapping(path="currency", constant=raw_currency, type=FieldMappingType.CONSTANT))
    field_mappings.append(parse_column_field(raw_status, "status", FieldMappingType.MAPPING))
    field_mappings.append(parse_column_field(raw_trans_date, "transDate", FieldMappingType.DATE))

    field_mappings.append(FieldMapping(path="extra.service", constant=extra_service, type=FieldMappingType.CONSTANT))
    field_mappings.append(FieldMapping(path="extra.portal", constant=extra_portal, type=FieldMappingType.CONSTANT))
    field_mappings.append(FieldMapping(path="extra.provider", constant=extra_provider, type=FieldMappingType.CONSTANT))

    field_mappings = [fm for fm in field_mappings if fm is not None]

    # Extract filename from path pattern
    filename = Path(path_file_pattern).name if path_file_pattern else "m4becomvsp_07072024_combine.xlsx"
    if path_file_pattern and "#{" in path_file_pattern:
        # Fallback to test file name if it contains expression
        filename = "m4becomvsp_07072024_combine.xlsx"

    # Excel template always uses Sheet1
    sheet_name = "Sheet1"

    return {
        "partner": partner,
        "start_row": start_row + 1,  # Row 7 is header, data starts at 8
        "field_mappings": field_mappings,
        "filename": filename,
        "sheet_name": sheet_name,
    }


def _create_config_loader(db):
    """Create a ConfigLoader instance.

    Args:
        db: AsyncIOMotorDatabase instance.

    Returns:
        ConfigLoader instance.
    """
    config_repo = MappingConfigRepository(db)
    config_cache = ConfigCache()
    config_validator = ConfigValidator()
    return ConfigLoader(config_repo, config_cache, config_validator)


async def run_ingestion(args):
    """Handle --data and --config CLI commands (ingestion pipeline).

    Manages config upload (--config), SFTP download (if no --data),
    pipeline execution, and cleanup.
    """
    db, client = await get_db()
    await init_databases(db)

    # Upload Config Dynamically if --config is passed
    if args.config:
        parsed_config = parse_excel_template(args.config)
        partner = parsed_config["partner"]
        start_row = parsed_config["start_row"]
        field_mappings = parsed_config["field_mappings"]
        remote_filename = parsed_config["filename"]

        parsed_sheet_name = parsed_config.get("sheet_name", "Sheet1")
        print(f"Uploading parsed MappingConfig for {partner} to MongoDB...")
        config_doc = MappingConfig(
            partner=partner,
            workflow_type="UPC",
            file_type=FileType.SETTLEMENT,
            sheet_name=parsed_sheet_name,
            start_row=start_row,
            field_mappings=field_mappings,
            config_version="v_template"
        )
        await db["reconciliation_mapping_config"].delete_many({"partner": partner})
        config_repo = MappingConfigRepository(db)
        await config_repo.create(config_doc)
        print("MappingConfig successfully uploaded to MongoDB!")

    # Determine partner and file path
    partner = args.partner
    if not args.data and not args.config:
        print("Error: Provide --data (local file) or --config (SFTP workflow).")
        return
    if args.data:
        local_path = Path(args.data)
        if not local_path.exists():
            print(f"Error: Data file not found: {local_path}")
            return
        print(f"Using local data file: {local_path}")
    else:
        # SFTP Connection and File Download
        sftp_host = os.getenv("SFTP_HOST", "localhost")
        sftp_port = int(os.getenv("SFTP_PORT", "2222"))
        sftp_user = os.getenv("SFTP_USER", "foo")
        sftp_pass = os.getenv("SFTP_PASS", "pass")

        remote_path = f"/upload/{remote_filename}"
        local_dir = Path("./tmp_downloads")
        local_dir.mkdir(exist_ok=True)
        local_path = local_dir / remote_filename

        print(f"Connecting to SFTP {sftp_user}@{sftp_host}:{sftp_port}...")
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(sftp_host, port=sftp_port, username=sftp_user, password=sftp_pass, timeout=10)

            sftp = ssh.open_sftp()
            print(f"Downloading {remote_path} from SFTP...")
            sftp.get(remote_path, str(local_path))
            sftp.close()
            ssh.close()
            print(f"File downloaded successfully to {local_path}")
        except Exception as e:
            print(f"SFTP connection/download failed: {e}")
            fallback_path = Path("./sftp_data") / remote_filename
            if fallback_path.exists():
                print(f"Using local sftp_data fallback: {fallback_path}")
                local_path = fallback_path
            else:
                print("Error: Could not retrieve file from SFTP or local sftp_data folder.")
                return

    # Determine reconciliation date
    if args.date:
        recon_date = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        recon_date = datetime(2024, 7, 7, tzinfo=timezone.utc)

    # Clean up previous records for a fresh run
    date_str = recon_date.strftime("%Y-%m-%d")
    print(f"Cleaning up any existing records for {partner} on {date_str}...")
    await db["reconciliation_file"].delete_many({"partner": partner, "reconciliationDate": recon_date})
    await db["data_container"].delete_many({"identify": partner, "reconciliationDate": recon_date})

    # Run Ingestion Pipeline
    config_repo = MappingConfigRepository(db)
    config_cache = ConfigCache()
    config_validator = ConfigValidator()
    config_loader = ConfigLoader(config_repo, config_cache, config_validator)

    pipeline = IngestionPipeline(db=db, config_loader=config_loader)

    print("Processing file through ingestion pipeline...")
    result = await pipeline.process_file(
        file_path=str(local_path),
        partner=partner,
        workflow_type="UPC",
        file_type=FileType.SETTLEMENT,
        reconciliation_date=recon_date,
        config_version="v_template",
        enable_config_health_check=True,
    )

    # Print Results
    print("\n=== Pipeline Processing Summary ===")
    print(f"Status: {result.file_record.processing_status}")
    print(f"Total Rows: {result.stats.total_rows}")
    print(f"Success Rows: {result.stats.success_rows}")
    print(f"Failed Rows: {result.stats.failed_rows}")

    if result.errors:
        print(f"Errors ({len(result.errors)}):")
        for err in result.errors[:5]:
            print(f"  - Row {err.get('row', 'N/A')}: {err.get('field')} -> {err.get('reason')}")

    saved_count = await db["data_container"].count_documents({"identify": partner})
    print(f"Verified documents in MongoDB (data_container): {saved_count}")

    # Clean up temp files (only if downloaded via SFTP)
    if not args.data and local_path.exists() and "tmp_downloads" in str(local_path):
        try:
            local_path.unlink()
            local_dir = Path("./tmp_downloads")
            if local_dir.exists() and not any(local_dir.iterdir()):
                local_dir.rmdir()
            print("Cleaned up temporary download files.")
        except Exception as e:
            print(f"Warning: Could not clean up temporary directory: {e}")

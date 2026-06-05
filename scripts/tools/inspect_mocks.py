import openpyxl
import os
from pathlib import Path

sftp_dir = Path("/home/kuokdavinci/AdapterService/sftp_data")
for file in sftp_dir.iterdir():
    if file.suffix == ".xlsx" and not file.name.startswith(".~"):
        print(f"\n=== File: {file.name} ===")
        try:
            wb = openpyxl.load_workbook(file, read_only=True)
            ws = wb.active
            print(f"Active Sheet: {ws.title}")
            rows = list(ws.iter_rows(values_only=True))
            print(f"Total Rows: {len(rows)}")
            # Find the first non-empty row as header
            header_row = None
            header_idx = -1
            for idx, r in enumerate(rows):
                if any(c is not None and str(c).strip() != "" for c in r):
                    header_row = [str(c) if c is not None else "" for c in r]
                    header_idx = idx
                    break
            if header_row:
                # Truncate empty cells from the end
                while header_row and header_row[-1] == "":
                    header_row.pop()
                print(f"Header Row (Index {header_idx + 1}): {header_row[:15]} ... (Total columns: {len(header_row)})")
                # Print a couple of sample rows
                sample_count = 0
                for r in rows[header_idx + 1:]:
                    if any(c is not None and str(c).strip() != "" for c in r):
                        non_empty_row = [str(c) if c is not None else "" for c in r]
                        print(f"  Data Row: {non_empty_row[:15]}...")
                        sample_count += 1
                        if sample_count >= 2:
                            break
            wb.close()
        except Exception as e:
            print(f"Error reading {file.name}: {e}")

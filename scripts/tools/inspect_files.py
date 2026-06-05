import openpyxl

def main():
    path = "/home/kuokdavinci/AdapterService/sftp_data/m4becomvsp_07072024_combine.xlsx"
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb["data"]
    rows = list(ws.iter_rows(values_only=True))
    print(f"Total rows: {len(rows)}")
    for i in range(5, min(len(rows), 15)):
        print(f"Row {i+1}: {rows[i][:20]}")
    wb.close()

if __name__ == "__main__":
    main()

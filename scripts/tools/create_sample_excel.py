import openpyxl

def main():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    
    # Headers
    headers = ["Mã Giao Dịch", "Mã Truy Vấn", "Số Tiền", "Ngày Giao Dịch", "Trạng Thái"]
    ws.append(headers)
    
    # Data Rows
    data = [
        ["TXN99001", "TRC2024070701", 150000, "2024-07-07 10:15:30", "SUCCESS"],
        ["TXN99002", "TRC2024070702", 230000, "2024-07-07 11:22:40", "SUCCESS"],
        ["TXN99003", "TRC2024070703", 50000, "2024-07-07 12:05:10", "FAILED"],
        ["TXN99004", "TRC2024070704", 500000, "2024-07-07 14:45:00", "SUCCESS"],
        ["TXN99005", "TRC2024070705", 100000, "2024-07-07 16:30:15", "SUCCESS"]
    ]
    
    for row in data:
        ws.append(row)
        
    file_path = "/home/kuokdavinci/AdapterService/vnpay_sample.xlsx"
    wb.save(file_path)
    print(f"Sample Excel saved to {file_path}")

if __name__ == "__main__":
    main()

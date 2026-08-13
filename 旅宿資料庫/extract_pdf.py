import PyPDF2

pdf_path = r"C:\Users\lzh08\OneDrive\桌面\日遊所思夜遊所夢資料集\觀光資料標準V2.1.pdf"
with open(pdf_path, 'rb') as f:
    reader = PyPDF2.PdfReader(f)
    for i, page in enumerate(reader.pages):
        text = page.extract_text()
        if "HotelClasses" in text or "旅宿" in text or "類別" in text:
            print(f"--- Page {i} ---")
            print(text)

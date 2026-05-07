import json
import os
import pytesseract
from PIL import Image
from utils.logger import get_logger

logger = get_logger("Loader")


def load_input(path, index=0):
    ext = os.path.splitext(path)[1].lower()

    logger.info(f"Loading file: {path}")

    # 🟢 CASE 1: JSON → use directly
    if ext == ".json":
        with open(path) as f:
            data = json.load(f)

        if isinstance(data, list):
            return data, False  # False = no extraction needed
        return data, False

    # 🟡 CASE 2: TXT → read text
    elif ext == ".txt":
        with open(path) as f:
            text = f.read()

        return {"text": text}, True

    # 🔵 CASE 3: PDF → extract text
    elif ext == ".pdf":
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)

        return {"text": text}, True

    # 🟣 CASE 4: IMAGE → OCR
    elif ext in [".png", ".jpg", ".jpeg"]:


        text = pytesseract.image_to_string(Image.open(path))

        return {"text": text}, True

    else:
        raise ValueError(f"Unsupported file type: {ext}")
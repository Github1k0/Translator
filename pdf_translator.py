# PDF Visual Translator using Gemini API and WeasyPrint

# Installation notes for Pydroid 3 (and other pip environments):
# 1. Make sure you have pip available.
# 2. Install necessary Python libraries:
#    pip install requests Pillow pdf2image google-generativeai weasyprint pypdf
#
# 3. **CRITICAL for `pdf2image` (Image Conversion):** 
#    This library REQUIRES 'poppler' to be installed on your system.
#    - For Pydroid 3: This is the trickiest part. Search Pydroid 3 settings/forums 
#      for how to install Poppler binaries. If Pydroid 3's package manager (if any) 
#      offers 'poppler-utils', install it. Otherwise, this may not be possible directly in Pydroid.
#    - For Linux: sudo apt-get install poppler-utils
#    - For macOS: brew install poppler
#    - For Windows: Download Poppler binaries, add its 'bin' folder to your System PATH.
#    You MIGHT need to set the POPPLER_PATH variable in this script if Poppler is installed 
#    but not found automatically by pdf2image.
#
# 4. **For `WeasyPrint` (PDF Generation from HTML):**
#    WeasyPrint has its own dependencies (like Pango, Cairo, GDK-PixBuf). 
#    - For Pydroid 3: Check if Pydroid 3's package manager can install these. 
#      `pip install weasyprint` might fetch some, but system-level libraries are often needed.
#      This might also be challenging on Pydroid 3.
#    - For Linux: sudo apt-get install libpango-1.0-0 libcairo2 libgdk-pixbuf2.0-0
#    - For macOS: brew install pango cairo gdk-pixbuf
#    - For Windows: Installation can be complex. See WeasyPrint documentation.

import requests
import base64
import json
from PIL import Image
import os
import traceback
import pathlib
import io # Moved import io to top-level
from pdf2image import convert_from_path, pdfinfo_from_path
from pdf2image.exceptions import (
    PDFInfoNotInstalledError,
    PDFPageCountError,
    PDFSyntaxError
)
from weasyprint import HTML as WeasyHTML # Alias to avoid conflict if HTML is used elsewhere
from pypdf import PdfReader, PdfMerger # PyPDF2 is now often under the 'pypdf' package name
# If 'from PyPDF2 import PdfReader' fails for the user, they might have an older install.
# For now, let's assume 'pypdf' as it's the modern way.

# --- CONFIGURATION ---
API_KEY = "YOUR_API_KEY_HERE"  # IMPORTANT: Replace with your actual Gemini API Key
MODEL_NAME = "gemini-1.5-flash-latest" 
TARGET_LANGUAGE = "ru"         # Target language for translation

# --- PDF Processing Configuration ---
PDF_PATH = "sample.pdf"        # Path to the PDF file you want to translate
                               # Create a 'sample.pdf' or change to your PDF
PAGES_TO_TRANSLATE = [1]       # List of specific page numbers to translate (e.g., [1, 2, 5]). 
                               # Set to None or [] to attempt all pages.
POPPLER_PATH = None            # Optional: Path to Poppler 'bin' directory.
                               # Example for Windows: r"C:\Program Files\poppler-23.08.0\Library\bin"
                               # Set if Poppler is not in your system PATH.
DPI_FOR_PDF_CONVERSION = 200       # Resolution for converting PDF pages to images
TEMP_PAGE_PDF_SUBFOLDER = "temp_translated_pages" # Subfolder for temporary per-page PDFs
    
# --- OUTPUT ---
# (We'll define output paths later, e.g., in the main loop)

# --- END CONFIGURATION ---

def encode_image(filepath_or_image_object):
    """Encodes an image from a filepath or PIL Image object to base64."""
    if isinstance(filepath_or_image_object, str): # It's a filepath
        if not os.path.exists(filepath_or_image_object):
            print(f"Ошибка: Файл изображения не найден по пути: {filepath_or_image_object}")
            return None
        try:
            with open(filepath_or_image_object, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode("utf-8")
        except Exception as e:
            print(f"Ошибка при чтении или кодировании файла {filepath_or_image_object}: {e}")
            return None
    elif isinstance(filepath_or_image_object, Image.Image): # It's a PIL Image object
        try:
            # import io # Removed from here
            buffered = io.BytesIO()
            filepath_or_image_object.save(buffered, format="JPEG") # Or PNG
            return base64.b64encode(buffered.getvalue()).decode("utf-8")
        except Exception as e:
            print(f"Ошибка при кодировании объекта PIL Image: {e}")
            return None
    else:
        print("Ошибка: `encode_image` ожидает путь к файлу или объект PIL Image.")
        return None

def convert_pdf_pages_to_images(pdf_path, page_numbers=None, poppler_path=None, dpi=200):
    """
    Converts specified pages of a PDF to a list of PIL Image objects.
    If page_numbers is None, converts all pages.
    page_numbers should be a list of 1-based page numbers.
    """
    pdf_file = pathlib.Path(pdf_path)
    if not pdf_file.exists():
        print(f"Ошибка: PDF файл не найден по пути: {pdf_path}")
        return [], [] # Return empty lists for images and page numbers

    try:
        # Check total pages first to validate page_numbers
        try:
            info = pdfinfo_from_path(pdf_file, poppler_path=poppler_path)
            total_pages = info["Pages"]
        except PDFInfoNotInstalledError:
            print("Ошибка: Poppler не найден. Установите Poppler и/или укажите 'poppler_path'.")
            print("Подсказка: `poppler_path` можно указать как аргумент в `convert_pdf_pages_to_images`.")
            print("Пример для Windows: convert_pdf_pages_to_images(..., poppler_path=r'C:\some\path\to\poppler\bin')")
            return [], [] # Cannot proceed without poppler

        valid_page_numbers = []
        if page_numbers:
            for pn in page_numbers:
                if 1 <= pn <= total_pages:
                    valid_page_numbers.append(pn)
                else:
                    print(f"Предупреждение: Номер страницы {pn} вне диапазона (1-{total_pages}). Пропускается.")
            if not valid_page_numbers:
                print("Ошибка: Ни один из указанных номеров страниц не является действительным.")
                return [], []
        else: # If no specific page_numbers, process all pages
            valid_page_numbers = list(range(1, total_pages + 1))
        
        print(f"Конвертация страниц: {valid_page_numbers} из PDF '{pdf_path}' (всего страниц: {total_pages})")

        images = []
        successfully_converted_pages = [] # New list for successfully converted page numbers
        # convert_from_path takes first_page and last_page, or page_numbers list (newer versions)
        # To handle specific, non-contiguous pages, it's better to call it for each page or small batches
        # However, for simplicity and common use case of a few pages, let's try to optimize
        
        # Efficiently convert specified pages. Some versions of pdf2image are more efficient with this.
        # We pass 0-indexed pages to convert_from_path if using first_page/last_page logic, 
        # but the page_numbers list itself should be 1-indexed for user input.
        # The `pages` parameter in `convert_from_path` expects 1-based page numbers directly if it's a list.
        
        # Let's convert all requested pages in one go if the version of pdf2image supports it well,
        # or iterate if that's more robust. The `pages` parameter is what we want.
        
        # For `convert_from_path`, `first_page` and `last_page` are 1-indexed.
        # The `thread_count` can be increased for performance on multi-core systems.
        # `fmt='jpeg'` can be used to save memory if images are large, but PIL default is fine.
        
        # Simplest approach for specified pages:
        # Convert all pages up to the max required page, then select.
        # This might be inefficient if only a few pages from a large PDF are needed.
        # A better way is to use the `pages` argument if available and works as expected.
        # The documentation for `pdf2image` suggests `pages` can be a list of page numbers.

        # Let's try to convert pages one by one to be safe and handle non-contiguous pages well.
        # This is less efficient than batch conversion but more robust for specific page numbers.
        for page_num in valid_page_numbers:
            try:
                # convert_from_path page numbers are 1-indexed for first_page, last_page
                page_image = convert_from_path(
                    pdf_file,
                    dpi=dpi,
                    first_page=page_num,
                    last_page=page_num,
                    poppler_path=poppler_path,
                    fmt='png' # Using PNG for better quality for OCR
                )
                if page_image:
                    images.append(page_image[0]) # convert_from_path returns a list
                    successfully_converted_pages.append(page_num) # Add page_num here
                    print(f"Страница {page_num} успешно сконвертирована.")
            except Exception as e_page:
                print(f"Ошибка при конвертации страницы {page_num}: {e_page}")
        
        if not images:
            print("Не удалось сконвертировать ни одной страницы.")
        return images, successfully_converted_pages # Return tuple

    except PDFInfoNotInstalledError:
        # This was already caught above, but as a fallback.
        print("Критическая ошибка: Poppler не установлен или не найден. Пожалуйста, установите Poppler.")
        print("Инструкции по установке есть в комментариях в начале скрипта.")
        return [], []
    except PDFPageCountError:
        print(f"Ошибка: Не удалось определить количество страниц в PDF: {pdf_path}. Файл поврежден или не PDF.")
        return [], []
    except PDFSyntaxError:
        print(f"Ошибка: Неверный синтаксис PDF файла: {pdf_path}. Файл может быть поврежден.")
        return [], []
    except Exception as e:
        print(f"Неожиданная ошибка при конвертации PDF в изображения: {e}")
        traceback.print_exc()
        return [], []

def extract_text_from_pdf_page(pdf_path, page_number, existing_reader=None):
    """
    Extracts text from a specific page of a PDF file using PyPDF2 (pypdf).

    Args:
        pdf_path (str): Path to the PDF file.
        page_number (int): The 1-based page number from which to extract text.
        existing_reader (PdfReader, optional): An existing PdfReader object to reuse.
                                              Useful when extracting from multiple pages
                                              of the same PDF to avoid reopening the file.

    Returns:
        str: The extracted text, or an empty string if extraction fails or page not found.
    """
    text = ""
    reader = None
    try:
        if existing_reader:
            reader = existing_reader
        else:
            if not os.path.exists(pdf_path):
                print(f"Ошибка (PyPDF2): PDF файл не найден по пути: {pdf_path}")
                return ""
            reader = PdfReader(pdf_path)
        
        if page_number < 1 or page_number > len(reader.pages):
            print(f"Ошибка (PyPDF2): Номер страницы {page_number} вне диапазона (1-{len(reader.pages)}).")
            return ""
            
        page = reader.pages[page_number - 1] # 0-indexed
        text = page.extract_text()
        if not text: # Handle cases where extract_text() returns None or empty
            text = "" 
            # print(f"Предупреждение (PyPDF2): Текст не найден или не удалось извлечь со страницы {page_number}.")
        
    except Exception as e:
        print(f"Ошибка (PyPDF2) при извлечении текста со страницы {page_number} из '{pdf_path}': {e}")
        traceback.print_exc()
        return "" # Return empty string on error
    
    # Note: We are not closing the reader here if it was passed in as existing_reader.
    # The caller who created it should manage its lifecycle (e.g., if it's opened once in the main loop).
    # If we create it here, it's closed implicitly when 'reader' goes out of scope or by PdfReader's __exit__.
    return text.strip() if text else ""

def create_prompt(target_language_code):
    """Creates a prompt for Gemini to OCR and translate text from an image."""
    prompt = f"""
Инструкция: Внимательно проанализируй предоставленное изображение.
Задача:
1. Обнаружить ВЕСЬ текст на изображении (OCR).
2. Перевести весь обнаруженный текст на следующий язык: {target_language_code}.
Требования к выводу:
- Верни ТОЛЬКО переведенный текст.
- Не включай никаких объяснений, извинений, нумерации, маркеров или любого другого текста, кроме самого перевода.
- Если на изображении нет текста, верни пустую строку.
- Постарайся сохранить смысл и форматирование оригинала, насколько это возможно в рамках простого текста.
"""
    return prompt

def create_translation_html_prompt(target_language, extracted_text=None):
    """
    Creates a prompt for Gemini to translate text from an image (and optional pre-extracted text)
    and generate an HTML representation of the translated page, mimicking the original layout.
    """
    # Instruction preamble
    instruction = "Your task is to act as a document layout specialist and translator."
    instruction += " You will be given an image of a document page"
    if extracted_text: # This argument check is for constructing the general instruction text
        instruction += " and pre-extracted text from that page."
    else:
        instruction += "."

    # The actual 'extracted_text' content is NOT embedded directly into this prompt string here.
    # This function generates the main textual instruction for Gemini.
    # The `send_request` function will be responsible for constructing the
    # multi-part message including this prompt, the image, and the optional actual extracted_text content.

    final_prompt_text = f"""
{instruction}

--- PRE-EXTRACTED TEXT (if provided separately in the API call) ---
If pre-extracted text is provided in a separate part of the input, use it as the primary source for text to be translated. 
Verify it against the image; if major discrepancies exist, you may note them if it seems critical, but prioritize accurate translation and layout reconstruction based on the image.

--- IMAGE ANALYSIS AND TRANSLATION TASK ---
1. Analyze the provided image to understand its visual layout: text block positions, headings, paragraphs, any images, columns, relative font sizes, etc.
2. If pre-extracted text was NOT provided separately (or if it's clearly missing significant parts visible in the image), perform OCR on the image to extract all text. If pre-extracted text is available and seems mostly complete, prioritize it.
3. Translate all relevant text (either the pre-extracted text or the OCRed text) into **{target_language}**.

--- HTML OUTPUT REQUIREMENTS ---
Generate a SINGLE HTML STRING that reconstructs the page content using the TRANSLATED text.
- The HTML structure must mimic the visual layout, positioning, and relative styling (font sizes for headings, bolding, etc.) of the original page as seen in the input image.
- Use simple HTML tags (e.g., `<h1>`, `<h2>`, `<p>`, `<div>`, `<span>`).
- Use inline CSS for styling and positioning. For example:
  `<div style="position:absolute; left:30px; top:50px; font-size:16pt; font-weight:bold;">Translated Heading</div>`
  `<p style="position:absolute; left:30px; top:80px; font-size:10pt; width: 500px;">Translated paragraph text...</p>`
- Preserve the general reading flow. If there are columns, try to represent them (e.g., using `divs` with appropriate `float:left; width:X%; margin-right:Y%;` or simple flexbox/grid if you deem it necessary and simple).
- For any images detected on the original page, if you can determine their approximate size (width, height in pixels) and position (left, top in pixels), represent them with a placeholder in the HTML:
  `<div style="position:absolute; left:Xpx; top:Ypx; width:Wpx; height:Hpx; border:1px solid #ccc; background-color:#f0f0f0; display:flex; align-items:center; justify-content:center;"><span style="font-size:10pt; color:#888;">Original Image Placeholder</span></div>`
- Ensure the generated HTML is well-formed and self-contained (no external CSS files or complex scripts).
- Base coordinates and dimensions on a coordinate system where (0,0) is the top-left of the page. You will need to estimate pixel values from the image. Assume a common page aspect ratio if exact dimensions are unknown (e.g., similar to A4 or US Letter).

--- RESPONSE FORMAT ---
IMPORTANT: Respond ONLY with the raw HTML string. Do NOT include any other text, explanations, apologies, or markdown formatting (like ```html ... ```) around the HTML content.
The HTML content should start with `<html>` or a `<div>` and end accordingly.
"""
    return final_prompt_text

def send_request(api_key, model, prompt_instruction_text, encoded_image, optional_extracted_text=None):
    """Отправляет запрос к Gemini API, с возможностью включения дополнительного извлеченного текста."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    mime_type = "image/jpeg" # Assuming JPEG from encode_image
    
    parts = [
        {"inline_data": {"mime_type": mime_type, "data": encoded_image}},
        {"text": prompt_instruction_text} # This is the prompt generated by create_translation_html_prompt
    ]
    if optional_extracted_text:
        # Add the extracted text as another part. Gemini can use this.
        # Inserting it before the main prompt but after the image, as per common multi-modal examples.
        parts.insert(1, {"text": "---\nPre-extracted Text Content (for context and translation accuracy):\n---\n" + optional_extracted_text + "\n---"})


    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.2, # Adjust as needed
            "response_mime_type": "text/plain", # Expecting HTML, so text/plain
        }
    }
    headers = {'Content-Type': 'application/json'}

    try:
        # response = requests.post(url, headers=headers, json=payload)
        response = requests.post(url, headers=headers, json=payload, timeout=60) # Added timeout
        response.raise_for_status() # Raises an HTTPError for bad responses (4XX or 5XX)
        
        # If response_mime_type was 'text/plain', response.text is the direct content.
        # If it was 'application/json' (for other types of requests this function might be used for),
        # then response.json() would be appropriate.
        # Given the current context for HTML generation, response_mime_type is "text/plain".
        if payload.get("generationConfig", {}).get("response_mime_type") == "text/plain":
            return response.text # Return raw text (HTML)
        else:
            # Fallback for other potential uses or if mime_type is accidentally different
            try:
                return response.json() 
            except json.JSONDecodeError:
                 # This might happen if the server sends plain text error for a JSON request
                 print("Ошибка: Ожидался JSON, но не удалось декодировать ответ. Текст ответа:")
                 print(response.text)
                 return None

    except requests.exceptions.RequestException as e:
        print(f"Ошибка сети или API: {e}")
        if hasattr(e, 'response') and e.response is not None:
            # Attempt to print response text, which might be JSON error details or plain text
            print(f"Ответ сервера ({e.response.status_code}):")
            try:
                # Try to pretty-print if it's JSON
                error_details = e.response.json()
                print(json.dumps(error_details, indent=2, ensure_ascii=False))
            except json.JSONDecodeError:
                # If not JSON, print as plain text
                print(e.response.text)
        return None
    # Removed the specific json.JSONDecodeError here as it's handled above for the JSON case,
    # and for text/plain, a decode error isn't expected for the primary content.

def parse_gemini_html_response(html_string):
    """
    Parses the direct HTML string output from Gemini.
    Currently, this is a simple pass-through after basic validation.
    """
    if not html_string or not html_string.strip():
        print("Предупреждение: Получен пустой или отсутствующий HTML ответ от Gemini.")
        return None # Or an empty string, depending on how caller handles it

    # Basic sanity check (optional, as Gemini was strictly prompted)
    # if not (html_string.strip().startswith("<") and html_string.strip().endswith(">")):
    #     print(f"Предупреждение: Ответ не выглядит как HTML: {html_string[:100]}...") # Print first 100 chars
        # Depending on strictness, could return None here or proceed.
        # For now, trust the prompt and pass through.

    return html_string.strip()

def convert_html_to_pdf(html_string, output_pdf_path):
    """
    Converts an HTML string to a PDF file using WeasyPrint.

    Args:
        html_string (str): The HTML content to convert.
        output_pdf_path (str): The file path where the output PDF should be saved.

    Returns:
        bool: True if PDF generation was successful, False otherwise.
    """
    if not html_string or not html_string.strip():
        print("Ошибка (WeasyPrint): HTML строка для конвертации в PDF пуста.")
        return False

    try:
        print(f"Генерация PDF из HTML в файл: {output_pdf_path}...")
        # Ensure the directory for output_pdf_path exists, if it includes directories
        output_dir = os.path.dirname(output_pdf_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print(f"Создана директория: {output_dir}")

        WeasyHTML(string=html_string).write_pdf(output_pdf_path)
        print(f"PDF успешно создан: {output_pdf_path}")
        return True
    except FileNotFoundError:
        # This can happen if a linked resource in HTML (like an image) is not found,
        # though our HTML from Gemini should be self-contained or use placeholders.
        # More likely, this is an issue with WeasyPrint's own external dependencies not being found.
        print(f"Ошибка (WeasyPrint): Возможно, не найдены необходимые файлы или зависимости WeasyPrint.")
        print(f"Убедитесь, что WeasyPrint и его системные зависимости (Pango, Cairo, etc.) установлены корректно.")
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"Ошибка (WeasyPrint) при конвертации HTML в PDF: {e}")
        print("Проверьте корректность HTML или наличие всех зависимостей WeasyPrint.")
        print(f"Проблемный HTML (первые 500 символов):\n{html_string[:500]}")
        traceback.print_exc()
        return False

# --- Main execution block ---
if __name__ == "__main__":
    print("--- PDF Visual Translator Initialized ---")

    # --- Validate API_KEY ---
    if not API_KEY or API_KEY == "YOUR_API_KEY_HERE":
        print("ОШИБКА: Пожалуйста, установите ваш API_KEY в переменной API_KEY в начале скрипта.")
        exit()
    
    # --- Validate PDF_PATH ---
    if not os.path.exists(PDF_PATH):
        print(f"ОШИБКА: PDF файл не найден по пути: {PDF_PATH}")
        print("Пожалуйста, убедитесь, что файл существует, или измените переменную PDF_PATH в скрипте.")
        exit()

    # --- Poppler Path Reminder (if not set) ---
    if POPPLER_PATH is None:
        print("ИНФО: POPPLER_PATH не установлен. Убедитесь, что Poppler находится в системном PATH,")
        print("      иначе укажите путь к директории 'bin' Poppler в переменной POPPLER_PATH.")
        print("      Конвертация PDF в изображения не удастся без Poppler.")
    
    print(f"Загрузка PDF: {PDF_PATH}")
    page_images, processed_page_numbers = convert_pdf_pages_to_images(PDF_PATH, 
                                                                     page_numbers=PAGES_TO_TRANSLATE, 
                                                                     poppler_path=POPPLER_PATH, 
                                                                     dpi=DPI_FOR_PDF_CONVERSION) 

    if not page_images:
        print("КРИТИЧЕСКАЯ ОШИБКА: Не удалось сконвертировать PDF страницы в изображения. Проверьте ошибки выше.")
        print("                  Убедитесь, что Poppler установлен и доступен (см. заметки по установке).")
        exit()

    print(f"Успешно сконвертировано {len(page_images)} страниц(ы) для обработки: {processed_page_numbers}")
    
    # Create temporary subfolder for individual PDF pages
    if not os.path.exists(TEMP_PAGE_PDF_SUBFOLDER):
        os.makedirs(TEMP_PAGE_PDF_SUBFOLDER)
        print(f"Создана временная директория для страниц: {TEMP_PAGE_PDF_SUBFOLDER}")

    pdf_reader = None
    DECISION_USE_PYPDF2_TEXT = True 
    if DECISION_USE_PYPDF2_TEXT:
        try:
            pdf_reader = PdfReader(PDF_PATH)
        except Exception as e:
            print(f"Ошибка при открытии PDF с помощью PyPDF2: {e}. Продолжение без PyPDF2 текста.")
            DECISION_USE_PYPDF2_TEXT = False

    successfully_translated_pdf_pages = [] 

    for i, page_image in enumerate(page_images):
        page_num = processed_page_numbers[i]
        print(f"\n--- Обработка страницы {page_num} ---")

        print(f"  Кодирование изображения страницы {page_num}...")
        encoded_image_data = encode_image(page_image)
        if not encoded_image_data:
            print(f"  ОШИБКА: Не удалось закодировать изображение для страницы {page_num}. Пропуск страницы.")
            continue

        extracted_text_for_prompt = None
        if DECISION_USE_PYPDF2_TEXT and pdf_reader:
            print(f"  Извлечение текста со страницы {page_num} с помощью PyPDF2...")
            extracted_text_for_prompt = extract_text_from_pdf_page(PDF_PATH, page_num, existing_reader=pdf_reader)
            if extracted_text_for_prompt:
                print(f"  Извлечено {len(extracted_text_for_prompt)} символов текста со страницы {page_num}.")
            else:
                print(f"  Не удалось извлечь текст с помощью PyPDF2 со страницы {page_num} или страница пуста.")
        
        print(f"  Формирование запроса на перевод и верстку (язык: {TARGET_LANGUAGE}) для страницы {page_num}...")
        prompt_instructions = create_translation_html_prompt(TARGET_LANGUAGE, extracted_text=extracted_text_for_prompt)
        
        print(f"  Отправка запроса к модели {MODEL_NAME} для страницы {page_num}...")
        api_response_html = send_request(API_KEY, 
                                       MODEL_NAME, 
                                       prompt_instructions, 
                                       encoded_image_data,
                                       optional_extracted_text=extracted_text_for_prompt) 

        if not api_response_html:
            print(f"  ОШИБКА: Не удалось получить ответ от API для страницы {page_num}. Пропуск страницы.")
            continue

        print(f"  Обработка HTML ответа от Gemini для страницы {page_num}...")
        html_content = parse_gemini_html_response(api_response_html)

        if not html_content:
            print(f"  ОШИБКА: Не удалось извлечь HTML контент из ответа API для страницы {page_num}. Пропуск страницы.")
            continue
        
        page_output_pdf_path = os.path.join(TEMP_PAGE_PDF_SUBFOLDER, f"translated_page_{page_num}.pdf")
        print(f"  Конвертация HTML в PDF для страницы {page_num} -> {page_output_pdf_path}...")
        if convert_html_to_pdf(html_content, page_output_pdf_path):
            successfully_translated_pdf_pages.append(page_output_pdf_path)
        else:
            print(f"  ОШИБКА: Не удалось сконвертировать HTML в PDF для страницы {page_num}.")

    # --- End of page loop ---

    # --- Merge individual PDFs ---
    if not successfully_translated_pdf_pages:
        print("\nОШИБКА: Ни одна страница не была успешно переведена в PDF.")
    elif len(successfully_translated_pdf_pages) == 1:
        final_pdf_name = f"{os.path.splitext(os.path.basename(PDF_PATH))[0]}_translated_p{processed_page_numbers[0]}.pdf"
        # Ensure the source path for rename includes the subfolder
        source_single_pdf_path = successfully_translated_pdf_pages[0]
        try:
            os.rename(source_single_pdf_path, final_pdf_name)
            print(f"\n--- Перевод завершен ---")
            print(f"Создан один переведенный PDF файл: {final_pdf_name}")
            # Attempt to remove the (now empty) temporary subfolder if this was the only file
            if TEMP_PAGE_PDF_SUBFOLDER and os.path.exists(TEMP_PAGE_PDF_SUBFOLDER) and not os.listdir(TEMP_PAGE_PDF_SUBFOLDER):
                try:
                    os.rmdir(TEMP_PAGE_PDF_SUBFOLDER)
                    print(f"Удалена временная директория: {TEMP_PAGE_PDF_SUBFOLDER}")
                except OSError as e_rmdir:
                    print(f"Предупреждение: Не удалось удалить временную директорию {TEMP_PAGE_PDF_SUBFOLDER}: {e_rmdir}")
        except Exception as e_rename:
            print(f"ОШИБКА при переименовании единственного PDF файла: {e_rename}")
            print(f"Переведенный PDF файл доступен по пути: {source_single_pdf_path}")

    else:
        merger = PdfMerger()
        # Construct final PDF name based on the original PDF name and processed page numbers
        original_pdf_basename = os.path.splitext(os.path.basename(PDF_PATH))[0]
        pages_str = '_'.join(map(str, processed_page_numbers))
        final_pdf_name = f"{original_pdf_basename}_translated_pages_{pages_str}.pdf"
        
        print(f"\nОбъединение {len(successfully_translated_pdf_pages)} переведенных страниц в один PDF: {final_pdf_name}...")
        for pdf_page_path in successfully_translated_pdf_pages:
            merger.append(pdf_page_path)
        
        try:
            merger.write(final_pdf_name)
            merger.close()
            print(f"Финальный PDF '{final_pdf_name}' успешно создан.")
            
            # Clean up individual page PDFs and the subfolder
            print(f"Удаление временных PDF файлов страниц из '{TEMP_PAGE_PDF_SUBFOLDER}'...")
            for pdf_page_path in successfully_translated_pdf_pages:
                try:
                    os.remove(pdf_page_path)
                except Exception as e_remove:
                    print(f"  Предупреждение: Не удалось удалить временный файл {pdf_page_path}: {e_remove}")
            
            # Attempt to remove the temporary subfolder if it's empty
            if TEMP_PAGE_PDF_SUBFOLDER and os.path.exists(TEMP_PAGE_PDF_SUBFOLDER) and not os.listdir(TEMP_PAGE_PDF_SUBFOLDER):
                try:
                    os.rmdir(TEMP_PAGE_PDF_SUBFOLDER)
                    print(f"Удалена временная директория: {TEMP_PAGE_PDF_SUBFOLDER}")
                except OSError as e_rmdir:
                    print(f"Предупреждение: Не удалось удалить временную директорию {TEMP_PAGE_PDF_SUBFOLDER}: {e_rmdir}")

        except Exception as e_merge:
            print(f"  ОШИБКА при объединении PDF файлов: {e_merge}")
            print(f"  Индивидуальные переведенные страницы сохранены в '{TEMP_PAGE_PDF_SUBFOLDER}'.")

    print("\n--- Процесс перевода полностью завершен ---")

# PDF Translator using Gemini API

# Installation notes for Pydroid 3 (and other pip environments):
# 1. Make sure you have pip available.
# 2. Install necessary libraries:
#    pip install requests Pillow pdf2image google-generativeai
#
# 3. **IMPORTANT for `pdf2image`**: This library requires `poppler` to be installed on your system.
#    - For Pydroid 3: Poppler is often included or can be installed via its package manager if available.
#      If you get errors related to "poppler", search for how to install poppler binaries in Pydroid's environment.
#    - For Linux: sudo apt-get install poppler-utils
#    - For macOS: brew install poppler
#    - For Windows: Download Poppler binaries, add to PATH. See pdf2image documentation.
#      You might need to specify the poppler_path in convert_from_path if not in PATH.

import requests
import base64
import json
from PIL import Image # ImageDraw and ImageFont removed
import os
import traceback
import pathlib
from pdf2image import convert_from_path, pdfinfo_from_path
from pdf2image.exceptions import (
    PDFInfoNotInstalledError,
    PDFPageCountError,
    PDFSyntaxError
)

# --- CONFIGURATION ---
API_KEY = "AIzaSyAH1Dty8GNnQNE7WLmWLXrg-8d7sWc_t78" # Replace with your API key
MODEL_NAME = "gemini-1.5-flash-latest" # Updated model name
# IMAGE_PATH = "image.jpg" # Will be replaced by PDF path
# OBJECTS_TO_DETECT = "все машины" # Not relevant for translation
# OUTPUT_IMAGE_PATH = "output_image.jpg" # Not relevant for now
TARGET_LANGUAGE = "ru" # Target language for translation

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
            import io
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
            print("Пример для Windows: convert_pdf_pages_to_images(..., poppler_path=r'C:\path\to\poppler\bin')")
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

def send_request(api_key, model, prompt, encoded_image):
    """Отправляет запрос к Gemini API."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    # Determine mime_type based on how image is saved by PIL (JPEG for now)
    mime_type = "image/jpeg" 
    payload = {
        "contents": [
            {
                "parts": [
                    {"inline_data": {"mime_type": mime_type, "data": encoded_image}},
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "response_mime_type": "application/json",
        }
    }
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Ошибка сети или API: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Ответ сервера ({e.response.status_code}): {e.response.text}")
        return None
    except json.JSONDecodeError:
        print("Ошибка: Не удалось декодировать ответ сервера как JSON.")
        if 'response' in locals() and response is not None:
            print(f"Текст ответа: {response.text}")
        return None

def parse_response(response_data):
    """Извлекает переведенный текст из ответа API."""
    if not response_data:
        print("Ошибка: Получены пустые данные ответа.")
        return "" 
    try:
        if "candidates" not in response_data or not response_data["candidates"]:
            print("Ошибка: В ответе API отсутствует поле 'candidates' или оно пустое.")
            if "promptFeedback" in response_data and "blockReason" in response_data["promptFeedback"]:
                 print(f"Ответ заблокирован. Причина: {response_data['promptFeedback']['blockReason']}")
                 if "safetyRatings" in response_data["promptFeedback"]:
                     print(f"Рейтинги безопасности: {response_data['promptFeedback']['safetyRatings']}")
            else:
                print(f"Полный ответ: {response_data}")
            return ""

        candidate = response_data["candidates"][0]

        if "content" not in candidate or "parts" not in candidate["content"] or not candidate["content"]["parts"]:
            # Check for safety ratings if content is missing, as per original code's logic for safety
            if "safetyRatings" in candidate:
                 print("Ошибка: Ответ мог быть заблокирован настройками безопасности (отсутствует 'content').")
                 print(f"Причина завершения: {candidate.get('finishReason', 'Нет информации')}")
                 print(f"Рейтинги безопасности: {candidate['safetyRatings']}")
            else:
                print("Ошибка: В ответе API отсутствует 'content' или 'parts'.")
                print(f"Кандидат: {candidate}")
            return ""
        
        part = candidate["content"]["parts"][0]
        if "text" not in part:
            print("Ошибка: В ответе API отсутствует поле 'text' в 'parts[0]'.")
            print(f"Часть: {part}")
            return ""

        translated_text = part["text"].strip()
        return translated_text

    except KeyError as e:
        print(f"Ошибка: Отсутствует ожидаемый ключ '{e}' в ответе API.")
        print(f"Полный ответ: {response_data}")
        return ""
    except Exception as e:
        print(f"Неожиданная ошибка при обработке ответа: {e}")
        traceback.print_exc()
        print(f"Полный ответ API: {response_data}")
        return ""

# --- Main execution block ---
if __name__ == "__main__":
    print("--- PDF Translator Initialized ---")

    # --- Configuration for PDF Processing ---
    # TODO: Consider making these configurable (e.g., command-line arguments)
    PDF_PATH = "sample.pdf"  # Replace with your PDF file path
    # Specify pages to translate (1-based indexing). None or empty list means all pages.
    PAGES_TO_TRANSLATE = [1, 2] # Example: Translate first two pages
    # PAGES_TO_TRANSLATE = None # Example: Translate all pages
    
    # Optional: If Poppler is not in PATH, specify its bin directory
    # Example for Windows: POPPLER_PATH = r"C:\Program Files\poppler-23.08.0\Library\bin" 
    POPPLER_PATH = None # Set to None if Poppler is in PATH or Pydroid handles it

    TARGET_LANGUAGE = "ru" # Defined in global config, but good to be aware here
    # --- End Configuration ---

    if not API_KEY or API_KEY == "AIzaSyAH1Dty8GNnQNE7WLmWLXrg-8d7sWc_t78": # Default placeholder
        print("Ошибка: Пожалуйста, установите ваш API_KEY в переменной API_KEY в начале скрипта.")
        exit()
        
    if not os.path.exists(PDF_PATH):
        print(f"Ошибка: PDF файл не найден по пути: {PDF_PATH}")
        print("Пожалуйста, убедитесь, что файл существует, или измените переменную PDF_PATH в скрипте.")
        exit()

    print(f"Загрузка PDF: {PDF_PATH}")
    # Convert specified PDF pages to images
    # The 'page_numbers' argument in 'convert_pdf_pages_to_images' expects a list of 1-based page numbers.
    page_images, processed_page_numbers = convert_pdf_pages_to_images(PDF_PATH, page_numbers=PAGES_TO_TRANSLATE, poppler_path=POPPLER_PATH)

    if not page_images:
        print("Не удалось сконвертировать PDF страницы в изображения. Проверьте ошибки выше.")
        print("Убедитесь, что Poppler установлен и доступен (см. заметки по установке).")
    else:
        print(f"Успешно сконвертировано {len(page_images)} страниц(ы) для перевода: {processed_page_numbers}")
        
        # The complex logic for actual_page_numbers_being_processed is no longer needed.
        # We directly use processed_page_numbers.

        for i, page_image in enumerate(page_images):
            page_num_for_display = processed_page_numbers[i] # Use directly from the returned list
            
            print(f"\n--- Обработка страницы {page_num_for_display} ---")

            print("Кодирование изображения страницы...")
            encoded_image_data = encode_image(page_image) # encode_image handles PIL Image objects

            if encoded_image_data:
                print(f"Формирование запроса на перевод (язык: {TARGET_LANGUAGE})...")
                prompt_text = create_prompt(TARGET_LANGUAGE)

                print(f"Отправка запроса к модели {MODEL_NAME}...")
                api_response = send_request(API_KEY, MODEL_NAME, prompt_text, encoded_image_data)

                if api_response:
                    print("Обработка ответа...")
                    translated_text = parse_response(api_response)
                    if translated_text:
                        print(f"*** Переведенный текст (Страница {page_num_for_display}): ***\n{translated_text}")
                    else:
                        print(f"Не удалось получить переведенный текст для страницы {page_num_for_display}.")
                        print("Возможные причины: нет текста на странице, ошибка API, или ответ был отфильтрован.")
                else:
                    print(f"Не удалось получить ответ от API для страницы {page_num_for_display}.")
            else:
                print(f"Не удалось закодировать изображение для страницы {page_num_for_display}.")
        
        print("\n--- Перевод завершен ---")

    # Example of how one might call this if it were a function:
    # process_pdf_for_translation(PDF_PATH, PAGES_TO_TRANSLATE, POPPLER_PATH, TARGET_LANGUAGE)

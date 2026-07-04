import os
import io
import json
import datetime
from PIL import Image

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google import genai
from google.genai import types

SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
CONFIG_FILE = 'config.json'

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def get_credentials():
    return service_account.Credentials.from_service_account_file('service_account.json', scopes=SCOPES)

def analyze_image_with_gemini(image_bytes, api_key):
    client = genai.Client(api_key=api_key)
    image = Image.open(io.BytesIO(image_bytes))
    
    prompt = """Analyze this document/image (like a date sheet or alert) and generate a short, punchy notice (maximum 1 to 2 sentences) suitable for a scrolling news ticker on a university website.
    Return a JSON object with this exact structure:
    {
      "Title": "The short notice text summarizing the key announcement.",
      "Link": "Any specific URL mentioned. If none is found, return '#'"
    }
    Return ONLY the valid JSON object."""

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[prompt, image],
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"[ERROR] Gemini API Failed: {e}")
        return None

def process_notices():
    config = load_config()
    creds = get_credentials()
    drive_service = build('drive', 'v3', credentials=creds)
    sheets_service = build('sheets', 'v4', credentials=creds)

    folder_id = config['drive_folder_id']
    sheet_id = config['spreadsheet_id']
    sheet_name = config.get('sheet_name', 'Sheet1')
    api_key = config['gemini_api_key']

    # فولڈر میں نئی تصاویر تلاش کریں
    query = f"'{folder_id}' in parents and trashed = false and mimeType contains 'image/'"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])

    if not files:
        print("[INFO] No new notices found.")
        return

    for file in files:
        file_id = file['id']
        print(f"\n[PROCESS] Processing {file['name']}...")

        # تصویر ڈاؤنلوڈ کریں
        request = drive_service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        # جیمنی اے آئی سے نوٹس بنوائیں
        data = analyze_image_with_gemini(fh.getvalue(), api_key)
        if not data: 
            continue

        title = data.get("Title", "New Update")
        link = data.get("Link", "#")
        status = "Active"
        date_added = datetime.date.today().strftime("%Y-%m-%d")

        new_row = [title, link, status, date_added]

        # گوگل شیٹ کا موجودہ ڈیٹا نکالیں
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=f"'{sheet_name}'!A:D"
        ).execute()
        values = result.get('values', [])

        # اگر شیٹ بالکل خالی ہے تو ہیڈرز شامل کریں
        if not values:
            values = [["Title", "Link", "Status", "Date"]]

        # نیا نوٹس قطار نمبر 2 (ہیڈر کے فوراً بعد) شامل کریں
        values.insert(1, new_row)

        # صرف ہیڈر اور تازہ ترین 4 نوٹسز رکھیں (کل 5 قطاریں)، باقی پرانے ہٹا دیں
        values = values[:5]

        # شیٹ کو صاف کر کے نیا اپڈیٹڈ ڈیٹا لکھیں
        sheets_service.spreadsheets().values().clear(
            spreadsheetId=sheet_id, range=f"'{sheet_name}'!A:D"
        ).execute()

        sheets_service.spreadsheets().values().update(
            spreadsheetId=sheet_id, range=f"'{sheet_name}'!A1",
            valueInputOption="RAW", body={"values": values}
        ).execute()

        print(f"[SUCCESS] Added notice: {title}")

        # تصویر کو گوگل ڈرائیو کے ٹریش میں ڈال دیں
        drive_service.files().update(fileId=file_id, body={'trashed': True}).execute()
        print(f"[SUCCESS] File moved to trash.")

if __name__ == '__main__':
    process_notices()

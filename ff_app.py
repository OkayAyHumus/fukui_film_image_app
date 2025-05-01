import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
import pandas as pd
from PIL import Image
import os
from io import BytesIO

st.set_page_config(page_title="Google Drive Image Uploader", layout="wide")
st.title("📁 Google Drive 画像アップローダー")

def get_drive_service():
    creds_dict = st.secrets["gcp_service_account"]
    creds = service_account.Credentials.from_service_account_info(creds_dict)
    return build("drive", "v3", credentials=creds)

def list_image_files(service, folder_id):
    query = f"'{folder_id}' in parents and mimeType contains 'image/' and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    return results.get("files", [])

def display_images(service, files, cwd):
    data_dir = os.path.join(cwd, "data")
    os.makedirs(data_dir, exist_ok=True)
    for f in files:
        file_id = f["id"]
        file_name = f["name"]
        content = service.files().get_media(fileId=file_id).execute()
        path = os.path.join(data_dir, file_name)
        with open(path, "wb") as out_file:
            out_file.write(content)
        image = Image.open(path)
        st.image(image, caption=file_name, width=300)

cwd = os.path.dirname(__file__)
service = get_drive_service()

folder_id = st.text_input("Google Drive フォルダIDを入力:")
if folder_id:
    files = list_image_files(service, folder_id)
    if files:
        display_images(service, files, cwd)
    else:
        st.warning("画像が見つかりません")

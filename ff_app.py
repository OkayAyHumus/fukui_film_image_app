import streamlit as st
import pandas as pd
import os
from PIL import Image
from io import BytesIO
from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# ========================
# Google Drive接続
# ========================
def get_drive_service():
    creds_dict = st.secrets["gcp_service_account"]
    creds = service_account.Credentials.from_service_account_info(creds_dict)
    return build("drive", "v3", credentials=creds)

# ========================
# users.csv の読み込みとアップロード
# ========================
@st.cache_data
def download_csv_from_drive(_service, file_name, folder_id):
    query = f"'{folder_id}' in parents and name = '{file_name}' and mimeType = 'text/csv'"
    results = _service.files().list(q=query, fields="files(id)").execute()
    items = results.get("files", [])
    if not items:
        return None, None

    file_id = items[0]["id"]
    request = _service.files().get_media(fileId=file_id)
    fh = BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    fh.seek(0)
    df = pd.read_csv(fh)
    return df, file_id

def upload_csv_to_drive(service, df, file_name, folder_id, file_id=None):
    buffer = BytesIO()
    df.to_csv(buffer, index=False)
    buffer.seek(0)
    media = MediaIoBaseUpload(buffer, mimetype='text/csv')

    metadata = {"name": file_name, "parents": [folder_id]}
    if file_id:
        service.files().update(fileId=file_id, media_body=media).execute()
    else:
        service.files().create(body=metadata, media_body=media).execute()

# ========================
# ログイン機能
# ========================
def login(service, users_df):
    st.sidebar.header("🔐 ログイン")

    if "username" in st.session_state:
        st.sidebar.success(f"ログイン中: {st.session_state['username']}")
        if st.sidebar.button("ログアウト"):
            for key in ["username", "folder_id", "is_admin"]:
                st.session_state.pop(key, None)
            st.session_state["login_submitted"] = False
            st.rerun()
        return

    if "login_submitted" not in st.session_state:
        st.session_state.login_submitted = False

    username = st.sidebar.text_input("ユーザー名", key="login_username")
    password = st.sidebar.text_input("パスワード", type="password", key="login_password")

    if st.sidebar.button("ログイン"):
        st.session_state.login_submitted = True

    if st.session_state.login_submitted:
        users_df["username"] = users_df["username"].astype(str).str.strip()
        users_df["password"] = users_df["password"].astype(str).str.strip()
        u = str(st.session_state.login_username).strip()
        p = str(st.session_state.login_password).strip()

        match = users_df[(users_df["username"] == u) & (users_df["password"] == p)]

        if not match.empty:
            st.session_state["username"] = u
            st.session_state["folder_id"] = match.iloc[0]["folder_id"]
            st.session_state["is_admin"] = u == "admin"
            st.rerun()
        else:
            st.sidebar.error("ユーザー名またはパスワードが違います")
            st.session_state.login_submitted = False

    if "username" not in st.session_state:
        st.stop()

# ========================
# 画像処理
# ========================
def list_image_files_in_folder(service, folder_id):
    query = f"'{folder_id}' in parents and mimeType contains 'image/' and trashed = false"
    results = service.files().list(q=query, fields="files(name)").execute()
    return [item["name"] for item in results.get("files", [])]

def display_images_with_checkboxes(cwd, service, file_names):
    selected_files = []
    data_dir = os.path.join(cwd, "data")
    os.makedirs(data_dir, exist_ok=True)

    for file_name in file_names:
        query = f"name = '{file_name}' and mimeType contains 'image/'"
        items = service.files().list(q=query).execute().get("files", [])
        if not items:
            continue

        file_id = items[0]["id"]
        file_content = service.files().get_media(fileId=file_id).execute()
        file_path = os.path.join(data_dir, file_name)
        with open(file_path, "wb") as f:
            f.write(file_content)

        image = Image.open(file_path)
        width, height = image.size
        file_size = os.path.getsize(file_path) // 1024  # KB単位に変換

        cols = st.columns([1, 11])
        with cols[0]:
            checked = st.checkbox("", key=file_name)
        with cols[1]:
            st.markdown(
                f"<div style='border:1px solid #ccc; border-radius:10px; padding:10px;'>"
                f"<b>{file_name}</b><br>{width} × {height}px<br>{file_size:,} KB</div>",
                unsafe_allow_html=True
            )
            st.image(image, width=200)

        if checked:
            selected_files.append(file_name)
    return selected_files

def create_timestamped_folder(service, parent_folder_id=None):
    folder_name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    metadata = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_folder_id:
        metadata["parents"] = [parent_folder_id]
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"], folder_name

def compress_and_upload_images(service, cwd, file_names, max_size_bytes, upload_folder_id):
    uploaded = []
    for file_name in file_names:
        file_path = os.path.join(cwd, "data", file_name)
        image = Image.open(file_path)
        buffer = BytesIO()
        quality = 95
        while quality >= 10:
            buffer.seek(0)
            buffer.truncate()
            image.save(buffer, format="JPEG", quality=quality, optimize=True)
            if buffer.tell() <= max_size_bytes:
                break
            quality -= 5
        if quality < 10:
            st.warning(f"{file_name} は圧縮できませんでした")
            continue

        buffer.seek(0)
        metadata = {"name": f"compressed_{file_name}", "parents": [upload_folder_id]}
        media = MediaIoBaseUpload(buffer, mimetype="image/jpeg")
        service.files().create(body=metadata, media_body=media).execute()
        uploaded.append(file_name)
        st.success(f"{file_name} をアップロードしました")
    return uploaded

# ========================
# メイン処理
# ========================
def main():
    st.set_page_config(page_title="画像圧縮・管理アプリ", layout="wide")

    st.markdown("""
    <style>
    .main-title {
        font-size: 2em;
        font-weight: bold;
        color: #2c3e50;
        margin-bottom: 20px;
    }
    </style>
    <div class='main-title'>📷 福井県フィルムコミッション｜画像圧縮・ユーザー管理</div>
    """, unsafe_allow_html=True)

    cwd = os.path.dirname(__file__)
    service = get_drive_service()

    admin_folder_id = st.secrets["folders"]["admin_folder_id"]  # ← Driveのusers.csvのフォルダIDを指定
    users_df, users_file_id = download_csv_from_drive(service, "users.csv", admin_folder_id)
    if users_df is None:
        st.error("users.csv が見つかりません")
        return

    login(service, users_df)

    user_folder_id = st.session_state["folder_id"]
    file_list = list_image_files_in_folder(service, user_folder_id)
    if not file_list:
        st.warning("画像が見つかりません")
        return

    selected = display_images_with_checkboxes(cwd, service, file_list)

    with st.form("compression_form"):
        max_kb = st.number_input("📐 最大ファイルサイズ（KB）", min_value=50, max_value=2048, value=500, key="max_kb_input")
        submit_btn = st.form_submit_button("📤 圧縮してアップロード")

    if submit_btn and selected:
        max_bytes = st.session_state.max_kb_input * 1024
        parent_folder_id = st.session_state["folder_id"]
        new_folder_id, _ = create_timestamped_folder(service, parent_folder_id=parent_folder_id)
        compress_and_upload_images(service, cwd, selected, max_bytes, new_folder_id)
        st.rerun()

if __name__ == "__main__":
    main()

# --- 必要なインポート ---
import streamlit as st
import pandas as pd
import numpy as np
import re
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
import gspread

# --- 設定 ---
json_key_path = "/Users/poca/hrmos/mineral-liberty-460106-m7-a24c4c78154f.json"
drive_folder_id = "1tQGYGjOmWR0MBWJ6NpSQ9etg3rxTzvuY"
target_filename_pattern = "kintai_"  # ファイル名のパターン（前部分）
sheet_url = "https://docs.google.com/spreadsheets/d/1Ymt2OrvY2dKFs9puCX8My7frS_BS1sg3Yev3BLQm9xQ/edit"

# --- サービスアカウント認証 ---
scopes = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets"
]
credentials = service_account.Credentials.from_service_account_file(json_key_path, scopes=scopes)

drive_service = build("drive", "v3", credentials=credentials)
gspread_client = gspread.authorize(credentials)

# --- Driveから該当するファイル一覧を取得 ---
results = drive_service.files().list(
    q=f"name contains '{target_filename_pattern}' and '{drive_folder_id}' in parents and trashed=false",
    spaces="drive",
    fields="files(id, name, modifiedTime)"
).execute()
items = results.get("files", [])

if not items:
    st.error(f"❌ ファイルが見つかりません: {target_filename_pattern}*")
else:
    # ファイル名から日付を抽出してソート
    def extract_date_from_filename(filename):
        """ファイル名から日付を抽出する（例: kintai_2025-05.csv -> 2025-05）"""
        match = re.search(r'(\d{4}-\d{2})', filename)
        if match:
            return match.group(1)
        return None
    
    # 日付が抽出できるファイルのみを対象にする
    valid_files = []
    for item in items:
        date_str = extract_date_from_filename(item['name'])
        if date_str:
            try:
                # 日付文字列をdatetimeオブジェクトに変換（比較用）
                date_obj = datetime.strptime(date_str, '%Y-%m')
                valid_files.append({
                    'id': item['id'],
                    'name': item['name'],
                    'date_str': date_str,
                    'date_obj': date_obj,
                    'modified_time': item['modifiedTime']
                })
            except ValueError:
                continue
    
    if not valid_files:
        st.error("❌ 有効な日付形式のファイルが見つかりません")
    else:
        # 最新の日付のファイルを選択
        latest_file = max(valid_files, key=lambda x: x['date_obj'])
        
        file_id = latest_file['id']
        target_filename = latest_file['name']
        
        st.success(f"✅ 最新ファイルを検出: {target_filename} ({latest_file['date_str']})")
        
        # 他の候補ファイルがある場合は表示
        if len(valid_files) > 1:
            other_files = [f['name'] for f in valid_files if f['id'] != file_id]
            st.info(f"📝 他の候補ファイル: {', '.join(other_files)}")

        # --- DriveからCSVをダウンロード ---
        request = drive_service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()

        fh.seek(0)
        try:
            df = pd.read_csv(fh, encoding="cp932")
        except UnicodeDecodeError:
            fh.seek(0)
            df = pd.read_csv(fh, encoding="shift_jis")

        df = df.fillna("")
        st.dataframe(df)

        # --- 時間列の定義 ---
        time_columns = [
            '所定内勤務時間',
            '所定時間外勤務時間',
            '所定外休日勤務時間',
            '法定外休日勤務時間',
            '法定休日勤務時間',
            '深夜勤務時間',
            '勤務時間',
            '実勤務時間',
            '確定_有給なし_残業時間'
        ]

        # --- 時間フォーマット変換処理 ---
        def preprocess_value(val):
            if pd.isna(val):
                return ""
            if isinstance(val, str):
                val = val.replace("'", "")
                time_pattern = re.compile(r'^(\d{1,3}):(\d{2})')
                match = time_pattern.match(val)
                if match:
                    hours, minutes = match.groups()
                    return f"{hours}:{minutes}:00"
                return val
            if isinstance(val, (int, float)):
                return val
            return str(val)

        # --- スプレッドシートへ書き込み処理 ---
        try:
            spreadsheet = gspread_client.open_by_url(sheet_url)
            worksheet = spreadsheet.worksheet("貼り付け用")

            # データ前処理
            processed_data = []
            for row in df.values.tolist():
                processed_row = [preprocess_value(val) for val in row]
                processed_data.append(processed_row)
            processed_headers = [preprocess_value(col) for col in df.columns.values.tolist()]

            # シートをクリアしてデータ書き込み
            worksheet.clear()
            worksheet.update([processed_headers] + processed_data, value_input_option='USER_ENTERED')

            # 時間列の書式を整える
            for col_name in time_columns:
                if col_name in df.columns:
                    col_index = df.columns.get_loc(col_name)
                    col_letter = chr(65 + col_index)  # A〜Z対応（列数が多い場合は gspread.utils.toA1推奨）
                    time_range = f'{col_letter}2:{col_letter}{len(processed_data) + 1}'
                    worksheet.format(time_range, {
                        "numberFormat": {
                            "type": "TIME",
                            "pattern": "[h]:mm:ss"
                        }
                    })

            st.success(f"✅ '{target_filename}' のデータを '貼り付け用' シートへ更新しました")

        except Exception as e:
            st.error(f"❌ スプレッドシートの更新中にエラーが発生しました: {str(e)}")
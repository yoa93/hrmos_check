# --- 必要なインポート ---
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from datetime import datetime
from dateutil.relativedelta import relativedelta
import mimetypes
import glob
import time
import os
import random
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# --- 設定 ---
download_dir = "/Users/poca/hrmos"
folder_id = "1tQGYGjOmWR0MBWJ6NpSQ9etg3rxTzvuY"
json_key_path = "/Users/poca/hrmos/mineral-liberty-460106-m7-a24c4c78154f.json"

# --- 任意の対象月を指定（例：2025年4月） ---
target_year = 2025
target_month = 5
target_month_str = f"{target_year}-{target_month:02}"
filename = f"kintai_{target_month_str}.csv"

# --- CSVファイル出現を待機 ---
def wait_for_csv_file(directory, timeout=60):
    seconds = 0
    while seconds < timeout:
        csvs = glob.glob(os.path.join(directory, "*.csv"))
        if csvs:
            return sorted(csvs, key=os.path.getmtime)[-1]
        time.sleep(1)
        seconds += 1
    raise TimeoutError("❌ CSVファイルが見つかりません（タイムアウト）")

# --- Google Driveへアップロード（サービスアカウント使用） ---
def upload_to_drive(filepath, drive_filename, folder_id):
    creds = service_account.Credentials.from_service_account_file(
        json_key_path,
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    service = build("drive", "v3", credentials=creds)

    mime_type = mimetypes.guess_type(filepath)[0] or "application/octet-stream"
    media = MediaFileUpload(filepath, mimetype=mime_type)

    # 同名ファイルの検索（上書き対応）
    results = service.files().list(
        q=f"name='{drive_filename}' and '{folder_id}' in parents and trashed=false",
        spaces="drive",
        fields="files(id, name)"
    ).execute()
    items = results.get("files", [])

    if items:
        file_id = items[0]["id"]
        service.files().update(
            fileId=file_id,
            media_body=media
        ).execute()
        print(f"♻️ 既存ファイルを上書き: {drive_filename}")
    else:
        file_metadata = {
            "name": drive_filename,
            "parents": [folder_id]
        }
        uploaded_file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id"
        ).execute()
        print(f"🆕 新規ファイルとして作成: {drive_filename}")

    print(f"✅ Google Drive にアップロード完了: {drive_filename}")

# --- Chrome設定 ---
options = Options()
options.add_experimental_option("prefs", {
    "download.default_directory": download_dir,
    "download.prompt_for_download": False,
    "directory_upgrade": True,
    "safebrowsing.enabled": True
})
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")

# --- メイン処理 ---
driver = None
try:
    driver = webdriver.Chrome(options=options)
    driver.get("https://p.ieyasu.co/sho_ei/login/")

    driver.find_element(By.ID, "user_login_id").send_keys("a-yoshida@sho-ei.net")
    driver.find_element(By.ID, "user_password").send_keys("Dx7p3r4i@")
    driver.find_element(By.XPATH, "//input[@type='submit' and @value='ログイン']").click()

    # レポート画面へ遷移
    time.sleep(1)
    driver.find_element(By.LINK_TEXT, "レポート").click()
    time.sleep(1)
    driver.find_element(By.LINK_TEXT, "月次集計データ出力").click()

    # 指定の期間を選択
    Select(driver.find_element(By.ID, "select")).select_by_value(target_month_str)
    time.sleep(2)
    Select(driver.find_element(By.ID, "select_last")).select_by_value(target_month_str)
    time.sleep(2)

    # 「CSV出力」ボタンをフォーム内から明示的に取得してクリック
    form = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "output_file_month"))
    )

    csv_button = form.find_element(By.CSS_SELECTOR, "input[type='submit'][value='CSV出力']")
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", csv_button)
    time.sleep(1)
    csv_button.click()
    print("✅ CSV出力ボタンをクリックしました")
    time.sleep(60)

    WebDriverWait(driver, 15).until(
        EC.text_to_be_present_in_element((By.CSS_SELECTOR, "span.notice"), "月次集計データ出力 を受け付けました。")
    )
    print("✅ 出力受付メッセージを検出しました")

    driver.find_element(By.LINK_TEXT, "CSV・PDF履歴").click()
    print("📁 CSV・PDF履歴ページへ遷移しました")

    download_link = WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((
            By.XPATH,
            "//a[contains(text(),'出力') and contains(@href, '/files/') and contains(@class, 'btnSubmit')]"
        ))
    )
    href = download_link.get_attribute("href")
    driver.get(href)
    print("⬇️ 出力リンクからCSVダウンロードを開始しました")

    latest_csv = wait_for_csv_file(download_dir)
    print(f"✅ ダウンロード完了: {latest_csv}")

    upload_to_drive(filepath=latest_csv, drive_filename=filename, folder_id=folder_id)

    input("確認後 Enter を押して終了します...")

finally:
    if driver:
        driver.quit()

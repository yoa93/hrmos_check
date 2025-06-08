# --- 必要なインポート ---
import streamlit as st
import pandas as pd
import os
import requests
import time

st.set_page_config(
    layout="wide"
)

# Google関連のインポートをtry-exceptで囲む
try:
    from google.oauth2 import service_account
    import gspread
    GOOGLE_LIBS_AVAILABLE = True
except ImportError as e:
    st.error(f"Google ライブラリが見つかりません: {e}")
    st.error("requirements.txt に以下が含まれていることを確認してください:")
    st.code("""
google-auth>=2.0.0
google-auth-oauthlib>=0.5.0
gspread>=5.0.0
    """)
    st.stop()

# --- 設定の初期化 ---
@st.cache_data
def get_config():
    """設定情報を取得"""
    config = {
        "development_mode": False,
        "sheet_url": "https://docs.google.com/spreadsheets/d/1Ymt2OrvY2dKFs9puCX8My7frS_BS1sg3Yev3BLQm9xQ/edit",
        "has_secrets": False,
        "has_gcp_account": False,
        "has_oauth": False
    }
    
    # Streamlit Secretsの確認
    try:
        if hasattr(st, 'secrets') and st.secrets:
            config["has_secrets"] = True
            config["development_mode"] = st.secrets.get("DEVELOPMENT_MODE", False)
            
            # Google Service Accountの確認
            if "gcp_service_account" in st.secrets:
                config["has_gcp_account"] = True
            
            # Google OAuth設定の確認
            required_oauth_keys = ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]
            oauth_keys_present = all(key in st.secrets for key in required_oauth_keys)
            
            if oauth_keys_present:
                client_id = str(st.secrets.get("GOOGLE_CLIENT_ID", "")).strip()
                client_secret = str(st.secrets.get("GOOGLE_CLIENT_SECRET", "")).strip()
                
                if client_id and client_secret:
                    if client_secret.startswith("GOCSPX-") and len(client_secret) > 10:
                        config["has_oauth"] = True
                    elif len(client_secret) > 20:
                        config["has_oauth"] = True
                        
    except Exception as e:
        config["config_error"] = str(e)
    
    return config

# --- OAuth認証関数 ---
def get_google_auth_url():
    """Google OAuth認証URLを生成"""
    config = get_config()
    if not config["has_oauth"]:
        return None
    
    import urllib.parse
    
    client_id = st.secrets["GOOGLE_CLIENT_ID"]
    
    # リダイレクトURIの決定
    try:
        if (hasattr(st, 'get_option') and 
            st.get_option('server.headless') and 
            'streamlit.app' in str(st.secrets.get("REDIRECT_URI", ""))):
            redirect_uri = st.secrets.get("REDIRECT_URI", "https://your-app.streamlit.app/")
        elif 'localhost' in str(st.secrets.get("REDIRECT_URI", "")) or 'localhost' in os.environ.get("HOST", ""):
            redirect_uri = "http://localhost:8501/"
        else:
            redirect_uri = st.secrets.get("REDIRECT_URI", "http://localhost:8501/")
    except:
        redirect_uri = st.secrets.get("REDIRECT_URI", "http://localhost:8501/")
    
    # OAuth2.0パラメータ
    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'scope': 'email profile',
        'response_type': 'code',
        'access_type': 'offline',
        'include_granted_scopes': 'true',
        'prompt': 'select_account'
    }
    
    query_string = urllib.parse.urlencode(params)
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{query_string}"
    
    return auth_url

def get_google_user_info(code):
    """認証コードからユーザー情報を取得"""
    config = get_config()
    if not config["has_oauth"]:
        return None
    
    try:
        # リダイレクトURIの決定（認証時と同じロジック）
        try:
            if (hasattr(st, 'get_option') and 
                st.get_option('server.headless') and 
                'streamlit.app' in str(st.secrets.get("REDIRECT_URI", ""))):
                redirect_uri = st.secrets.get("REDIRECT_URI", "https://your-app.streamlit.app/")
            elif 'localhost' in str(st.secrets.get("REDIRECT_URI", "")) or 'localhost' in os.environ.get("HOST", ""):
                redirect_uri = "http://localhost:8501/"
            else:
                redirect_uri = st.secrets.get("REDIRECT_URI", "http://localhost:8501/")
        except:
            redirect_uri = st.secrets.get("REDIRECT_URI", "http://localhost:8501/")
        
        # アクセストークン取得
        token_url = "https://oauth2.googleapis.com/token"
        token_data = {
            "client_id": st.secrets["GOOGLE_CLIENT_ID"],
            "client_secret": st.secrets["GOOGLE_CLIENT_SECRET"],
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri
        }
        
        token_response = requests.post(token_url, data=token_data)
        
        if token_response.status_code != 200:
            st.error(f"❌ 認証エラー: {token_response.status_code}")
            st.error("Google認証の設定を確認してください。")
            return None
            
        token_json = token_response.json()
        
        if "access_token" not in token_json:
            st.error(f"❌ アクセストークンの取得に失敗しました")
            return None
            
        # ユーザー情報取得
        user_info_url = f"https://www.googleapis.com/oauth2/v2/userinfo?access_token={token_json['access_token']}"
        user_response = requests.get(user_info_url)
        
        if user_response.status_code != 200:
            st.error(f"❌ ユーザー情報の取得に失敗しました")
            return None
            
        return user_response.json()
        
    except Exception as e:
        st.error(f"❌ 認証エラー: {e}")
        return None

def check_user_permission(email, df_staff):
    """ユーザーの権限チェック"""
    valid_permissions = ["4. 承認者", "3. 利用者・承認者", "2. システム管理者", "5. 一般利用者"]
    user_data = df_staff[
        (df_staff["ログインID"] == email) & 
        (df_staff["権限"].isin(valid_permissions))
    ]
    
    if len(user_data) > 0:
        user_info = user_data.iloc[0]
        return True, user_info
    else:
        return False, None

# --- 認証情報の取得 ---
@st.cache_resource
def get_credentials():
    """Google Sheets認証情報を取得"""
    config = get_config()
    
    try:
        if config["has_gcp_account"]:
            credentials = service_account.Credentials.from_service_account_info(
                st.secrets["gcp_service_account"],
                scopes=["https://www.googleapis.com/auth/spreadsheets"]
            )
            return credentials
        else:
            json_paths = [
                "/Users/poca/hrmos/mineral-liberty-460106-m7-a24c4c78154f.json",
                "./service_account.json",
                os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
            ]
            
            for path in json_paths:
                if path and os.path.exists(path):
                    credentials = service_account.Credentials.from_service_account_file(
                        path,
                        scopes=["https://www.googleapis.com/auth/spreadsheets"]
                    )
                    return credentials
            
            st.error("Google Service Account認証情報が見つかりません。")
            st.info("Streamlit Secretsに gcp_service_account を設定してください。")
            return None
            
    except Exception as e:
        st.error(f"認証エラー: {e}")
        return None

# --- データ読み込み ---
@st.cache_data(ttl=300)
def load_spreadsheet_data():
    """スプレッドシートからデータを読み込み"""
    credentials = get_credentials()
    if not credentials:
        return None, None
    
    try:
        gspread_client = gspread.authorize(credentials)
        config = get_config()
        spreadsheet = gspread_client.open_by_url(config["sheet_url"])
        
        # 勤怠データの読み込み
        worksheet_kintai = spreadsheet.worksheet("勤怠確認シート(打刻管理)")
        headers_kintai_raw = worksheet_kintai.row_values(1)
        
        # ヘッダー重複回避
        headers_kintai = []
        seen = {}
        for col in headers_kintai_raw:
            if col in seen:
                seen[col] += 1
                headers_kintai.append(f"{col}_{seen[col]}")
            else:
                seen[col] = 0
                headers_kintai.append(col)
        
        records_kintai = worksheet_kintai.get_all_values()[1:]
        df_kintai = pd.DataFrame(records_kintai, columns=headers_kintai)
        df_kintai = df_kintai[df_kintai["社員番号"].str.strip() != ""]
        
        # 社員一覧の読み込み
        worksheet_staff = spreadsheet.worksheet("社員一覧")
        df_staff = pd.DataFrame(worksheet_staff.get_all_records())
        
        return df_kintai, df_staff
        
    except Exception as e:
        st.error(f"スプレッドシート読み込みエラー: {e}")
        st.info("スプレッドシートの設定を確認してください。")
        return None, None

# --- ユーザーフィルタリング関数 ---
def apply_user_filter(merged, user_permission, current_user_fullname, current_user_login_id, current_user_employee_id):
    """ユーザー権限に基づくデータフィルタリング"""
    
    if user_permission == "2. システム管理者":
        return merged.copy()
        
    elif user_permission in ["4. 承認者", "3. 利用者・承認者"]:
        return merged[
            (merged["承認者"] == current_user_login_id) |
            (merged["承認者"] == current_user_fullname) |
            (merged["承認者フルネーム"] == current_user_fullname)
        ]
        
    elif user_permission == "5. 一般利用者":
        merged_clean = merged.copy()
        merged_clean["社員番号"] = merged_clean["社員番号"].astype(str).str.strip()
        current_user_employee_id_clean = str(current_user_employee_id).strip()
        
        conditions = (merged_clean["社員番号"] == current_user_employee_id_clean)
        
        if "ログインID" in merged_clean.columns:
            merged_clean["ログインID"] = merged_clean["ログインID"].astype(str).str.strip()
            current_user_login_id_clean = str(current_user_login_id).strip()
            login_conditions = (merged_clean["ログインID"] == current_user_login_id_clean)
            conditions = conditions | login_conditions
        
        return merged_clean[conditions]
    
    else:
        return merged.iloc[0:0]

# --- 認証システム ---
def handle_authentication():
    """認証処理"""
    config = get_config()
    
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    
    if st.session_state.authenticated:
        return True
    
    # OAuth認証の処理
    query_params = st.query_params
    if "code" in query_params and config["has_oauth"]:
        code = query_params["code"]
        
        with st.spinner("認証中..."):
            user_info = get_google_user_info(code)
        
        if user_info and "email" in user_info:
            with st.spinner("ユーザー権限を確認中..."):
                df_kintai, df_staff = load_spreadsheet_data()
                
            if df_staff is not None:
                has_permission, staff_info = check_user_permission(user_info["email"], df_staff)
                
                if has_permission:
                    st.session_state.authenticated = True
                    st.session_state.user_info = staff_info.to_dict()
                    st.session_state.user_email = user_info["email"]
                    surname = str(staff_info.get('姓', '')).strip()
                    given_name = str(staff_info.get('名', '')).strip()
                    st.session_state.user_name = f"{surname}{given_name}"
                    
                    st.query_params.clear()
                    st.success("ログインに成功しました！")
                    st.rerun()
                else:
                    st.error("❌ アクセス権限がありません")
                    st.error("権限が設定されているメールアドレスでログインしてください。")
                    
                    if st.button("ログイン画面に戻る"):
                        st.query_params.clear()
                        st.rerun()
                    st.stop()
            else:
                st.error("データの読み込みに失敗しました。")
                st.stop()
        else:
            st.error("❌ 認証に失敗しました")
            
            if st.button("ログイン画面に戻る"):
                st.query_params.clear()
                st.rerun()
            st.stop()
    
    # ログイン画面
    st.title("🔐 勤怠確認チェックツール")
    st.markdown("---")
    
    # 設定状況の表示
    status_cols = st.columns(3)
    with status_cols[0]:
        if config["has_secrets"]:
            st.success("✅ Streamlit Secrets")
        else:
            st.error("❌ Streamlit Secrets")
    
    with status_cols[1]:
        if config["has_gcp_account"]:
            st.success("✅ Google Service Account")
        else:
            st.error("❌ Google Service Account")
    
    with status_cols[2]:
        if config["has_oauth"]:
            st.success("✅ Google OAuth")
        else:
            st.error("❌ Google OAuth")
    
    # データ接続確認
    with st.spinner("データ接続を確認中..."):
        df_kintai, df_staff = load_spreadsheet_data()
    
    if df_staff is None:
        st.error("❌ データの読み込みに失敗しました")
        st.stop()
    else:
        st.success("✅ データ接続成功")
    
    # 認証方式の選択
    st.markdown("### 🔑 ログイン")
    
    # OAuth認証
    if config["has_oauth"]:
        auth_url = get_google_auth_url()
        if auth_url:
            st.markdown("#### Google アカウント認証")
            st.info("下記のリンクをクリックしてGoogleアカウントでログインしてください。")
            
            # メインの認証リンク（Googleスタイル）
            st.markdown(f"""
            <div style="text-align: center; margin: 20px 0;">
                <a href="{auth_url}" target="_blank" style="
                    background-color: #4285f4;
                    color: white;
                    text-decoration: none;
                    padding: 12px 24px;
                    font-size: 16px;
                    border-radius: 4px;
                    display: inline-flex;
                    align-items: center;
                    gap: 8px;
                    max-width: 300px;
                    width: 100%;
                    justify-content: center;
                    font-weight: 500;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.2);
                    transition: background-color 0.3s;
                " onmouseover="this.style.backgroundColor='#3367d6'" 
                   onmouseout="this.style.backgroundColor='#4285f4'">
                    🔐 Googleでログイン
                </a>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown("✅ 認証完了後、自動的にこのページに戻ります")
            st.markdown("---")
    
    # 開発モード
    if config["development_mode"]:
        st.markdown("#### 🛠️ 開発モード: ユーザー選択")
        st.warning("⚠️ 本番環境ではこの選択肢は表示されません")
        
        valid_permissions = ["4. 承認者", "3. 利用者・承認者", "2. システム管理者", "5. 一般利用者"]
        
        if "権限" not in df_staff.columns:
            st.error("社員一覧に「権限」列が見つかりません。")
            st.stop()
        
        authorized_users = df_staff[df_staff["権限"].isin(valid_permissions)]
        
        if len(authorized_users) == 0:
            st.error("権限のあるユーザーが見つかりません。")
            st.stop()
        
        user_options = ["選択してください"]
        user_data = {}
        
        for _, user in authorized_users.iterrows():
            surname = str(user.get('姓', '')).strip()
            given_name = str(user.get('名', '')).strip()
            name = f"{surname}{given_name}" if surname or given_name else "名前なし"
            login_id = str(user.get('ログインID', '')).strip()
            permission = str(user.get('権限', '')).strip()
            
            display_text = f"{name} ({login_id}) - {permission}"
            user_options.append(display_text)
            user_data[display_text] = user.to_dict()
        
        selected_user = st.selectbox("ログインするユーザーを選択", user_options)
        
        if selected_user != "選択してください":
            if st.button("ログイン", type="primary"):
                user_info = user_data[selected_user]
                
                st.session_state.authenticated = True
                st.session_state.user_info = user_info
                st.session_state.user_email = user_info.get('ログインID', '')
                surname = str(user_info.get('姓', '')).strip()
                given_name = str(user_info.get('名', '')).strip()
                st.session_state.user_name = f"{surname}{given_name}"
                
                st.success("ログインしました！")
                st.rerun()
    
    return False

# --- メインアプリケーション ---
def main_app():
    """メインアプリケーション"""
    
    # データ読み込み
    df_kintai, df_staff = load_spreadsheet_data()
    if df_kintai is None or df_staff is None:
        st.error("データの読み込みに失敗しました。")
        return
    
    # データ整形
    if "第一承認者" in df_staff.columns:
        df_staff_with_fullname = df_staff.copy()
        df_staff_with_fullname["承認者フルネーム"] = df_staff_with_fullname["姓"].astype(str) + df_staff_with_fullname["名"].astype(str)
        
        merged = pd.merge(df_kintai, df_staff[["社員番号", "第一承認者"]], on="社員番号", how="left")
        merged = merged.rename(columns={"第一承認者": "承認者"})
        merged = pd.merge(merged, df_staff_with_fullname[["社員番号", "承認者フルネーム"]], on="社員番号", how="left")
    else:
        st.warning("社員一覧に「第一承認者」列が見つかりません。")
        merged = df_kintai.copy()
        merged["承認者"] = ""
        merged["承認者フルネーム"] = ""
    
    # 権限に基づくフィルタリング
    user_info = st.session_state.user_info
    user_permission = user_info.get("権限", "")
    
    current_user_fullname = st.session_state.user_name
    current_user_login_id = user_info.get("ログインID", "")
    current_user_employee_id = user_info.get("社員番号", "")
    
    filtered = apply_user_filter(
        merged, 
        user_permission, 
        current_user_fullname, 
        current_user_login_id, 
        current_user_employee_id
    )
    
    # UI
    st.markdown("""
    <style>
        .user-info {
            background-color: #f0f2f6; padding: 1rem;
            border-radius: 0.5rem; margin-bottom: 1rem;
        }
        .header-box {
            font-size: 20px; font-weight: bold; padding: 0.5rem;
            display: inline-block; margin-bottom: 1rem;
        }
        /* スマホ対応：データフレームの行番号を非表示 */
        .stDataFrame div[data-testid="stDataFrameResizable"] > div > div > div > div > div:first-child {
            display: none !important;
        }
        /* データフレームの列幅調整 */
        .stDataFrame {
            font-size: 14px;
        }
        /* スマホ向けレスポンシブ調整 */
        @media (max-width: 768px) {
            .stDataFrame {
                font-size: 12px;
            }
            .user-info {
                font-size: 14px;
                padding: 0.8rem;
            }
            .header-box {
                font-size: 18px;
            }
        }
    </style>
    """, unsafe_allow_html=True)
    
    # ヘッダー
    col1, col2 = st.columns([3, 1])
    with col1:
        st.title("📊 勤怠確認チェックツール")
    with col2:
        if st.button("🚪 ログアウト"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.query_params.clear()
            st.rerun()
    
    # ユーザー情報表示
    st.markdown(f"""
    <div class='user-info'>
        <strong>👤 ログインユーザー:</strong> {st.session_state.user_name} ({st.session_state.user_email})<br>
        <strong>🔑 権限:</strong> {user_permission}
    </div>
    """, unsafe_allow_html=True)
    
    # データ表示
    display_columns = [
        "社員番号", "名前", "休日出勤", "有休日数", "欠勤日数", "出勤時間",
        "総残業時間", "規定残業時間", "規定残業超過分", "深夜残業時間",
        "60時間超過残業", "打刻ズレ", "勤怠マイナス分"
    ]
    
    available_columns = [col for col in display_columns if col in filtered.columns]
    
    if len(filtered) > 0:
        if user_permission == "2. システム管理者":
            permission_label = "全スタッフ"
        elif user_permission in ["4. 承認者", "3. 利用者・承認者"]:
            permission_label = "承認対象スタッフ"
        elif user_permission == "5. 一般利用者":
            permission_label = "自分の勤怠データ"
        else:
            permission_label = "表示データ"
            
        st.markdown(f"<div class='header-box'>📋 {permission_label}: {len(filtered)}名</div>", unsafe_allow_html=True)
        
        if available_columns:
            display_df = filtered[available_columns]
            
            # スマホ対応：社員番号と名前を固定列として表示するためのデータフレーム設定
            st.dataframe(
                display_df,
                use_container_width=True,
                hide_index=True,  # これで行番号（インデックス）を非表示にする
                column_config={
                    "社員番号": st.column_config.TextColumn(
                        "社員番号",
                        width="small",
                        pinned="left"  # 左側に固定
                    ),
                    "名前": st.column_config.TextColumn(
                        "名前", 
                        width="medium",
                        pinned="left"  # 左側に固定
                    ),
                    "休日出勤": st.column_config.TextColumn("休日出勤", width="small"),
                    "有休日数": st.column_config.TextColumn("有休日数", width="small"),
                    "欠勤日数": st.column_config.TextColumn("欠勤日数", width="small"),
                    "出勤時間": st.column_config.TextColumn("出勤時間", width="small"),
                    "総残業時間": st.column_config.TextColumn("総残業時間", width="small"),
                    "規定残業時間": st.column_config.TextColumn("規定残業時間", width="small"),
                    "規定残業超過分": st.column_config.TextColumn("規定残業超過分", width="small"),
                    "深夜残業時間": st.column_config.TextColumn("深夜残業時間", width="small"),
                    "60時間超過残業": st.column_config.TextColumn("60時間超過残業", width="small"),
                    "打刻ズレ": st.column_config.TextColumn("打刻ズレ", width="small"),
                    "勤怠マイナス分": st.column_config.TextColumn("勤怠マイナス分", width="small")
                }
            )
        else:
            st.warning("表示可能な列が見つかりません。")
    else:
        if user_permission == "2. システム管理者":
            st.info("📋 表示可能なデータがありません。")
        elif user_permission in ["4. 承認者", "3. 利用者・承認者"]:
            st.info("📋 承認対象のスタッフがいません。第一承認者として割り当てられているスタッフのデータのみ表示されます。")
        elif user_permission == "5. 一般利用者":
            st.info("📋 あなたの勤怠データが見つかりません。")
        else:
            st.info("📋 表示可能なデータがありません。")

# --- メイン実行 ---
if __name__ == "__main__":
    if handle_authentication():
        main_app()
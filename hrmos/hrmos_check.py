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
        "development_mode": False,  # デフォルトは開発モード
        "sheet_url": "https://docs.google.com/spreadsheets/d/1Ymt2OrvY2dKFs9puCX8My7frS_BS1sg3Yev3BLQm9xQ/edit",
        "has_secrets": False,
        "has_gcp_account": False,
        "has_oauth": False
    }
    
    # Streamlit Secretsの確認
    try:
        if hasattr(st, 'secrets') and st.secrets:
            config["has_secrets"] = True
            config["development_mode"] = st.secrets.get("DEVELOPMENT_MODE", True)
            
            # Google Service Accountの確認
            if "gcp_service_account" in st.secrets:
                config["has_gcp_account"] = True
            
            # Google OAuth設定の確認
            if all(key in st.secrets for key in ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "REDIRECT_URI"]):
                config["has_oauth"] = True
    except Exception:
        pass
    
    return config

# --- OAuth認証関数 ---
def get_google_auth_url():
    """Google OAuth認証URLを生成"""
    config = get_config()
    if not config["has_oauth"]:
        return None
    
    import urllib.parse
    
    client_id = st.secrets["GOOGLE_CLIENT_ID"]
    redirect_uri = st.secrets["REDIRECT_URI"]
    
    # OAuth2.0パラメータ
    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'scope': 'email profile',
        'response_type': 'code',
        'access_type': 'offline',
        'include_granted_scopes': 'true'
    }
    
    # URLエンコード
    query_string = urllib.parse.urlencode(params)
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{query_string}"
    
    return auth_url

def get_google_user_info(code):
    """認証コードからユーザー情報を取得"""
    config = get_config()
    if not config["has_oauth"]:
        return None
    
    try:
        # アクセストークン取得
        token_url = "https://oauth2.googleapis.com/token"
        token_data = {
            "client_id": st.secrets["GOOGLE_CLIENT_ID"],
            "client_secret": st.secrets["GOOGLE_CLIENT_SECRET"],
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": st.secrets["REDIRECT_URI"]
        }
        token_response = requests.post(token_url, data=token_data)
        token_json = token_response.json()
        
        if "access_token" not in token_json:
            return None
            
        # ユーザー情報取得
        user_info_url = f"https://www.googleapis.com/oauth2/v2/userinfo?access_token={token_json['access_token']}"
        user_response = requests.get(user_info_url)
        return user_response.json()
    except Exception as e:
        st.error(f"認証エラー: {e}")
        return None

def check_user_permission(email, df_staff):
    """ユーザーの権限チェック"""
    valid_permissions = ["4. 承認者", "3. 利用者・承認者", "2. システム管理者"]
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
            # Streamlit Secretsからサービスアカウント情報を取得
            credentials = service_account.Credentials.from_service_account_info(
                st.secrets["gcp_service_account"],
                scopes=["https://www.googleapis.com/auth/spreadsheets"]
            )
            return credentials
        else:
            # 代替手段: 環境変数やローカルファイル
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
            
            # どの方法でも認証情報が取得できない場合
            st.error("Google Service Account認証情報が見つかりません。")
            st.info("以下のいずれかの方法で設定してください:")
            st.code("""
1. Streamlit Secrets設定:
   [gcp_service_account]
   type = "service_account"
   project_id = "your-project-id"
   private_key = "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n"
   client_email = "your-service-account@project.iam.gserviceaccount.com"
   # ... 他の設定

2. 環境変数:
   GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

3. ローカルファイル:
   ./service_account.json
            """)
            return None
            
    except Exception as e:
        st.error(f"認証エラー: {e}")
        return None

# --- データ読み込み ---
@st.cache_data(ttl=300)  # 5分間キャッシュ
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
        st.info("以下を確認してください:")
        st.info("1. スプレッドシートのURLが正しいか")
        st.info("2. サービスアカウントがスプレッドシートに共有されているか")
        st.info("3. 「勤怠確認シート(打刻管理)」シートと「社員一覧」シートが存在するか")
        return None, None

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
        user_info = get_google_user_info(code)
        
        if user_info and "email" in user_info:
            # データ読み込み
            df_kintai, df_staff = load_spreadsheet_data()
            if df_staff is not None:
                has_permission, staff_info = check_user_permission(user_info["email"], df_staff)
                
                if has_permission:
                    # セッション状態設定
                    st.session_state.authenticated = True
                    st.session_state.user_info = staff_info.to_dict()
                    st.session_state.user_email = user_info["email"]
                    surname = str(staff_info.get('姓', '')).strip()
                    given_name = str(staff_info.get('名', '')).strip()
                    st.session_state.user_name = f"{surname}{given_name}"
                    
                    # URLパラメータをクリア
                    st.query_params.clear()
                    st.rerun()
                else:
                    st.error("アクセス権限がありません。権限が設定されているメールアドレスでログインしてください。")
                    st.stop()
        else:
            st.error("認証に失敗しました。")
            st.stop()
    
    # ログイン画面
    st.title("勤怠確認チェックツール")
    st.markdown("---")
    
    # 設定状況の表示
    if config["development_mode"]:
        st.info("🔧 開発モードで動作中")
    
    if not config["has_secrets"]:
        st.warning("⚠️ Streamlit Secrets が設定されていません")
    
    if not config["has_gcp_account"]:
        st.warning("⚠️ Google Service Account が設定されていません")
    
    if not config["has_oauth"]:
        st.warning("⚠️ Google OAuth が設定されていません")
    
    # データ読み込みテスト
    with st.spinner("データ読み込み中..."):
        df_kintai, df_staff = load_spreadsheet_data()
    
    if df_staff is None:
        st.error("データの読み込みに失敗しました。設定を確認してください。")
        st.stop()
    
    # 認証方式の選択
    st.markdown("### ログイン方式を選択")
    
    # OAuth認証が利用可能な場合
    if config["has_oauth"]:
        auth_url = get_google_auth_url()
        if auth_url:
            st.markdown("#### Google アカウント認証")
            
            # 方法1: セッション状態を使用したリダイレクト管理
            if "redirect_initiated" not in st.session_state:
                st.session_state.redirect_initiated = False
            
            if st.button("🔐 Googleアカウントでログイン", type="primary", use_container_width=True):
                st.session_state.redirect_initiated = True
                st.rerun()
            
            # リダイレクトの実行
            if st.session_state.redirect_initiated:
                st.info("Googleログイン画面にリダイレクトしています...")
                # meta refreshを使用したリダイレクト
                redirect_html = f"""
                <meta http-equiv="refresh" content="0; url={auth_url}">
                <script>
                    window.location.href = "{auth_url}";
                </script>
                """
                st.markdown(redirect_html, unsafe_allow_html=True)
                
                # リダイレクトが失敗した場合のフォールバック
                time.sleep(2)
                st.markdown(f"### 自動リダイレクトが動作しない場合は、[こちらをクリック]({auth_url})してください。")
                st.stop()
            
            # 方法2: 直接リンク（常に表示）
            st.markdown("---")
            st.markdown("**手動でログインする場合:**")
            st.markdown(f"[Googleアカウントでログインする]({auth_url})")
            st.caption("↑自動リダイレクトが動作しない場合はこちらをクリックしてください")
            st.markdown("---")
    
    # 開発モード: ユーザー選択（開発モードでのみ表示）
    if config["development_mode"]:
        st.markdown("#### 開発モード: ユーザー選択")
        st.info("💡 本番環境ではこの選択肢は表示されません")
        
        # 権限のあるユーザーを取得
        valid_permissions = ["4. 承認者", "3. 利用者・承認者", "2. システム管理者"]
        
        if "権限" not in df_staff.columns:
            st.error("社員一覧に「権限」列が見つかりません。")
            st.info("必要な列: ログインID(B列), 社員番号(D列), 姓(E列), 名(F列), 権限(BL列)")
            st.stop()
        
        authorized_users = df_staff[df_staff["権限"].isin(valid_permissions)]
        
        if len(authorized_users) == 0:
            st.error("権限のあるユーザーが見つかりません。")
            st.info("社員一覧の権限列に以下のいずれかが設定されているユーザーが必要です:")
            for perm in valid_permissions:
                st.info(f"- {perm}")
            st.stop()
        
        # ユーザー選択
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
                
                # セッション状態設定
                st.session_state.authenticated = True
                st.session_state.user_info = user_info
                st.session_state.user_email = user_info.get('ログインID', '')
                surname = str(user_info.get('姓', '')).strip()
                given_name = str(user_info.get('名', '')).strip()
                st.session_state.user_name = f"{surname}{given_name}"
                
                st.success("ログインしました！")
                st.rerun()
    
    # 設定ガイド
    if not config["has_oauth"]:
        st.markdown("---")
        st.markdown("#### Google OAuth設定")
        st.info("本格的なGoogle認証を有効にするには、Streamlit Secretsに以下を追加してください:")
        st.code("""
GOOGLE_CLIENT_ID = "your-client-id"
GOOGLE_CLIENT_SECRET = "your-client-secret"
REDIRECT_URI = "https://your-app.streamlit.app/"
        """)
    
    return False

# --- 固定ヘッダー・固定列テーブル作成関数 ---
def create_fixed_table(df, fixed_columns=['名前']):
    """
    固定ヘッダーと固定列を持つスクロール可能なテーブルを作成
    """
    if df.empty:
        return ""
    
    # 固定列とその他の列を分離
    fixed_cols = [col for col in fixed_columns if col in df.columns]
    other_cols = [col for col in df.columns if col not in fixed_cols]
    
    # CSSスタイル
    css = """
    <style>
        .fixed-table-container {
            position: relative;
            max-height: 600px;
            overflow: auto;
            border: 1px solid #ddd;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .fixed-table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            font-size: 14px;
        }
        
        .fixed-table th,
        .fixed-table td {
            border: 1px solid #e0e0e0;
            padding: 8px 12px;
            text-align: left;
            white-space: nowrap;
        }
        
        .fixed-table th {
            background-color: #f8f9fa;
            font-weight: bold;
            position: sticky;
            top: 0;
            z-index: 10;
            box-shadow: 0 2px 2px -1px rgba(0, 0, 0, 0.1);
        }
        
        .fixed-table .fixed-col {
            position: sticky;
            left: 0;
            background-color: #ffffff;
            z-index: 5;
            box-shadow: 2px 0 2px -1px rgba(0, 0, 0, 0.1);
        }
        
        .fixed-table .fixed-col.header {
            z-index: 11;
            background-color: #f8f9fa;
        }
        
        .fixed-table tbody tr:nth-child(even) {
            background-color: #f9f9f9;
        }
        
        .fixed-table tbody tr:hover {
            background-color: #e3f2fd;
        }
        
        .fixed-table .fixed-col:hover {
            background-color: #e3f2fd !important;
        }
        
        .fixed-table tbody tr:nth-child(even) .fixed-col {
            background-color: #f9f9f9;
        }
        
        .fixed-table tbody tr:hover .fixed-col {
            background-color: #e3f2fd !important;
        }
        
        /* 数値セルの右寄せ */
        .fixed-table .numeric {
            text-align: right;
        }
        
        /* 警告表示のための色分け */
        .fixed-table .warning {
            background-color: #fff3cd !important;
            color: #856404;
        }
        
        .fixed-table .error {
            background-color: #f8d7da !important;
            color: #721c24;
        }
    </style>
    """
    
    # テーブルHTML作成
    html = css + '<div class="fixed-table-container"><table class="fixed-table">'
    
    # ヘッダー作成
    html += '<thead><tr>'
    
    # 固定列のヘッダー
    for col in fixed_cols:
        html += f'<th class="fixed-col header">{col}</th>'
    
    # その他の列のヘッダー
    for col in other_cols:
        html += f'<th>{col}</th>'
    
    html += '</tr></thead>'
    
    # ボディ作成
    html += '<tbody>'
    
    for _, row in df.iterrows():
        html += '<tr>'
        
        # 固定列のデータ
        for col in fixed_cols:
            value = str(row[col]) if pd.notna(row[col]) else ''
            html += f'<td class="fixed-col">{value}</td>'
        
        # その他の列のデータ
        for col in other_cols:
            value = str(row[col]) if pd.notna(row[col]) else ''
            
            # 数値列の判定と右寄せ
            css_class = ""
            if col in ['休日出勤', '有休日数', '欠勤日数', '総残業時間', '規定残業時間', 
                      '規定残業超過分', '深夜残業時間', '60時間超過残業', '打刻ズレ', '勤怠マイナス分']:
                css_class = "numeric"
                
                # 警告値の色分け
                try:
                    num_value = float(value) if value and value != '' else 0
                    if col in ['欠勤日数', '打刻ズレ', '勤怠マイナス分'] and num_value > 0:
                        css_class += " warning"
                    elif col in ['規定残業超過分', '60時間超過残業'] and num_value > 0:
                        css_class += " error"
                except:
                    pass
            
            class_attr = f' class="{css_class}"' if css_class else ''
            html += f'<td{class_attr}>{value}</td>'
        
        html += '</tr>'
    
    html += '</tbody></table></div>'
    
    return html

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
        # 社員一覧で姓名を結合した承認者名を作成
        df_staff_with_fullname = df_staff.copy()
        df_staff_with_fullname["承認者フルネーム"] = df_staff_with_fullname["姓"].astype(str) + df_staff_with_fullname["名"].astype(str)
        
        # 勤怠データとマージ
        merged = pd.merge(df_kintai, df_staff[["社員番号", "第一承認者"]], on="社員番号", how="left")
        merged = merged.rename(columns={"第一承認者": "承認者"})
        
        # 承認者フルネーム情報も追加
        merged = pd.merge(merged, df_staff_with_fullname[["社員番号", "承認者フルネーム"]], on="社員番号", how="left")
    else:
        st.warning("社員一覧に「第一承認者」列が見つかりません。")
        merged = df_kintai.copy()
        merged["承認者"] = ""
        merged["承認者フルネーム"] = ""
    
    # 権限に基づくフィルタリング
    user_info = st.session_state.user_info
    user_permission = user_info.get("権限", "")
    
    # 現在ログインしているユーザーのフルネーム
    current_user_fullname = st.session_state.user_name
    
    if user_permission == "2. システム管理者":
        filtered = merged.copy()
    elif user_permission in ["4. 承認者", "3. 利用者・承認者"]:
        # フルネームまたはログインIDで承認対象をフィルタリング
        user_login_id = user_info.get("ログインID", "")
        filtered = merged[
            (merged["承認者"] == user_login_id) |  # ログインIDでの一致
            (merged["承認者"] == current_user_fullname) |  # フルネームでの一致
            (merged["承認者フルネーム"] == current_user_fullname)  # 承認者フルネームでの一致
        ]
    else:
        filtered = merged.iloc[0:0]
    
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
        .auth-method {
            background-color: #e8f4fd; padding: 0.5rem;
            border-radius: 0.25rem; margin-bottom: 1rem; font-size: 0.9em;
        }
    </style>
    """, unsafe_allow_html=True)
    
    # ヘッダー
    col1, col2 = st.columns([3, 1])
    with col1:
        st.title("勤怠確認チェックツール")
    with col2:
        if st.button("ログアウト"):
            # ログアウト時にredirect_initiatedもリセット
            for key in ['authenticated', 'redirect_initiated']:
                if key in st.session_state:
                    del st.session_state[key]
            st.query_params.clear()  # URLパラメータをクリア
            st.rerun()
    
    # 認証方法の表示
    auth_method = "Google OAuth認証" if "code" in st.query_params else "開発モード"
    st.markdown(f"<div class='auth-method'>認証方法: {auth_method}</div>", unsafe_allow_html=True)
    
    # ユーザー情報表示
    st.markdown(f"""
    <div class='user-info'>
        <strong>ログインユーザー:</strong> {st.session_state.user_name} ({st.session_state.user_email})<br>
        <strong>権限:</strong> {user_permission}
    </div>
    """, unsafe_allow_html=True)
    
    # 開発モード時のデバッグ情報
    config = get_config()
    if config["development_mode"] and user_permission in ["4. 承認者", "3. 利用者・承認者"]:
        with st.expander("🔍 デバッグ情報（承認者マッチング）"):
            st.write(f"**現在のユーザー名:** {current_user_fullname}")
            st.write(f"**ログインID:** {user_info.get('ログインID', '')}")
            
            # 承認者として設定されているデータの確認
            approval_matches = merged[
                (merged["承認者"] == user_info.get('ログインID', '')) |
                (merged["承認者"] == current_user_fullname) |
                (merged["承認者フルネーム"] == current_user_fullname)
            ]
            
            if len(approval_matches) > 0:
                st.write(f"**承認対象者数:** {len(approval_matches)}名")
                st.write("**承認対象者一覧:**")
                debug_display = approval_matches[["社員番号", "名前", "承認者", "承認者フルネーム"]].head(10)
                st.dataframe(debug_display)
            else:
                st.write("**承認対象者:** なし")
                st.write("**確認項目:**")
                st.write("- 勤怠データの「第一承認者」列にあなたの名前またはログインIDが設定されているか")
                st.write("- 姓名の表記が一致しているか（姓名間のスペースなど）")
    
    # データ表示
    display_columns = [
        "社員番号", "名前", "休日出勤", "有休日数", "欠勤日数", "出勤時間",
        "総残業時間", "規定残業時間", "規定残業超過分", "深夜残業時間",
        "60時間超過残業", "打刻ズレ", "勤怠マイナス分"
    ]
    
    # 存在する列のみ表示
    available_columns = [col for col in display_columns if col in filtered.columns]
    
    if len(filtered) > 0:
        permission_label = "全スタッフ" if user_permission == "2. システム管理者" else "承認対象スタッフ"
        st.markdown(f"<div class='header-box'>{permission_label}: {len(filtered)}名</div>", unsafe_allow_html=True)
        
        if available_columns:
            # 固定ヘッダー・固定列テーブルを使用してデータを表示
            display_df = filtered[available_columns]
            
            # 固定列を設定（社員番号と名前を固定）
            fixed_columns = ["社員番号", "名前"]
            available_fixed_columns = [col for col in fixed_columns if col in display_df.columns]
            
            # テーブルHTML生成
            table_html = create_fixed_table(display_df, fixed_columns=available_fixed_columns)
            
            # テーブル表示
            st.markdown(table_html, unsafe_allow_html=True)
            
            # 補足情報
            st.markdown("---")
            st.markdown("**テーブル操作ガイド:**")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("- **縦スクロール**: マウスホイールまたはスクロールバー")
                st.markdown("- **横スクロール**: Shift + マウスホイールまたは横スクロールバー")
            with col2:
                st.markdown("- **固定列**: 社員番号・名前は常に表示")
                st.markdown("- **色分け**: 🟡警告値（欠勤等） 🔴エラー値（超過残業等）")
        else:
            st.warning("表示可能な列が見つかりません。")
    else:
        if user_permission in ["4. 承認者", "3. 利用者・承認者"]:
            st.info("承認対象のスタッフがいません。第一承認者として割り当てられているスタッフのデータのみ表示されます。")
        else:
            st.info("表示可能なデータがありません。")

# --- メイン実行 ---
if __name__ == "__main__":
    if handle_authentication():
        main_app()
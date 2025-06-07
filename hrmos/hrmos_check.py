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
    
    # 現在のURLを正確に取得
    try:
        # Streamlit Cloud の環境変数から取得
        if "STREAMLIT_SHARING_MODE" in os.environ or "streamlit.app" in os.environ.get("HOST", ""):
            # Streamlit Cloud環境
            app_name = os.environ.get("STREAMLIT_APP_NAME", "")
            if app_name:
                redirect_uri = f"https://{app_name}.streamlit.app/"
            else:
                # フォールバック: secretsから取得
                redirect_uri = st.secrets.get("REDIRECT_URI", "https://your-app.streamlit.app/")
        else:
            # ローカル環境
            redirect_uri = "http://localhost:8501/"
    except:
        # エラー時のフォールバック
        redirect_uri = st.secrets.get("REDIRECT_URI", "http://localhost:8501/")
    
    # デバッグ情報表示（開発モードのみ）
    if config.get("development_mode", False):
        st.info(f"🔍 デバッグ: 使用するリダイレクトURI: {redirect_uri}")
    
    # OAuth2.0パラメータ
    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'scope': 'email profile',
        'response_type': 'code',
        'access_type': 'offline',
        'include_granted_scopes': 'true',
        'prompt': 'select_account'  # アカウント選択を強制
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
        # 現在のURLを正確に取得（認証時と同じロジック）
        try:
            if "STREAMLIT_SHARING_MODE" in os.environ or "streamlit.app" in os.environ.get("HOST", ""):
                # Streamlit Cloud環境
                app_name = os.environ.get("STREAMLIT_APP_NAME", "")
                if app_name:
                    redirect_uri = f"https://{app_name}.streamlit.app/"
                else:
                    redirect_uri = st.secrets.get("REDIRECT_URI", "https://your-app.streamlit.app/")
            else:
                # ローカル環境
                redirect_uri = "http://localhost:8501/"
        except:
            redirect_uri = st.secrets.get("REDIRECT_URI", "http://localhost:8501/")
        
        # デバッグ情報
        if config.get("development_mode", False):
            st.info(f"🔍 デバッグ: トークン取得用リダイレクトURI: {redirect_uri}")
        
        # アクセストークン取得
        token_url = "https://oauth2.googleapis.com/token"
        token_data = {
            "client_id": st.secrets["GOOGLE_CLIENT_ID"],
            "client_secret": st.secrets["GOOGLE_CLIENT_SECRET"],
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri
        }
        
        # デバッグ情報
        if config.get("development_mode", False):
            debug_data = token_data.copy()
            debug_data["client_secret"] = "***隠し***"
            st.info(f"🔍 デバッグ: トークンリクエストデータ: {debug_data}")
        
        token_response = requests.post(token_url, data=token_data)
        
        if token_response.status_code != 200:
            st.error(f"❌ トークン取得エラー: {token_response.status_code}")
            st.error(f"レスポンス: {token_response.text}")
            st.error(f"使用したリダイレクトURI: {redirect_uri}")
            st.error("Google Cloud Console で以下を確認してください:")
            st.error(f"1. {redirect_uri} が承認済みリダイレクトURIに登録されているか")
            st.error("2. クライアントIDとシークレットが正しいか")
            return None
            
        token_json = token_response.json()
        
        if "access_token" not in token_json:
            st.error(f"❌ アクセストークンが見つかりません: {token_json}")
            return None
            
        # ユーザー情報取得
        user_info_url = f"https://www.googleapis.com/oauth2/v2/userinfo?access_token={token_json['access_token']}"
        user_response = requests.get(user_info_url)
        
        if user_response.status_code != 200:
            st.error(f"❌ ユーザー情報取得エラー: {user_response.status_code}")
            return None
            
        return user_response.json()
        
    except Exception as e:
        st.error(f"❌ 認証エラー: {e}")
        import traceback
        st.error(f"詳細: {traceback.format_exc()}")
        return None

def check_user_permission(email, df_staff):
    """ユーザーの権限チェック"""
    # 全ての権限レベルを許可（一般利用者も含む）
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

# --- ユーザーフィルタリング関数（修正版） ---
def apply_user_filter(merged, user_permission, current_user_fullname, current_user_login_id, current_user_employee_id):
    """ユーザー権限に基づくデータフィルタリング"""
    
    if user_permission == "2. システム管理者":
        # システム管理者：全データを表示
        return merged.copy()
        
    elif user_permission in ["4. 承認者", "3. 利用者・承認者"]:
        # 承認者：承認対象のスタッフのデータを表示
        return merged[
            (merged["承認者"] == current_user_login_id) |  # ログインIDでの一致
            (merged["承認者"] == current_user_fullname) |  # フルネームでの一致
            (merged["承認者フルネーム"] == current_user_fullname)  # 承認者フルネームでの一致
        ]
        
    elif user_permission == "5. 一般利用者":
        # データ型を統一してクリーニング
        merged_clean = merged.copy()
        merged_clean["社員番号"] = merged_clean["社員番号"].astype(str).str.strip()
        current_user_employee_id_clean = str(current_user_employee_id).strip()
        
        # 基本条件：社員番号での一致
        conditions = (merged_clean["社員番号"] == current_user_employee_id_clean)
        
        # ログインID列が存在する場合の追加条件
        if "ログインID" in merged_clean.columns:
            merged_clean["ログインID"] = merged_clean["ログインID"].astype(str).str.strip()
            current_user_login_id_clean = str(current_user_login_id).strip()
            login_conditions = (merged_clean["ログインID"] == current_user_login_id_clean)
            conditions = conditions | login_conditions
        
        return merged_clean[conditions]
    
    else:
        # 不明な権限の場合は空のデータフレームを返す
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
            # データ読み込み
            with st.spinner("ユーザー権限を確認中..."):
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
                    st.success("ログインに成功しました！")
                    st.rerun()
                else:
                    st.error("❌ アクセス権限がありません")
                    st.error("権限が設定されているメールアドレスでログインしてください。")
                    st.info(f"使用されたメールアドレス: {user_info['email']}")
                    
                    # ログイン画面に戻るボタン
                    if st.button("ログイン画面に戻る"):
                        st.query_params.clear()
                        st.rerun()
                    st.stop()
            else:
                st.error("データの読み込みに失敗しました。")
                st.stop()
        else:
            st.error("❌ 認証に失敗しました")
            st.info("もう一度ログインを試してください。")
            
            # ログイン画面に戻るボタン
            if st.button("ログイン画面に戻る"):
                st.query_params.clear()
                st.rerun()
            st.stop()
    
    # ログイン画面
    st.title("🔐 勤怠確認チェックツール")
    st.markdown("---")
    
    # 設定状況の表示
    if config["development_mode"]:
        st.info("🔧 開発モードで動作中")
    
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
    
    # データ読み込みテスト
    with st.spinner("データ接続を確認中..."):
        df_kintai, df_staff = load_spreadsheet_data()
    
    if df_staff is None:
        st.error("❌ データの読み込みに失敗しました")
        st.error("設定を確認してください。")
        st.stop()
    else:
        st.success("✅ データ接続成功")
    
    # 認証方式の選択
    st.markdown("### 🔑 ログイン方式を選択")
    
    # OAuth認証が利用可能な場合
    if config["has_oauth"]:
        auth_url = get_google_auth_url()
        if auth_url:
            st.markdown("#### Google アカウント認証")
            st.info("Googleアカウントでログインして認証を行います。")
            
            # デバッグ情報の表示
            if config["development_mode"]:
                st.markdown("##### 🔧 デバッグ情報")
                st.write(f"**Client ID:** {st.secrets.get('GOOGLE_CLIENT_ID', 'Not set')[:20]}...")
                st.write(f"**Client Secret:** {'設定済み' if st.secrets.get('GOOGLE_CLIENT_SECRET') else '未設定'}")
                
                # 現在のURL情報
                try:
                    # 環境変数の確認
                    st.write("**環境変数情報:**")
                    st.write(f"- STREAMLIT_SHARING_MODE: {os.environ.get('STREAMLIT_SHARING_MODE', '未設定')}")
                    st.write(f"- HOST: {os.environ.get('HOST', '未設定')}")
                    st.write(f"- STREAMLIT_APP_NAME: {os.environ.get('STREAMLIT_APP_NAME', '未設定')}")
                    
                    # 推奨するリダイレクトURI
                    st.write("**Google Cloud Console に登録すべきリダイレクトURI:**")
                    
                    # あなたのアプリのURLを特定
                    app_url = st.text_input("あなたのStreamlitアプリのURL", 
                                           placeholder="例: https://your-app-name.streamlit.app/",
                                           help="Streamlit CloudのアプリURLを入力してください")
                    
                    if app_url:
                        # 入力されたURLから推奨URIを生成
                        recommended_uris = [
                            app_url.rstrip('/') + '/',
                            app_url.rstrip('/')
                        ]
                    else:
                        # デフォルトの推奨URI
                        recommended_uris = [
                            "https://your-app-name.streamlit.app/",
                            "https://your-app-name.streamlit.app"
                        ]
                    
                    # ローカル開発用URI
                    recommended_uris.extend([
                        "http://localhost:8501/",
                        "http://localhost:8501",
                        "http://127.0.0.1:8501/",
                        "http://127.0.0.1:8501"
                    ])
                    
                    for uri in recommended_uris:
                        st.code(uri)
                        
                except Exception as e:
                    st.write(f"URL取得エラー: {e}")
            
            # 改善されたリンクベースの認証
            st.markdown(f"""
            <div style="text-align: center; margin: 2rem 0;">
                <a href="{auth_url}" target="_top" style="
                    display: inline-block;
                    background-color: #4285f4;
                    color: white;
                    padding: 12px 24px;
                    text-decoration: none;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 16px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.2);
                ">🔐 Googleアカウントでログイン</a>
            </div>
            """, unsafe_allow_html=True)
            
            st.caption("↑ クリックしてGoogleアカウントでログインしてください")
            
            # 重要な注意事項
            st.warning("⚠️ **重要**: このリンクをクリックする前に、Google Cloud Console で上記のリダイレクトURIがすべて登録されていることを確認してください。")
            
            # 追加のトラブルシューティング情報
            with st.expander("🔧 認証がうまくいかない場合"):
                st.markdown("""
                **手順1: Google Cloud Console の設定確認**
                1. [Google Cloud Console](https://console.cloud.google.com/) にアクセス
                2. 「APIとサービス」→「認証情報」
                3. 作成したOAuthクライアントIDを編集
                4. 上記のデバッグ情報に表示されたすべてのURIを「承認済みのリダイレクトURI」に追加
                
                **手順2: OAuth同意画面の設定**
                1. 「APIとサービス」→「OAuth同意画面」
                2. アプリがテストモードの場合、「テストユーザー」にログインするユーザーを追加
                3. または「本番環境に公開」をクリック
                
                **手順3: ブラウザのキャッシュクリア**
                1. ブラウザのキャッシュと Cookie をクリア
                2. シークレット/プライベートブラウジングで再試行
                
                **よくあるエラーと解決方法:**
                - **「接続が拒否されました」**: リダイレクトURIの設定不備
                - **「redirect_uri_mismatch」**: URIの完全一致が必要
                - **「unauthorized_client」**: OAuth同意画面の設定未完了
                - **「access_denied」**: ユーザーが認証を拒否、またはテストユーザー未追加
                """)
            
            st.markdown("---")
    
    # 開発モード: ユーザー選択（開発モードでのみ表示）
    if config["development_mode"]:
        st.markdown("#### 🛠️ 開発モード: ユーザー選択")
        st.warning("⚠️ 本番環境ではこの選択肢は表示されません")
        
        # 権限のあるユーザーを取得
        valid_permissions = ["4. 承認者", "3. 利用者・承認者", "2. システム管理者", "5. 一般利用者"]
        
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
        st.markdown("#### ⚙️ Google OAuth設定")
        st.info("本格的なGoogle認証を有効にするには、Streamlit Secretsに以下を追加してください:")
        st.code("""
GOOGLE_CLIENT_ID = "your-client-id"
GOOGLE_CLIENT_SECRET = "your-client-secret"
REDIRECT_URI = "https://your-app.streamlit.app/"
        """)
    
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
    current_user_login_id = user_info.get("ログインID", "")
    current_user_employee_id = user_info.get("社員番号", "")
    
    # 修正されたフィルタリング関数を使用
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
        .auth-method {
            background-color: #e8f4fd; padding: 0.5rem;
            border-radius: 0.25rem; margin-bottom: 1rem; font-size: 0.9em;
        }
    </style>
    """, unsafe_allow_html=True)
    
    # ヘッダー
    col1, col2 = st.columns([3, 1])
    with col1:
        st.title("📊 勤怠確認チェックツール")
    with col2:
        if st.button("🚪 ログアウト"):
            # セッション状態をクリア
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.query_params.clear()
            st.rerun()
    
    # 認証方法の表示
    auth_method = "Google OAuth認証" if "code" in st.query_params else "開発モード"
    st.markdown(f"<div class='auth-method'>🔐 認証方法: {auth_method}</div>", unsafe_allow_html=True)
    
    # ユーザー情報表示
    st.markdown(f"""
    <div class='user-info'>
        <strong>👤 ログインユーザー:</strong> {st.session_state.user_name} ({st.session_state.user_email})<br>
        <strong>🔑 権限:</strong> {user_permission}
    </div>
    """, unsafe_allow_html=True)
    
    # 開発モード時のデバッグ情報
    config = get_config()
    if config["development_mode"]:
        with st.expander("🔍 デバッグ情報"):
            st.write(f"**現在のユーザー名:** {current_user_fullname}")
            st.write(f"**ログインID:** {current_user_login_id}")
            st.write(f"**社員番号:** {current_user_employee_id}")
            st.write(f"**権限:** {user_permission}")
            
            if user_permission in ["4. 承認者", "3. 利用者・承認者"]:
                # 承認者として設定されているデータの確認
                approval_matches = merged[
                    (merged["承認者"] == current_user_login_id) |
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
            
            elif user_permission == "5. 一般利用者":
                st.write("**表示対象:** 自分のデータのみ")
                st.write(f"**フィルタリング条件:** 社員番号={current_user_employee_id}")
                
                if len(filtered) > 0:
                    st.write("**自分のデータ:**")
                    st.dataframe(filtered[["社員番号", "名前"]].head(1))
                else:
                    st.write("**注意:** 自分のデータが見つかりません")
                    st.write("**検索に使用した情報:**")
                    st.write(f"- 社員番号: '{current_user_employee_id}'")
                    st.write(f"- ログインID: '{current_user_login_id}'")
                    
                    st.write("**勤怠データ内の社員番号（最初の5件）:**")
                    sample_ids = merged["社員番号"].unique()[:5]
                    for sid in sample_ids:
                        st.write(f"- '{sid}'")
    
    # データ表示
    display_columns = [
        "社員番号", "名前", "休日出勤", "有休日数", "欠勤日数", "出勤時間",
        "総残業時間", "規定残業時間", "規定残業超過分", "深夜残業時間",
        "60時間超過残業", "打刻ズレ", "勤怠マイナス分"
    ]
    
    # 存在する列のみ表示
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
            # データをそのまま表示（一切の加工なし）
            display_df = filtered[available_columns]
            st.dataframe(display_df, use_container_width=True)
        else:
            st.warning("表示可能な列が見つかりません。")
    else:
        if user_permission == "2. システム管理者":
            st.info("📋 表示可能なデータがありません。")
        elif user_permission in ["4. 承認者", "3. 利用者・承認者"]:
            st.info("📋 承認対象のスタッフがいません。第一承認者として割り当てられているスタッフのデータのみ表示されます。")
        elif user_permission == "5. 一般利用者":
            st.info("📋 あなたの勤怠データが見つかりません。")
            
            # デバッグ情報を表示
            with st.expander("🔍 詳細情報（トラブルシューティング）"):
                st.write(f"**検索条件:**")
                st.write(f"- 社員番号: '{current_user_employee_id}'")
                st.write(f"- ログインID: '{current_user_login_id}'")
                
                st.write(f"**勤怠データ内の社員番号一覧（最初の10件）:**")
                unique_ids = merged["社員番号"].unique()[:10]
                for uid in unique_ids:
                    st.write(f"- '{uid}'")
                
                st.write(f"**完全一致チェック:**")
                exact_match = merged[merged["社員番号"].astype(str).str.strip() == str(current_user_employee_id).strip()]
                st.write(f"- 社員番号完全一致: {len(exact_match)}件")
                
                if "ログインID" in merged.columns:
                    login_match = merged[merged["ログインID"].astype(str).str.strip() == str(current_user_login_id).strip()]
                    st.write(f"- ログインID完全一致: {len(login_match)}件")
        else:
            st.info("📋 表示可能なデータがありません。")

# --- メイン実行 ---
if __name__ == "__main__":
    if handle_authentication():
        main_app()
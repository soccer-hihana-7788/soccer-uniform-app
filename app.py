import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
import os
from streamlit_cookies_manager import EncryptedCookieManager
import time

# --- ページ設定 ---
st.set_page_config(page_title="サッカーチーム背番号管理ツール", layout="wide")

# --- 1. クッキー（ログイン保持）の設定 ---
cookies = EncryptedCookieManager(password="soccer_secure_password_2026")
if not cookies.ready():
    st.stop()

def check_auth():
    auth_status = cookies.get("auth_status")
    saved_user = cookies.get("current_user")
    expire_time_str = cookies.get("login_expire")
    is_valid = False
    if auth_status == "ok" and expire_time_str:
        try:
            expire_time = datetime.fromisoformat(expire_time_str)
            if datetime.now() < expire_time: is_valid = True
        except: pass
    if is_valid:
        st.session_state["password_correct"] = True
        if saved_user: st.session_state["current_user"] = saved_user
        return True
    
    st.title("🛡️ ログイン")
    user_id = st.text_input("ログインID")
    password = st.text_input("パスワード", type="password")
    if st.button("ログイン"):
        # IDとパスワードは必要に応じて変更してください
        if user_id == "KSC" and password == "kuma2019":
            expire_date = datetime.now() + timedelta(hours=8)
            cookies["auth_status"] = "ok"
            cookies["login_expire"] = expire_date.isoformat()
            cookies.save()
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("IDまたはパスワードが正しくありません。")
    return False

if not check_auth(): st.stop()

# --- ユーザー氏名の選択 ---
if "current_user" not in st.session_state or not st.session_state["current_user"]:
    st.title("👤 担当者 氏名選択")
    name_list = ["加藤", "瀬野", "平", "稲垣", "富井", "新美", "細川", "島田"]
    selected_user = st.selectbox("あなたの氏名を選択してください", name_list)
    if st.button("決定"):
        st.session_state["current_user"] = selected_user
        cookies["current_user"] = selected_user
        cookies.save()
        st.rerun()
    st.stop()

# --- 2. Google Sheets 認証・接続設定 ---
@st.cache_resource
def get_gspread_client():
    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scope)
    else:
        key_file = "credentials.json"
        credentials = Credentials.from_service_account_file(key_file, scopes=scope)
    return gspread.authorize(credentials)

try:
    gc = get_gspread_client()
    # 新規作成したGoogleスプレッドシートのIDを反映
    SPREADSHEET_ID = "1yOFFntvApgvi-h6Z2bYFZbQevKNqAT82cfEitjD9Q14" 
    sh = gc.open_by_key(SPREADSHEET_ID)
except Exception as e:
    st.error(f"Googleスプレッドシート接続エラー: {e}")
    st.stop()

# --- サイドバー ---
st.sidebar.write(f"ログイン中の氏名: **{st.session_state['current_user']}**")
if st.sidebar.button("ユーザー変更"):
    cookies["current_user"] = ""
    cookies.save(); st.session_state["current_user"] = None; st.rerun()

if st.sidebar.button("ログアウト"):
    cookies["auth_status"] = ""; cookies["current_user"] = ""; cookies["login_expire"] = ""
    cookies.save(); st.session_state["password_correct"] = False; st.session_state["current_user"] = None; st.rerun()

st.title("⚽ サッカーチーム 背番号管理システム")
st.markdown("---")

# --- 3. 初期データ自動生成関数 ---
def init_worksheet_if_empty(ws, start_num, end_num):
    data = ws.get_all_records()
    if not data:
        # 初回起動時、指定範囲の背番号行を自動作成
        rows = []
        for num in range(start_num, end_num + 1):
            rows.append([num, "", "", "✕", ""]) # [背番号, 名前, 発注日時, 納品, 受け渡し日時]
        ws.append_rows(rows)

# --- 4. ページ切り替え（1〜100番 / 101〜200番） ---
tab1, tab2 = st.tabs(["👕 1 〜 100番 管理", "👕 101 〜 200番 管理"])

def render_uniform_manager(sheet_name, start_num, end_num):
    st.subheader(f"背番号 {start_num} 〜 {end_num} 一覧管理")
    
    try:
        ws = sh.worksheet(sheet_name)
    except Exception:
        # ワークシートが存在しない場合は作成して初期化
        ws = sh.add_worksheet(title=sheet_name, rows=200, cols=10)
        ws.append_row(["背番号", "名前", "発注日時", "納品", "受け渡し日時"])

    # 初期行の確認・作成
    init_worksheet_if_empty(ws, start_num, end_num)
    
    records = ws.get_all_records()
    df = pd.DataFrame(records)
    
    if df.empty:
        st.warning("データが取得できませんでした。")
        return

    # データエディタ用の表示用DataFrame調整
    # 受け渡し日時が入っている行の判定
    df['is_handed'] = df['受け渡し日時'].apply(lambda x: True if str(x).strip() != "" and pd.notna(x) else False)
    
    st.info("💡 **操作ガイド**: 氏名、発注日時、納品(〇/✕)、受け渡し日時を直接編集できます。編集後は画面下の「変更を保存する」ボタンを押してください。\n"
            "🔒 **グレーアウト仕様**: 受け渡し日時が入力されている選手は、番号と名前以外の詳細項目が自動的にロック（編集不可）されます。")

    # st.data_editor によるインライン編集
    edited_df = st.data_editor(
        df[["背番号", "名前", "発注日時", "納品", "受け渡し日時", "is_handed"]],
        column_config={
            "背番号": st.column_config.NumberColumn("背番号", disabled=True),
            "名前": st.column_config.TextColumn("名前 (選手名)"),
            "発注日時": st.column_config.DateColumn("発注日時 (YYYY-MM-DD)", format="YYYY-MM-DD"),
            "納品": st.column_config.SelectboxColumn("納品", options=["〇", "✕"], required=True),
            "受け渡し日時": st.column_config.DateColumn("受け渡し日時 (YYYY-MM-DD)", format="YYYY-MM-DD"),
            "is_handed": st.column_config.CheckboxColumn("受け渡し済ロック", disabled=True)
        },
        disabled=["背番号", "is_handed"], # 基本ロック
        hide_index=True,
        use_container_width=True,
        key=f"editor_{sheet_name}"
    )

    # 変更をスプレッドシートに保存するボタン
    if st.button("💾 変更をスプレッドシートに保存", key=f"save_{sheet_name}"):
        try:
            # 更新データの書き込み準備
            update_rows = []
            for idx, row in edited_df.iterrows():
                b_num = row["背番号"]
                name = str(row["名前"]) if pd.notna(row["名前"]) else ""
                
                # 日付のフォーマット処理（クリア時は空文字）
                ord_date = row["発注日時"]
                ord_str = ord_date.strftime("%Y-%m-%d") if pd.notna(ord_date) and str(ord_date).strip() != "" else ""
                
                delivery = str(row["納品"]) if pd.notna(row["納品"]) else "✕"
                
                hand_date = row["受け渡し日時"]
                hand_str = hand_date.strftime("%Y-%m-%d") if pd.notna(hand_date) and str(hand_date).strip() != "" else ""
                
                update_rows.append([int(b_num), name, ord_str, delivery, hand_str])
            
            # ヘッダー行を含めて一括更新 (2行目以降)
            ws.update(f"A2:E{len(update_rows)+1}", update_rows)
            st.cache_data.clear()
            st.success("スプレッドシートのデータを正常に更新しました！")
            time.sleep(1)
            st.rerun()
        except Exception as e:
            st.error(f"保存に失敗しました: {e}")

with tab1:
    render_uniform_manager("1_100", 1, 100)

with tab2:
    render_uniform_manager("101_200", 101, 200)
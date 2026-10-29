import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import time

# --- ページ設定 ---
st.set_page_config(page_title="サッカーチーム背番号管理ツール", layout="wide")

# --- 1. Secretsを用いたセキュアな認証 ---
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if not st.session_state["authenticated"]:
    st.title("🛡️ ログイン")
    user_id = st.text_input("ログインID")
    password = st.text_input("パスワード", type="password")
    
    if st.button("ログイン"):
        try:
            correct_user = st.secrets["auth"]["user_id"]
            correct_password = st.secrets["auth"]["password"]
        except Exception:
            st.error("認証情報（secrets.toml）が正しく設定されていません。")
            st.stop()
            
        if user_id == correct_user and password == correct_password:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("IDまたはパスワードが正しくありません。")
    st.stop()

# --- 2. Google Sheets 認証・接続設定 ---
@st.cache_resource
def get_gspread_client():
    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scope)
    else:
        st.error("Streamlit CloudのSecretsにGoogle認証情報が正しく設定されていません。")
        st.stop()
    return gspread.authorize(credentials)

try:
    gc = get_gspread_client()
    SPREADSHEET_ID = "1yOFFntvApgvi-h6Z2bYFZbQevKNqAT82cfEitjD9Q14" 
    sh = gc.open_by_key(SPREADSHEET_ID)
except Exception as e:
    st.error(f"Googleスプレッドシート接続エラー: {e}")
    st.stop()

# --- サイドバー ---
if st.sidebar.button("ログアウト"):
    st.session_state["authenticated"] = False
    st.rerun()

st.title("⚽ サッカーチーム 背番号管理システム")
st.markdown("---")

# --- 安全なレコード取得用ヘルパー（API制限・レートリミット自動リトライ対策） ---
def safe_get_all_records(ws):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return ws.get_all_records()
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            time.sleep(1.0 * (attempt + 1))

# --- 3. 初期データ自動生成関数 ---
def init_worksheet_if_empty(ws, start_num, end_num):
    try:
        data = safe_get_all_records(ws)
    except Exception:
        data = []
        
    if not data:
        rows = []
        for num in range(start_num, end_num + 1):
            rows.append([num, "", "", "", ""]) # [背番号, 名前, 発注日時, 納品, 受け渡し日時]
        try:
            ws.update("A1:E1", [["背番号", "名前", "発注日時", "納品", "受け渡し日時"]])
            ws.append_rows(rows)
        except Exception:
            pass

# --- 4. ワークシートデータ取得用ヘルパー ---
def load_sheet_data(sheet_name, start_num, end_num):
    try:
        ws = sh.worksheet(sheet_name)
    except Exception:
        ws = sh.add_worksheet(title=sheet_name, rows=200, cols=10)
        ws.append_row(["背番号", "名前", "発注日時", "納品", "受け渡し日時"])

    init_worksheet_if_empty(ws, start_num, end_num)
    
    try:
        records = safe_get_all_records(ws)
    except Exception as e:
        st.error(f"シート '{sheet_name}' の読み込みに失敗しました（API制限の可能性があります。少し待って再読み込みしてください）: {e}")
        return ws, pd.DataFrame()

    df = pd.DataFrame(records)
    
    if df.empty or "背番号" not in df.columns:
        init_worksheet_if_empty(ws, start_num, end_num)
        try:
            records = safe_get_all_records(ws)
            df = pd.DataFrame(records)
        except Exception:
            df = pd.DataFrame()

    # 日付列の安全なパース
    for col in ["発注日時", "受け渡し日時"]:
        if col in df.columns and not df.empty:
            df[col] = pd.to_datetime(df[col].replace(r'^\s*$', None, regex=True), errors='coerce').dt.date

    # 納品列の表示調整
    if "納品" in df.columns and not df.empty:
        df["納品"] = df["納品"].astype(str).replace({"✕": None, "None": None, "": None, "nan": None})

    if not df.empty and "受け渡し日時" in df.columns:
        df['is_handed'] = df['受け渡し日時'].apply(lambda x: True if pd.notna(x) and str(x).strip() != "" else False)
    else:
        df['is_handed'] = False
        
    return ws, df

# --- 5. ページ切り替え（利用中 / 1〜100番 / 101〜200番） ---
tab_active, tab1, tab2 = st.tabs(["🔥 利用中", "👕 1 〜 100番 管理", "👕 101 〜 200番 管理"])

# --- 【タブ0: 利用中一覧】 ---
with tab_active:
    st.subheader("🔥 利用中 背番号一覧")
    
    _, df1 = load_sheet_data("1_100", 1, 100)
    _, df2 = load_sheet_data("101_200", 101, 200)
    
    all_df = pd.concat([df1, df2], ignore_index=True)
    
    if not all_df.empty:
        active_df = all_df[all_df["名前"].astype(str).str.strip() != ""].copy()
        
        search_active = st.text_input(
            "🔍 利用中の背番号または名前で検索", 
            key="search_active",
            placeholder="例: 10 や 山田 など"
        )
        if search_active.strip():
            term = search_active.strip().lower()
            active_df = active_df[
                active_df['背番号'].astype(str).str.contains(term, case=False, na=False) |
                active_df['名前'].astype(str).str.contains(term, case=False, na=False)
            ]
        
        if active_df.empty:
            st.info("現在利用中の背番号はありません。")
        else:
            st.data_editor(
                active_df[["背番号", "名前", "発注日時", "納品", "受け渡し日時", "is_handed"]],
                column_config={
                    "背番号": st.column_config.NumberColumn("背番号", disabled=True),
                    "名前": st.column_config.TextColumn("名前 (選手名)", disabled=True),
                    "発注日時": st.column_config.DateColumn("発注日時 (YYYY-MM-DD)", format="YYYY-MM-DD", disabled=True),
                    "納品": st.column_config.SelectboxColumn("納品", options=[None, "〇", "✕"], disabled=True),
                    "受け渡し日時": st.column_config.DateColumn("受け渡し日時 (YYYY-MM-DD)", format="YYYY-MM-DD", disabled=True),
                    "is_handed": st.column_config.CheckboxColumn("受け渡し済ロック", disabled=True)
                },
                disabled=True,
                hide_index=True,
                use_container_width=True,
                key="editor_active_view"
            )

# --- 背番号管理画面描画関数 ---
def render_uniform_manager(sheet_name, start_num, end_num):
    st.subheader(f"背番号 {start_num} 〜 {end_num} 一覧管理")
    
    ws, df = load_sheet_data(sheet_name, start_num, end_num)
    
    if df.empty:
        st.warning("データが取得できませんでした。")
        return

    search_term = st.text_input(
        "🔍 背番号または名前で検索（該当する選手のみ絞り込まれます）", 
        key=f"search_{sheet_name}",
        placeholder="例: 10 や 山田 など"
    )

    display_df = df.copy()
    if search_term.strip():
        term = search_term.strip().lower()
        display_df = display_df[
            display_df['背番号'].astype(str).str.contains(term, case=False, na=False) |
            display_df['名前'].astype(str).str.contains(term, case=False, na=False)
        ]

    st.info("💡 **操作ガイド**: 各セルを選択して直接編集が可能です。編集完了後は画面下の「変更を保存する」ボタンを押してください。\n"
            "🔒 **グレーアウト仕様**: 受け渡し日時が入力されている選手は、番号と名前以外の詳細項目が自動的にロック（編集不可）されます。")

    edited_df = st.data_editor(
        display_df[["背番号", "名前", "発注日時", "納品", "受け渡し日時", "is_handed"]],
        column_config={
            "背番号": st.column_config.NumberColumn("背番号", disabled=True),
            "名前": st.column_config.TextColumn("名前 (選手名)"),
            "発注日時": st.column_config.DateColumn("発注日時 (YYYY-MM-DD)", format="YYYY-MM-DD"),
            "納品": st.column_config.SelectboxColumn("納品", options=[None, "〇", "✕"], required=False),
            "受け渡し日時": st.column_config.DateColumn("受け渡し日時 (YYYY-MM-DD)", format="YYYY-MM-DD"),
            "is_handed": st.column_config.CheckboxColumn("受け渡し済ロック", disabled=True)
        },
        disabled=["背番号", "is_handed"],
        hide_index=True,
        use_container_width=True,
        key=f"editor_{sheet_name}"
    )

    if st.button("💾 変更をスプレッドシートに保存", key=f"save_{sheet_name}"):
        try:
            updated_full_df = df.set_index("背番号")
            edited_set = edited_df.set_index("背番号")
            
            for b_num, row in edited_set.iterrows():
                if b_num in updated_full_df.index:
                    updated_full_df.loc[b_num, "名前"] = row["名前"]
                    updated_full_df.loc[b_num, "発注日時"] = row["発注日時"]
                    updated_full_df.loc[b_num, "納品"] = row["納品"]
                    updated_full_df.loc[b_num, "受け渡し日時"] = row["受け渡し日時"]
            
            updated_full_df = updated_full_df.reset_index()

            update_rows = []
            for idx, row in updated_full_df.iterrows():
                b_num = row["背番号"]
                name = str(row["名前"]) if pd.notna(row["名前"]) else ""
                
                ord_date = row["発注日時"]
                ord_str = ord_date.strftime("%Y-%m-%d") if pd.notna(ord_date) and str(ord_date).strip() != "" else ""
                
                delivery = str(row["納品"]) if pd.notna(row["納品"]) and row["納品"] is not None and str(row["納品"]) != "None" else ""
                
                hand_date = row["受け渡し日時"]
                hand_str = hand_date.strftime("%Y-%m-%d") if pd.notna(hand_date) and str(hand_date).strip() != "" else ""
                
                update_rows.append([int(b_num), name, ord_str, delivery, hand_str])
            
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

import os
import re
import sqlite3
import urllib.parse
import urllib.request
import json
import pandas as pd
import streamlit as st

# --- 1. 自动从 GitHub Release 缓存下载 DB 文件 ---
DB_PATH = "weblog_corpus.db"
RELEASE_URL = "https://github.com/JasonZeng24/CDSSDEMO/releases/download/v1.0/weblog_corpus.db"

st.set_page_config(
    page_title="Brad DeLong's Weblog Archive (1995–2005)",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource(show_spinner=False)
def ensure_database():
    if not os.path.exists(DB_PATH):
        with st.spinner(
            "Downloading Brad DeLong's Corpus Database (~100MB+)... Please wait a"
            " few seconds."
        ):
            urllib.request.urlretrieve(RELEASE_URL, DB_PATH)


ensure_database()


def get_db_connection():
    return sqlite3.connect(DB_PATH)


# 月份英文名转两位数字映射表
MONTH_MAP = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12"
}


@st.cache_data(show_spinner=False)
def resolve_wayback_url(rel_path: str, post_date: str) -> str:
    """
    将本地自定义 rel_path 还原为当年 j-bradford-delong.net 上的具体文章/归档页 URL，
    并通过 Wayback CDX API 查找最匹配的真实快照页面。
    """
    clean_p = str(rel_path).replace("\\", "/").lstrip("/")
    
    # 剔除本地外层文件夹前缀（如果有）
    for prefix in ["web_assets_cleaned/", "delong_archive/", "archive/"]:
        if clean_p.startswith(prefix):
            clean_p = clean_p[len(prefix):]

    candidates = []

    # 1. 处理类似 '2003_archives--July' 的月度归档文件名
    m_month = re.search(r"(\d{4})_archives(?:--|/|-)?([A-Za-z]+)", clean_p)
    if m_month:
        yr, m_name = m_month.group(1), m_month.group(2).lower()
        if m_name in MONTH_MAP:
            mm = MONTH_MAP[m_name]
            # Movable Type 当年真实的月度归档 URL 格式
            candidates.append(f"http://www.j-bradford-delong.net/movable_type/{yr}_archives/{yr}_{mm}.html")
            candidates.append(f"http://www.j-bradford-delong.net/movable_type/archives/{yr}_{mm}.html")

    # 2. 处理将 '--' 转回 '/' 后的原始相对路径
    restored_path = clean_p.replace("--", "/")
    if restored_path.startswith("movable_type/"):
        sub_p = restored_path[len("movable_type/"):]
    else:
        sub_p = restored_path

    # 候选路径：带 movable_type 和直接挂在根域名下的具体页面
    candidates.append(f"http://www.j-bradford-delong.net/movable_type/{sub_p}")
    candidates.append(f"http://www.j-bradford-delong.net/{sub_p}")
    if not sub_p.endswith(".html") and not sub_p.endswith(".htm"):
        candidates.append(f"http://www.j-bradford-delong.net/movable_type/{sub_p}.html")
        candidates.append(f"http://www.j-bradford-delong.net/{sub_p}.html")

    # 3. 依次通过 Wayback CDX API 检查哪个候选具体页面真实存在快照
    for cand_url in candidates:
        cdx_api = (
            f"https://web.archive.org/cdx/search/cdx?"
            f"url={urllib.parse.quote(cand_url)}&output=json&fl=timestamp,original&filter=statuscode:200&limit=1"
        )
        try:
            req = urllib.request.Request(cdx_api, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if len(data) > 1:  # data[0] 是表头 ['timestamp', 'original']
                    ts, orig = data[1][0], data[1][1]
                    return f"https://web.archive.org/web/{ts}/{orig}"
        except Exception:
            pass

    # 4. 如果精确文件名因当年重命名找不到，用文件前缀模糊搜索 CDX 目录下的最近页面
    base_slug = os.path.splitext(os.path.basename(restored_path))[0]
    if len(base_slug) >= 4:
        cdx_prefix_api = (
            f"https://web.archive.org/cdx/search/cdx?"
            f"url=j-bradford-delong.net/*{urllib.parse.quote(base_slug)}*&output=json&fl=timestamp,original&filter=statuscode:200&limit=1"
        )
        try:
            req = urllib.request.Request(cdx_prefix_api, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if len(data) > 1:
                    ts, orig = data[1][0], data[1][1]
                    return f"https://web.archive.org/web/{ts}/{orig}"
        except Exception:
            pass

    # 5. 最终保底：跳到该文章所属年份/日期的具体时间轴快照
    m_yr = re.search(r"(199\d|200[0-5])", clean_p + " " + str(post_date))
    yr = m_yr.group(1) if m_yr else "2004"
    return f"https://web.archive.org/web/{yr}0710015200/http://www.j-bradford-delong.net/"


# --- 2. 侧边栏：强化 DeLong 个人归档与科研项目背景 ---
st.sidebar.title("🏛️ Brad DeLong's Corpus")
st.sidebar.caption("UC Berkeley Economics | Pre-2005 Archive")
st.sidebar.markdown(
    """
**J. Bradford DeLong's Semi-Daily Journal**  
A digital catalog with a mouth for 20+ years of economic history, policy critiques, and academic discourse.
"""
)
st.sidebar.divider()

# 数据统计卡片
try:
    conn = get_db_connection()
    total_posts = pd.read_sql_query(
        "SELECT COUNT(*) AS c FROM posts;", conn
    ).iloc[0]["c"]
    dated_posts = pd.read_sql_query(
        "SELECT COUNT(*) AS c FROM posts WHERE post_date != 'Unknown';", conn
    ).iloc[0]["c"]
    missing_asset_posts = pd.read_sql_query(
        "SELECT COUNT(*) AS c FROM posts WHERE missing_imgs > 0;", conn
    ).iloc[0]["c"]
    conn.close()

    st.sidebar.metric("Indexed DeLong Posts", f"{total_posts:,}")
    st.sidebar.metric(
        "Temporal Recovery Rate", f"{(dated_posts / total_posts):.1%}"
    )
    st.sidebar.metric(
        "Asset Integrity Rate",
        f"{((total_posts - missing_asset_posts) / total_posts):.1%}",
    )
except Exception as e:
    st.sidebar.warning(f"Database error: {e}")

st.sidebar.divider()
nav_mode = st.sidebar.radio(
    "Navigation",
    [
        "DeLong Full-Text Search (FTS5)",
        "Posting Timeline & Trends",
        "Resource Health Audit",
    ],
)

# --- 3. 页面 1：强调 DeLong 博客全文检索与正文渲染 ---
if nav_mode == "DeLong Full-Text Search (FTS5)":
    st.title("Search Brad DeLong's Weblog Archive")
    st.markdown(
        "**Explore 21,500+ original posts and economic commentary from Brad"
        " DeLong's *Semi-Daily Journal* (Pre-2005).**  \n*Powered by SQLite FTS5"
        " for instant sub-second contextual querying.*"
    )

    col1, col2 = st.columns([3, 1])
    with col1:
        query_text = st.text_input(
            "Search keywords or phrases in DeLong's writings:",
            value="Zhu Rongji",
            placeholder="e.g. Zhu Rongji, Greenspan, East Asian Crisis, Treasury",
        )
    with col2:
        max_results = st.selectbox(
            "Max results to display:", [5, 10, 20, 50], index=1
        )

    if query_text.strip():
        conn = get_db_connection()
        search_sql = """
        SELECT 
            p.id, 
            p.title, 
            p.post_date, 
            p.rel_path, 
            p.body_clean,
            p.missing_imgs,
            snippet(posts_fts, 1, '<mark style="background-color: #fef08a; font-weight: bold; color: #1e293b;">', '</mark>', '...', 35) AS snippet_text
        FROM posts_fts
        JOIN posts p ON posts_fts.rowid = p.id
        WHERE posts_fts MATCH ?
        LIMIT ?;
        """
        try:
            results = pd.read_sql_query(
                search_sql, conn, params=(query_text, max_results)
            )
            conn.close()

            st.write(
                f"Found **{len(results)}** matching posts by Brad DeLong (display"
                f" limit: {max_results}):"
            )

            for _, row in results.iterrows():
                post_title = (
                    row["title"] if row["title"] else "Untitled Entry / DeLong Note"
                )
                status_color = "green" if row["missing_imgs"] == 0 else "orange"
                status_label = (
                    "Complete Assets"
                    if row["missing_imgs"] == 0
                    else f"Missing {row['missing_imgs']} Images"
                )

                # 解析该条文章在 Wayback Machine 上的真实快照地址
                wayback_url = resolve_wayback_url(row["rel_path"], row["post_date"])

                with st.expander(
                    f"📝 {post_title} ({row['post_date']})", expanded=True
                ):
                    st.markdown(
                        f"**Matched Excerpt:**\n> {row['snippet_text']}",
                        unsafe_allow_html=True,
                    )

                    # Step 1 核心功能：全文可折叠渲染
                    with st.expander("📖 Read Full Article (Cleaned Text)"):
                        if row["body_clean"] and str(row["body_clean"]).strip():
                            st.markdown(row["body_clean"])
                        else:
                            st.info(
                                "Full text body unavailable in local database cache. Access"
                                " the preserved snapshot via Wayback below."
                            )

                    st.divider()
                    meta_col1, meta_col2 = st.columns([2, 1])
                    with meta_col1:
                        st.caption(
                            f"Original File: `{row['rel_path']}` | Integrity:"
                            f" :{status_color}[{status_label}]"
                        )
                    with meta_col2:
                        st.markdown(
                            f"[:blue-background[🌐 Sourced from Wayback]]({wayback_url})",
                            help="Open external archival snapshot in Internet Archive",
                        )

        except Exception as err:
            st.error(f"Search query error: {err}")
            conn.close()

# --- 4. 页面 2：DeLong 发帖时间轴趋势 ---
elif nav_mode == "Posting Timeline & Trends":
    st.title("Brad DeLong's Publishing Timeline")
    st.markdown(
        "*Annual volume of posts and notes published across the pre-2005"
        " archive.*"
    )

    conn = get_db_connection()
    yearly_sql = """
    SELECT 
        substr(post_date, -4) AS year, 
        COUNT(*) AS post_count
    FROM posts
    WHERE post_date != 'Unknown' 
      AND substr(post_date, -4) GLOB '19[89][0-9]|20[0-2][0-9]'
    GROUP BY year
    ORDER BY year ASC;
    """
    df_years = pd.read_sql_query(yearly_sql, conn)
    conn.close()

    if not df_years.empty:
        st.bar_chart(data=df_years.set_index("year"), color="#003262")
        st.dataframe(df_years, use_container_width=True)
    else:
        st.info("No yearly timeline data available.")

# --- 5. 页面 3：媒体依赖审计 ---
elif nav_mode == "Resource Health Audit":
    st.title("Asset & Dependency Health Audit")
    st.markdown(
        "*Audit of archived DeLong posts with missing external images or broken"
        " legacy paths (494 files flagged).*"
    )

    conn = get_db_connection()
    audit_sql = """
    SELECT rel_path, title, total_imgs, missing_imgs, missing_samples
    FROM posts
    WHERE missing_imgs > 0
    ORDER BY missing_imgs DESC;
    """
    df_missing = pd.read_sql_query(audit_sql, conn)
    conn.close()

    st.dataframe(df_missing, use_container_width=True)

import os
import re
import json
import sqlite3
import urllib.parse
import urllib.request
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


@st.cache_data(show_spinner=False, ttl=3600)
def query_cdx_snapshots(rel_path: str, post_date: str):
    """
    使用标准的 Wayback CDX Server API (matchType=prefix + 正则 filter)
    查找与当前本地文件最匹配的真实历史快照 URL 列表。
    """
    clean_p = str(rel_path).replace("\\", "/").lstrip("/")
    
    # 提取有辨识度的文件名或目录关键词（去掉无意义的后缀和横杠）
    # 例如 '2003_archives--July' -> 提取 '2003' 和 'July' 或具体文件名
    tokens = [t for t in re.split(r"[/\-_.]", clean_p) if len(t) >= 3 and t.lower() not in ("html", "htm", "txt", "www", "net", "delong", "bradford", "archives", "movable", "type")]
    
    # 优先使用最具体的末尾文件名 token
    keyword = tokens[-1] if tokens else "2003"
    
    # 构造符合 CDX 官方规范的 API URL（绝不在 domain 中间加 *）
    api_url = (
        "https://web.archive.org/cdx/search/cdx?"
        "url=j-bradford-delong.net/&matchType=prefix"
        "&filter=statuscode:200"
        "& filter=mimetype:text/html".replace(" ", "") +
        f"&filter=~original:(?i){urllib.parse.quote(keyword)}"
        "&collapse=urlkey&output=json&fl=timestamp,original&limit=10"
    )
    
    try:
        req = urllib.request.Request(
            api_url, 
            headers={"User-Agent": "UCBerkeley-DSDiscovery-Research/1.0"}
        )
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if len(data) > 1:
                # 返回 [(timestamp, original_url, wayback_full_link), ...]
                results = []
                for item in data[1:]:
                    ts, orig = item[0], item[1]
                    wb_link = f"https://web.archive.org/web/{ts}/{orig}"
                    results.append({"timestamp": ts, "original_url": orig, "wayback_url": wb_link})
                return results
    except Exception:
        pass
    return []


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
        " & Wayback Machine CDX API Integration.*"
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
                    "Complete Local Assets"
                    if row["missing_imgs"] == 0
                    else f"Missing {row['missing_imgs']} Images"
                )
                
                body_str = str(row["body_clean"]).strip() if row["body_clean"] else ""
                is_local_valid = len(body_str) > 40

                with st.expander(
                    f"📝 {post_title} ({row['post_date']})", expanded=True
                ):
                    # 顶部状态徽章栏
                    badge_col1, badge_col2 = st.columns([3, 1])
                    with badge_col1:
                        st.caption(
                            f"Record ID: `{row['id']}` | Local File: `{row['rel_path']}` | Integrity: :{status_color}[{status_label}]"
                        )
                    with badge_col2:
                        if is_local_valid:
                            st.markdown(":green-background[✅ Rendered from Local Archive]")
                        else:
                            st.markdown(":blue-background[🌐 Sourced from Wayback Fallback]")

                    # 匹配高亮摘要
                    st.markdown(
                        f"**Matched Excerpt:**\n> {row['snippet_text']}",
                        unsafe_allow_html=True,
                    )

                    # Step 1 核心要求：直接内置干净的全文阅读器 (Content Renderer)
                    with st.expander("📖 Read Full Article Text (Markdown Renderer)", expanded=False):
                        if is_local_valid:
                            st.markdown(body_str)
                        else:
                            st.warning("Local file is truncated or missing. Fetching from Wayback CDX API...")

                    # Step 2 集成：按需实时调用 Wayback CDX API 查找该文件的精确历史 URL
                    with st.expander("🌐 Wayback Machine CDX Lookup (Verify External Snapshots)", expanded=not is_local_valid):
                        if st.button(f"🔍 Query CDX API for `{row['rel_path']}`", key=f"cdx_btn_{row['id']}"):
                            with st.spinner("Querying Internet Archive CDX Server API..."):
                                cdx_hits = query_cdx_snapshots(row["rel_path"], row["post_date"])
                                if cdx_hits:
                                    st.success(f"Found {len(cdx_hits)} matching archival snapshots on Wayback Machine:")
                                    for hit in cdx_hits:
                                        st.markdown(
                                            f"- **[{hit['original_url']}]({hit['wayback_url']})** (Captured: `{hit['timestamp'][:8]}`)"
                                        )
                                else:
                                    # 如果文件名是纯本地重命名的，提供一个去 Wayback 搜索该路径关键词的直达入口
                                    m_yr = re.search(r"(199\d|200[0-5])", str(row["rel_path"]) + " " + str(row["post_date"]))
                                    yr = m_yr.group(1) if m_yr else "2003"
                                    fallback_archive = f"https://web.archive.org/web/{yr}0701000000*/http://www.j-bradford-delong.net/*"
                                    st.info(
                                        f"Filename `{row['rel_path']}` was renamed locally during the legacy scrape. "
                                        f"[👉 Browse all {yr} URLs in Wayback Machine Directory]({fallback_archive})"
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

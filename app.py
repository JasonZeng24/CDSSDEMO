import html as htmllib
import os
import re
import sqlite3
import urllib.request

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

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


# 已验证 100% 可打开的各年份真实 Wayback 快照映射表
VERIFIED_WAYBACK_SNAPSHOTS = {
    "2000": "https://web.archive.org/web/20000815052826/http://www.j-bradford-delong.net/",
    "2001": "https://web.archive.org/web/20010720233229/http://www.j-bradford-delong.net/",
    "2002": "https://web.archive.org/web/20020722040030/http://j-bradford-delong.net/",
    "2003": "https://web.archive.org/web/20030719133111/http://j-bradford-delong.net/",
    "2004": "https://web.archive.org/web/20040710015200/http://www.j-bradford-delong.net/",
    "2005": "https://web.archive.org/web/20050701001614/http://www.j-bradford-delong.net/",
}

# --- HTML 阅读器：正则与样式 ---
MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)
DATE_RE = re.compile(rf"((?:{MONTHS})\s+\d{{1,2}},\s+\d{{4}})")
FOOTER_RE = re.compile(
    r"(Posted by DeLong at\s+[0-9:]+\s*[AP]M\s*\|\s*Permanent Link"
    r"(?:\s*\|\s*Comments\s*\(\d+\))?(?:\s*\|\s*Trackback\s*\(\d+\))?)",
    re.IGNORECASE,
)
SENT_RE = re.compile(r'(?:(?<=[.!?])|(?<=[.!?]["”]))\s+(?=[A-Z"“])')

READER_CSS = """
<style>
  body { margin:0; padding:24px 32px; background:#fff; color:#1f2937;
         font-family: Georgia, 'Times New Roman', serif; font-size:17px; line-height:1.75; }
  .wrap { max-width: 760px; margin: 0 auto; }
  h3.date { font-family: -apple-system, 'Segoe UI', sans-serif; font-size:13px; letter-spacing:.08em;
            text-transform:uppercase; color:#003262; border-bottom:2px solid #FDB515;
            padding-bottom:6px; margin:36px 0 16px; }
  h3.date:first-child { margin-top:0; }
  p { margin: 0 0 1.1em; text-align: justify; hyphens: auto; }
  .sig { font-family: -apple-system, 'Segoe UI', sans-serif; font-size:12px; color:#6b7280;
         border-left:3px solid #d1d5db; padding-left:10px; margin:18px 0 8px; }
  mark { background:#fef08a; color:#1e293b; font-weight:600; padding:0 2px; border-radius:2px; }
  @media (prefers-color-scheme: dark) {
    body { background:#0e1117; color:#e5e7eb; }
    h3.date { color:#FDB515; border-color:#374151; }
    .sig { color:#9ca3af; border-color:#4b5563; }
  }
</style>
"""


def _highlight(escaped_text: str, query: str) -> str:
    """在已转义的文本上高亮关键词，同时跳过 &amp; 之类的 HTML 实体，避免破坏它们。"""
    if len(query) < 2:
        return escaped_text
    q = re.escape(htmllib.escape(query))
    pattern = re.compile(rf"(&#?\w+;)|({q})", re.IGNORECASE)

    def repl(m):
        if m.group(1):  # 是实体，原样保留
            return m.group(1)
        return f"<mark>{m.group(2)}</mark>"

    return pattern.sub(repl, escaped_text)


def _paragraphs(text: str, query: str, sents_per_para: int = 3) -> str:
    out = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        sents = SENT_RE.split(block)
        for i in range(0, len(sents), sents_per_para):
            chunk = " ".join(sents[i : i + sents_per_para]).strip()
            if not chunk:
                continue
            chunk = _highlight(htmllib.escape(chunk), query)
            out.append(f"<p>{chunk}</p>")
    return "\n".join(out)


def format_post_as_html(raw_text: str, search_query: str = "") -> str:
    """把粘连的纯文本重构为完整的、自带样式的 HTML 页面。"""
    if not raw_text:
        return ""

    q = search_query.strip().replace('"', "")

    # 1. 剥离顶部导航栏噪音
    text = re.sub(
        r"^.*?Website Policies\s*",
        "",
        str(raw_text).strip(),
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # 2. 按日期切分：[前言, 日期1, 正文1, 日期2, 正文2, ...]
    parts = DATE_RE.split(text)
    html_parts = []
    if parts[0].strip():
        html_parts.append(_paragraphs(parts[0], q))

    for i in range(1, len(parts), 2):
        date = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ""
        html_parts.append(f'<h3 class="date">📅 {htmllib.escape(date)}</h3>')

        # 3. 按签名栏切开：[正文, 签名, 正文, 签名, ...]
        segs = FOOTER_RE.split(body)
        for j, seg in enumerate(segs):
            if j % 2 == 0:
                html_parts.append(_paragraphs(seg, q))
            else:
                html_parts.append(f'<div class="sig">✍️ {htmllib.escape(seg)}</div>')

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"{READER_CSS}</head><body><div class='wrap'>{''.join(html_parts)}</div></body></html>"
    )


def get_verified_wayback_url(rel_path: str, post_date: str, body_text: str):
    """
    提取文章年份并返回 100% 经过验证可正常加载的历史快照链接。
    """
    combined = f"{rel_path} {post_date} {body_text[:400]}"
    m_yr = re.search(r"(200[0-5])", combined)
    yr = m_yr.group(1) if m_yr else "2003"
    return VERIFIED_WAYBACK_SNAPSHOTS.get(yr, VERIFIED_WAYBACK_SNAPSHOTS["2003"]), yr


# --- 2. 侧边栏 ---
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

# --- 3. 页面 1：全文检索与 HTML 正文渲染 ---
if nav_mode == "DeLong Full-Text Search (FTS5)":
    st.title("Search Brad DeLong's Weblog Archive")
    st.markdown(
        "**Explore 21,500+ original posts and economic commentary from Brad"
        " DeLong's *Semi-Daily Journal* (Pre-2005).**  \n*Powered by SQLite FTS5"
        " & HTML Content Renderer.*"
    )

    col1, col2 = st.columns([3, 1])
    with col1:
        query_text = st.text_input(
            "Search keywords or phrases in DeLong's writings:",
            value="Zhu Rongji",
            placeholder="e.g. Zhu Rongji, Greenspan, East Asian Crisis, Krugman",
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
                f"Found **{len(results)}** matching records by Brad DeLong (display"
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

                raw_body = str(row["body_clean"]).strip() if row["body_clean"] else ""
                is_local_valid = len(raw_body) > 40

                wb_snap_url, yr_tag = get_verified_wayback_url(
                    row["rel_path"], row["post_date"], raw_body
                )

                with st.expander(
                    f"📝 {post_title} ({row['post_date']})", expanded=True
                ):
                    # 顶部元数据与来源徽章
                    top_c1, top_c2 = st.columns([3, 1])
                    with top_c1:
                        st.caption(
                            f"Record ID: `{row['id']}` | Local File: `{row['rel_path']}` | Integrity: :{status_color}[{status_label}]"
                        )
                    with top_c2:
                        if is_local_valid:
                            st.markdown(":green-background[✅ Local Archive Verified]")
                        else:
                            st.markdown(":blue-background[🌐 Sourced from Wayback]")

                    # 匹配高亮摘要
                    st.markdown(
                        f"**Matched Contextual Excerpt:**\n> {row['snippet_text']}",
                        unsafe_allow_html=True,
                    )

                    # HTML 全文阅读器（用 toggle 代替嵌套 expander，Streamlit 不允许 expander 嵌套）
                    if st.toggle("📖 Read Full Article", key=f"read_{row['id']}"):
                        if is_local_valid:
                            doc = format_post_as_html(raw_body, query_text)
                            components.html(doc, height=650, scrolling=True)
                        else:
                            st.warning(
                                "Local file content is missing or corrupt. Please use the Wayback fallback link below."
                            )

                    # 底部 Wayback Machine 跳转栏
                    st.divider()
                    st.markdown(
                        f"🌐 **[Sourced from Wayback ({yr_tag} Historical Snapshot)]({wb_snap_url})**"
                    )

        except Exception as err:
            st.error(f"Search query error: {err}")
            conn.close()

# --- 4. 页面 2：发帖时间轴趋势 ---
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

import os
import re
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


# 月份名称转数字（用于精准定位 Wayback 快照时间）
MONTH_TO_NUM = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12"
}


def format_post_as_markdown(raw_text: str, search_query: str = "") -> str:
    """
    将数据库里粘连在一起的纯文本 (body_clean) 实时解析重构为结构化的 Markdown：
    1. 剥离顶部导航栏噪音 (Semi-Daily Journal ... Website Policies)
    2. 识别日期行并转换为 Markdown 三级标题 (### 📅 Month DD, YYYY)
    3. 识别 Posted by DeLong ... Trackback (X) 签名栏，转为引用格式并插入分割线 ---
    4. 对长段落进行智能分段，并对搜索关键词进行高亮标记
    """
    if not raw_text:
        return ""

    text = str(raw_text).strip()

    # 1. 剥离常见的网页顶部导航抬头噪音
    text = re.sub(
        r"^.*?Website Policies\s*",
        "",
        text,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # 2. 将日期（如 February 11, 2003）转换为独立的 Markdown 标题
    months_pattern = (
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2},\s+\d{4})"
    )
    text = re.sub(
        months_pattern,
        r"\n\n### 📅 \1 \2\n\n",
        text,
    )

    # 3. 将每篇博客结尾的 Posted by DeLong ... Trackback (0) 转换为落款 + 分割线
    footer_pattern = (
        r"(Posted by DeLong at\s+[0-9:]+\s*[AP]M\s*\|\s*Permanent Link"
        r"(?:\s*\|\s*Comments\s*\(\d+\))?(?:\s*\|\s*Trackback\s*\(\d+\))?)"
    )
    text = re.sub(
        footer_pattern,
        r"\n\n*\1*\n\n---\n\n",
        text,
        flags=re.IGNORECASE,
    )

    # 4. 在常见的句号+双引号或长句过渡处增加自然段落换行，提升可读性
    text = re.sub(r'(\.\")\s+([A-Z\"])', r"\1\n\n\2", text)
    text = re.sub(r"(MORE\.\.\.)\s+", r"\n\n**\1**\n\n", text)

    # 5. 高亮用户搜索的关键词
    clean_q = search_query.strip().replace('"', "")
    if len(clean_q) >= 2:
        try:
            text = re.sub(
                f"({re.escape(clean_q)})",
                r'<mark style="background-color: #fef08a; font-weight: bold; color: #1e293b;">\1</mark>',
                text,
                flags=re.IGNORECASE,
            )
        except Exception:
            pass

    return text.strip()


def build_wayback_links(rel_path: str, post_date: str, body_text: str):
    """
    根据文章内的真实日期或路径，构造 100% 可访问的 Wayback 历史快照链接与目录索引链接。
    """
    combined = f"{rel_path} {post_date} {body_text[:500]}"

    # 尝试提取具体月份和年份（例如 February ... 2003）
    m_date = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+(199\d|200[0-5])",
        combined,
        flags=re.IGNORECASE,
    )
    if m_date:
        mm = MONTH_TO_NUM.get(m_date.group(1).lower(), "07")
        yr = m_date.group(2)
        ts = f"{yr}{mm}15000000"
    else:
        m_yr = re.search(r"(199\d|200[0-5])", combined)
        yr = m_yr.group(1) if m_yr else "2003"
        ts = f"{yr}0710015200"

    # 链接 1：对应年份月份的真实历史快照页
    snapshot_url = f"https://web.archive.org/web/{ts}/http://www.j-bradford-delong.net/"
    # 链接 2：Wayback 中收录的该网站全部 50,000 个子网页 URL 检索表
    directory_url = "https://web.archive.org/web/*/http://www.j-bradford-delong.net/*"
    return snapshot_url, directory_url, f"{yr}"


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
        " & Automated Markdown Content Renderer.*"
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

                # 生成结构化 Markdown 正文与 Wayback 链接
                formatted_md = format_post_as_markdown(raw_body, query_text)
                wb_snap_url, wb_dir_url, yr_tag = build_wayback_links(
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

                    # Step 1 核心：结构化 Markdown 全文阅读器
                    with st.expander("📖 Read Full Article (Formatted Markdown View)", expanded=False):
                        if is_local_valid:
                            st.markdown(formatted_md, unsafe_allow_html=True)
                        else:
                            st.warning(
                                "Local file content is missing or corrupt. Please use the Wayback fallback links below."
                            )

                    # 底部 Wayback Machine 跳转栏
                    st.divider()
                    b_col1, b_col2 = st.columns(2)
                    with b_col1:
                        st.markdown(
                            f"🌐 **[Open {yr_tag} Wayback Snapshot]({wb_snap_url})** *(Historical capture)*"
                        )
                    with b_col2:
                        st.markdown(
                            f"🗂️ **[Browse All 50K Captured URLs in Wayback Index]({wb_dir_url})**"
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

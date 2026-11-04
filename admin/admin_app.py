"""管理后台：只有管理员能看用户访问流

密码从环境变量 ADMIN_PASSWORD 读，未设置时页面拒绝访问。
不在主页暴露任何统计数据——避免把别人的提问展示给所有访客。
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from tools.query_log import by_session, overview, recent, sessions_recent, stats

st.set_page_config(page_title="管理后台", page_icon="🔐", layout="wide")

PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()

# ---------------- 鉴权 ----------------
if "admin_ok" not in st.session_state:
    st.session_state.admin_ok = False

if not st.session_state.admin_ok:
    st.title("🔐 管理后台")
    if not PASSWORD:
        st.error("未配置 `ADMIN_PASSWORD` 环境变量，后台不可用。\n\n"
                 "在服务器的 `.env` 里加一行 `ADMIN_PASSWORD=你的密码` 后重启服务。")
        st.stop()

    with st.form("login"):
        pwd = st.text_input("管理员密码", type="password")
        if st.form_submit_button("进入", type="primary"):
            if pwd == PASSWORD:
                st.session_state.admin_ok = True
                st.rerun()
            else:
                st.error("密码错误")
    st.stop()

# ---------------- 概览 ----------------
st.title("🔐 管理后台")
if st.button("退出登录"):
    st.session_state.admin_ok = False
    st.rerun()

ov = overview()
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("总提问", ov["total"])
c2.metric("今日", ov["today"])
c3.metric("会话数", ov["sessions"])
c4.metric("未命中率", f"{ov['miss_rate']:.0f}%")
c5.metric("平均耗时", f"{ov['avg_ms']} ms")

if ov["total"] == 0:
    st.info("还没有任何提问记录。让用户问几个问题后再来看。")
    st.stop()

st.divider()

# ---------------- 路由分布 + 高频问题 ----------------
s = stats()
left, right = st.columns(2)

with left:
    st.subheader("路由分布")
    if s["routes"]:
        st.dataframe(
            [{"路由": r or "-", "次数": c} for r, c in s["routes"]],
            width="stretch", hide_index=True,
        )
    else:
        st.caption("暂无数据")

with right:
    st.subheader("高频问题")
    if s["top_questions"]:
        st.dataframe(
            [{"问题": q[:46], "次数": c} for q, c in s["top_questions"]],
            width="stretch", hide_index=True,
        )
    else:
        st.caption("暂无数据")

st.divider()

# ---------------- 访问流 ----------------
st.subheader("访问流（最近会话）")
sessions = sessions_recent(40)

if not sessions:
    st.caption("暂无会话")
else:
    st.dataframe(
        [{
            "开始时间": x["started_at"][5:16].replace("T", " "),
            "会话": x["session_id"],
            "轮次": x["turns"],
            "未命中": x["misses"],
            "首问": (x["first_q"] or "")[:40],
        } for x in sessions],
        width="stretch", hide_index=True,
    )

    st.divider()
    st.subheader("会话详情")

    labels = [f"{x['started_at'][5:16].replace('T', ' ')} · {x['session_id']} · "
              f"{(x['first_q'] or '')[:28]}" for x in sessions]
    pick = st.selectbox("选择一个会话查看完整追问链", labels)

    if pick:
        idx = labels.index(pick)
        sid = sessions[idx]["session_id"]

        for turn in by_session(sid):
            flag = "" if turn["hit"] else " ⚠️ 未命中"
            st.markdown(
                f"**{turn['ts'][11:16]}** · `{turn['mode']}` · `{turn['route']}` · "
                f"{turn['elapsed_ms']} ms · {turn['tokens'] or '-'} tokens{flag}"
            )
            st.markdown(f"> **问：** {turn['question']}")
            if turn["answer"]:
                st.caption(f"答：{turn['answer'][:300]}")
            st.divider()

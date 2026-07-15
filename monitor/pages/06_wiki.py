"""Wiki browser — file tree, markdown viewer, search."""
import streamlit as st
from lib.api import get_wiki_files, get_wiki_file

st.title("Wiki")

files = get_wiki_files()
if isinstance(files, dict) and "error" in files:
    st.error(files["error"])
    st.stop()

if not files:
    st.info("No wiki files found.")
    st.stop()

st.subheader(f"{len(files)} files")

col1, col2 = st.columns([1, 2])

with col1:
    selected = st.selectbox("File", [f["path"] for f in files])

with col2:
    if selected:
        data = get_wiki_file(selected)
        if "error" in data:
            st.error(data["error"])
        else:
            st.caption(f"Size: {data['size']:,} chars")
            st.markdown(data["content"])

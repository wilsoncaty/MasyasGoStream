"""Presentation components for Masyas Go Stream. No streaming logic lives here."""

from pathlib import Path
import streamlit as st


def render_brand():
    css = Path(__file__).with_name("gostream.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    st.markdown("""
<div class="gs-topbar">
  <div class="gs-brand"><span class="gs-logo" aria-hidden="true">M<span>↗</span></span>
    <div>Masyas <strong>Go Stream</strong><small>YOUR PERSONAL STREAMING STUDIO</small></div>
  </div>
  <div class="gs-top-right"><span class="gs-platform"><span aria-hidden="true">▶</span> YouTube Studio</span><span class="gs-avatar">M</span></div>
</div>
<div class="gs-hero">
  <div class="gs-hero-copy"><div class="gs-eyebrow"><span></span> CREATE. STREAM. REPEAT.</div>
    <h1>Kontenmu. Panggungmu.<br><span>Mulai dari sini.</span></h1>
    <p>Susun playlist, atur siaran, dan bawa kontenmu live di YouTube.<br>Satu ruang untuk semua ide besarmu.</p>
  </div>
  <div class="gs-art" aria-hidden="true"><div class="gs-orbit"></div><div class="gs-orbit gs-orbit-inner"></div><div class="gs-play">▶</div><div class="gs-art-label">MASYAS / ON AIR STUDIO</div></div>
</div>
""", unsafe_allow_html=True)


def render_workspace_title():
    st.markdown('<div class="gs-workspace-title"><div><span class="gs-eyebrow">WORKSPACE</span><h2>Ruang siaran</h2></div><span class="gs-workspace-note">Dari playlist ke siaran, dalam satu tempat.</span></div>', unsafe_allow_html=True)


def section(number, title, description=""):
    st.markdown(
        f'<div class="gs-section"><span class="gs-step">{number}</span>'
        f'<div><h3>{title}</h3><p>{description}</p></div></div>',
        unsafe_allow_html=True,
    )


def render_footer():
    st.markdown('''<div class="gs-footer"><span><strong>Masyas Go Stream</strong> · Dibuat untuk terus berkarya.</span><span>YOUR CONTENT. YOUR STAGE.</span></div>''', unsafe_allow_html=True)

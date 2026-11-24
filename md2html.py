#!/usr/bin/env python3
"""Konversi PANDUAN-BAHASA-BAYI.md ke HTML siap-cetak. Stdlib saja.

Konverter minimal: heading, bold, italic, inline code, list, tabel, blockquote, hr.
Cukup untuk dokumen ini, bukan markdown lengkap.
"""
import html
import re
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "PANDUAN-BAHASA-BAYI.md"
OUT = sys.argv[2] if len(sys.argv) > 2 else "PANDUAN-BAHASA-BAYI.html"


def inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    return s


def convert(md):
    out, lines, i = [], md.split("\n"), 0
    while i < len(lines):
        ln = lines[i]
        st = ln.strip()

        if not st:
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", st)
        if m:
            n = len(m.group(1))
            out.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
            i += 1
            continue

        if st.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            head = [c.strip() for c in st.strip("|").split("|")]
            i += 2
            body = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                body.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append("<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>")
            for r in body:
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
            out.append("</tbody></table>")
            continue

        if st == "---":
            out.append("<hr>")
            i += 1
            continue

        if st.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append("<blockquote>" + inline(" ".join(buf)) + "</blockquote>")
            continue

        m = re.match(r"^([-*])\s+(.*)$", st)
        if m:
            out.append("<ul>")
            while i < len(lines) and lines[i].strip():
                cur = lines[i]
                if re.match(r"^\s*[-*]\s+", cur):
                    buf = [re.sub(r"^\s*[-*]\s+", "", cur)]
                elif out[-1] == "<ul>":
                    break
                else:
                    # baris lanjutan item sebelumnya (indent >= 2 spasi)
                    if not cur.startswith("  "):
                        break
                    buf = [cur.strip()]
                i += 1
                # gabung baris lanjutan milik item ini
                while i < len(lines) and lines[i].strip() and not re.match(
                    r"^\s*([-*]|\d+\.)\s+", lines[i]
                ):
                    buf.append(lines[i].strip())
                    i += 1
                out.append("<li>" + inline(" ".join(buf)) + "</li>")
            out.append("</ul>")
            continue

        m = re.match(r"^(\d+)\.\s+(.*)$", st)
        if m:
            out.append("<ol>")
            while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i]):
                out.append("<li>" + inline(re.sub(r"^\s*\d+\.\s+", "", lines[i])) + "</li>")
                i += 1
            out.append("</ol>")
            continue

        buf = []
        while i < len(lines) and lines[i].strip() and not re.match(
            r"^(#{1,6}\s|\||>\s*|[-*]\s|\d+\.\s|---$)", lines[i].strip()
        ):
            buf.append(lines[i].strip())
            i += 1
        out.append("<p>" + inline(" ".join(buf)) + "</p>")
    return "\n".join(out)


CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: -apple-system, "Segoe UI", Roboto, sans-serif; font-size: 10.5pt;
       line-height: 1.55; color: #1a1a1a; max-width: 100%; }
h1 { font-size: 20pt; border-bottom: 3px solid #2563eb; padding-bottom: 6px; margin-top: 0; }
h2 { font-size: 14pt; margin-top: 22px; color: #1e3a8a; border-bottom: 1px solid #dbeafe;
     padding-bottom: 3px; page-break-after: avoid; }
h3 { font-size: 11.5pt; margin-top: 16px; color: #1f2937; page-break-after: avoid; }
p { margin: 7px 0; }
ul, ol { margin: 7px 0; padding-left: 22px; }
li { margin: 3px 0; }
code { background: #f1f5f9; padding: 1px 4px; border-radius: 3px;
       font-family: ui-monospace, Consolas, monospace; font-size: 9.5pt; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 9.5pt;
        page-break-inside: avoid; }
th { background: #eff6ff; text-align: left; font-weight: 600; }
th, td { border: 1px solid #cbd5e1; padding: 5px 8px; vertical-align: top; }
blockquote { border-left: 4px solid #f59e0b; background: #fffbeb; margin: 10px 0;
             padding: 8px 14px; color: #78350f; page-break-inside: avoid; }
hr { border: none; border-top: 1px solid #e2e8f0; margin: 20px 0; }
strong { color: #0f172a; }
"""

md = open(SRC, encoding="utf-8").read()
body = convert(md)
page = f"""<!DOCTYPE html>
<html lang="id"><head><meta charset="utf-8">
<title>Panduan Sistem Crypto — Versi Bahasa Bayi</title>
<style>{CSS}</style></head><body>{body}</body></html>"""

open(OUT, "w", encoding="utf-8").write(page)

# self-check: tag seimbang + tidak ada markdown mentah yang lolos
import collections
for tag in ("table", "ul", "ol", "blockquote", "p", "h2"):
    o, c = page.count(f"<{tag}>"), page.count(f"</{tag}>")
    assert o == c, f"tag {tag} tidak seimbang: {o} buka vs {c} tutup"
assert "**" not in body, "ada bold markdown yang tidak terkonversi"
print(f"ok: {OUT} {len(page)} chars, {body.count('<table>')} tabel, {body.count('<h2>')} bab")

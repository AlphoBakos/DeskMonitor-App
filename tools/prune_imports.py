# -*- coding: utf-8 -*-
"""Retire les imports inutilisés signalés par pyflakes (outil ponctuel, utilisé après le découpage)."""
import re
import subprocess
import sys
from pathlib import Path


def unused(path):
    out = subprocess.run([sys.executable, "-m", "pyflakes", str(path)], capture_output=True, text=True).stdout
    names = set()
    for line in out.splitlines():
        m = re.search(r"'([^']+)' imported but unused", line)
        if m:
            names.add(m.group(1))
    return names


def prune(path):
    raw = path.read_text(encoding="utf-8")
    crlf = "\r\n" in raw
    lines = raw.replace("\r\n", "\n").split("\n")
    bad = unused(path)
    if not bad:
        return 0
    short = {b.split(".")[-1].split(" as ")[-1] for b in bad}   # « core.THEMES » → THEMES ; « x as y » → y
    full = set(bad)
    out, in_paren, removed = [], False, 0
    # seulement l'en-tête du fichier : les imports placés dans les fonctions ne sont jamais touchés
    end = next((k for k, ln in enumerate(lines) if re.match(r"^(class|def)\s|^@", ln) or re.match(r"^[A-Z_]+ = ", ln)),
               len(lines))
    for idx, ln in enumerate(lines):
        st = ln.strip()
        if idx >= end:
            out.append(ln)
            continue
        if in_paren:   # bloc « from core import ( … ) » : un nom par ligne
            if st == ")":
                in_paren = False
                out.append(ln)
                continue
            name = st.rstrip(",")
            if name in short:
                removed += 1
                continue
            out.append(ln)
            continue
        if re.match(r"^(from \S+ )?import \($", st):
            in_paren = True
            out.append(ln)
            continue
        m = re.match(r"^(\s*)import (\S+)( as (\S+))?$", ln)
        if m and (m.group(2) in full or (m.group(4) and m.group(4) in short) or f"{m.group(2)} as {m.group(4)}" in full):
            removed += 1
            continue
        m = re.match(r"^(\s*)from (\S+) import (.+)$", ln)
        if m and "(" not in m.group(3):
            names = [n.strip() for n in m.group(3).split(",")]
            keep = [n for n in names if n.split(" as ")[-1] not in short]
            if len(keep) != len(names):
                removed += len(names) - len(keep)
                if keep:
                    out.append(f"{m.group(1)}from {m.group(2)} import {', '.join(keep)}")
                continue
        out.append(ln)
    text = "\n".join(out)
    text = re.sub(r"from core import \(\n\)\n", "", text)                      # bloc vidé
    text = re.sub(r"if IS_WIN:\n(?!    )", "", text)                           # « if IS_WIN: » sans contenu
    path.write_text(text.replace("\n", "\r\n") if crlf else text, encoding="utf-8", newline="")
    return removed


if __name__ == "__main__":
    for f in sys.argv[1:]:
        p = Path(f)
        total = 0
        for _ in range(3):   # un retrait peut en révéler un autre
            n = prune(p)
            total += n
            if not n:
                break
        print(f"{p.name} : {total} import(s) inutilisé(s) retiré(s)")

# fix_excel.py
# -*- coding: utf-8 -*-
"""
Saneado robusto del Excel de preguntas:

 - Normaliza Unicode/espacios/puntuación final.
 - Si 'Opciones' viene en una sola línea o con varias oraciones en la misma línea,
   las divide en líneas con dos heurísticas:
     (1) split por sentencia: (?<=[.!?])\s+(?=[A-Z])
     (2) capital-split: [A-Z][^A-Z]+(?=(?: [A-Z]|$))
 - Reagrupa tokens cortos contiguos (ventana 2..6) SOLO si no son frases,
   para casar exactamente con la 'Respuesta Correcta'.
 - Ajusta la 'Respuesta Correcta' a la opción real (o la añade si faltase).
 - Devuelve *_CLEAN.xlsx (uso silencioso desde la app).
"""
from __future__ import annotations
import os, re, unicodedata
from typing import List, Tuple
import pandas as pd

# ------------------ Normalización ------------------ #
def _norm(s: str) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = re.sub(r"[\u00A0\u2009\u2007\u202F\u200B\u200C\u200D\uFEFF]", "", s)
    s = s.replace("\r", " ").replace("\t", " ")
    s = re.sub(r"\s+", " ", s).strip().casefold()
    s = re.sub(r"[.;:]+$", "", s)
    return s

def _split_answers(ans: str) -> List[str]:
    ans = str(ans or "").strip()
    return [a.strip() for a in ans.split(";") if a.strip()]

# ------------------ Heurísticas de “frase” ------------------ #
def _is_sentence(line: str) -> bool:
    txt = (line or "").strip()
    if not txt:
        return False
    words = txt.split()
    return (len(txt) >= 20 or len(words) >= 4) or bool(re.search(r"[.!?]$", txt))

def _mostly_sentences(lines: List[str]) -> bool:
    if not lines:
        return False
    sents = sum(1 for l in lines if _is_sentence(l))
    return sents >= max(1, int(0.6 * len(lines)))

# ------------------ Split de opciones “pegadas” ------------------ #
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

def _explode_compounded_options(options_text: str) -> List[str]:
    """
    Asegura una opción por línea:
      1) si hay '\n' y cada línea ya parece opción -> devolver tal cual
      2) probar split por oraciones
      3) capital-split: [A-Z] ... hasta la siguiente [A-Z] (separado por espacio)
    """
    raw = [l.strip() for l in str(options_text or "").split("\n") if l.strip()]
    if not raw:
        return []

    if len(raw) >= 2 and not any(_SENT_SPLIT.search(l) for l in raw):
        # ya hay varias líneas; si parecen oraciones, dejamos tal cual
        return raw

    # 1) split por oraciones en cada línea
    parts: List[str] = []
    changed = False
    for l in raw:
        sents = [p.strip() for p in _SENT_SPLIT.split(l) if p.strip()]
        if len(sents) >= 2:
            parts.extend(sents); changed = True
        else:
            parts.append(l)
    if changed:
        return parts

    # 2) capital-split si seguimos “pegados”
    # ejemplo: "Define the enterprise strategy Establish lean budgets Align strategy..."
    joined = " ".join(raw)
    caps = re.findall(r'[A-Z][^A-Z]+(?=(?: [A-Z]|$))', joined)
    caps = [c.strip() for c in caps if c.strip()]
    if len(caps) >= 2:
        return caps

    return raw

# ------------------ Re-agrupado “tokens cortos” (2..6) ------------------ #
def _regroup_tokens_if_needed(raw_text: str, answers: List[str]) -> List[str]:
    """Reagrupa SOLO si no son frases (evita unir oraciones en mega-opciones)."""
    raw = [l.strip() for l in str(raw_text or "").split("\n") if l.strip()]
    if not raw:
        return []

    if answers and {_norm(x) for x in answers}.issubset({_norm(o) for o in raw}):
        return raw

    if _mostly_sentences(raw):
        return raw

    changed = True
    max_win = 6
    while changed:
        changed = False
        for ans in answers:
            ansn = _norm(ans)
            if ansn in {_norm(x) for x in raw}:
                continue
            found = False
            for start in range(len(raw)):
                for win in range(2, max_win + 1):
                    end = start + win
                    if end > len(raw): break
                    cand = " ".join(raw[start:end]).replace(" - ", "-").replace("- ", "-")
                    if _norm(cand) == ansn:
                        raw = raw[:start] + [cand] + raw[end:]
                        changed, found = True, True
                        break
                if found: break
        if not raw: break
    return raw

# ------------------ Corrección semántica ------------------ #
def _semantic_fix_row(options: List[str], answers: List[str]) -> Tuple[List[str], List[str], bool, int]:
    on = {_norm(o) for o in options}
    new_answers = answers.copy()
    changed_answer = False
    added_options = 0
    for j, a in enumerate(answers):
        an = _norm(a)
        if an in on: 
            continue
        # contención (elige la opción más larga)
        cands = [o for o in options if (_norm(o) in an) or (an in _norm(o))]
        if cands:
            best = max(cands, key=len)
            new_answers[j] = best
            changed_answer = True
        else:
            if a not in options:
                options.append(a)
                on.add(an)
                added_options += 1
    return options, new_answers, changed_answer, added_options

# ------------------ Proceso principal ------------------ #
def _process_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    for col in ("Veces Realizada", "Errores"):
        if col not in df.columns:
            df[col] = 0

    for i, row in df.iterrows():
        numero = row.get("Nº", "")
        opts_txt = str(row.get("Opciones", ""))
        answers  = _split_answers(row.get("Respuesta Correcta", ""))

        # (A) Siempre intentar “explotar” opciones pegadas (una opción por línea)
        opts_lines = _explode_compounded_options(opts_txt)

        # (B) Para todas, solo si parecen tokens cortos, intentar re-agrupado 2..6
        opciones = _regroup_tokens_if_needed("\n".join(opts_lines), answers)

        # (C) Corrección semántica final
        opciones, answers_fixed, changed_ans, _ = _semantic_fix_row(opciones, answers)

        df.at[i, "Opciones"] = "\n".join(opciones)
        if changed_ans:
            df.at[i, "Respuesta Correcta"] = "; ".join(answers_fixed)

    return df

def ensure_clean(in_path: str, out_path: str | None = None, backup: bool = True) -> str:
    if out_path is None:
        base, ext = os.path.splitext(in_path)
        out_path = f"{base}_CLEAN{ext}"
    backup_path = None
    if backup:
        base, ext = os.path.splitext(in_path)
        backup_path = f"{base}_backup{ext}"
    try:
        if os.path.exists(out_path) and os.path.getmtime(out_path) >= os.path.getmtime(in_path):
            return out_path
    except Exception:
        pass

    df = pd.read_excel(in_path, engine="openpyxl")
    try:
        if backup and (not os.path.exists(backup_path)):
            df.to_excel(backup_path, index=False, engine="openpyxl")
    except Exception:
        pass

    df2 = _process_dataframe(df)
    df2.to_excel(out_path, index=False, engine="openpyxl")
    return out_path

if __name__ == "__main__":
    DEFAULT_FILE = "Agil - Copia de Preguntas_Examen.xlsx"
    ensure_clean(DEFAULT_FILE)
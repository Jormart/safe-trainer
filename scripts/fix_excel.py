# fix_excel.py
# -*- coding: utf-8 -*-
"""
Saneado robusto del Excel de preguntas:
 - Divide en líneas las celdas de 'Opciones' que contengan varias oraciones en una sola línea.
 - Reagrupa 'palabra-por-línea' a frases (ventana contigua 2..6) **solo** cuando son tokens cortos.
 - Evita reagrupado si ya son oraciones (para no crear mega-opciones).
 - Para Nº 316..335, fuerza el auto-split cuando detecta frases pegadas (caso Solution Vision).
 - Garantiza que 'Respuesta Correcta' exista exactamente en 'Opciones' (ajusta/añade).
 - Devuelve la ruta del fichero *_CLEAN.xlsx a usar en la app (sin prints).
"""
from __future__ import annotations
import os
import re
import unicodedata
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
    s = re.sub(r"[.;:]+$", "", s)  # quita puntuación final común
    return s


def _split_answers(ans: str) -> List[str]:
    ans = str(ans or "").strip()
    return [a.strip() for a in ans.split(";") if a.strip()]


# ------------------ Detección de "frase" ------------------ #
def _is_sentence(line: str) -> bool:
    """
    Heurística simple: lo consideramos 'frase' si supera cierto umbral de longitud/palabras
    o termina en . ! ?  (evita reagrupados sobre líneas ya completas).
    """
    txt = (line or "").strip()
    if not txt:
        return False
    words = txt.split()
    return (len(txt) >= 20 or len(words) >= 4) or bool(re.search(r"[.!?]$", txt))


def _mostly_sentences(lines: List[str]) -> bool:
    if not lines:
        return False
    sents = sum(1 for l in lines if _is_sentence(l))
    return sents >= max(1, int(0.6 * len(lines)))  # mayoría


# ------------------ Auto-split de frases ------------------ #
# Separador: fin de oración (.!?), espacios, inicio de probable frase (Mayúscula, dígito, paréntesis o comillas)
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"“])")

def _split_sentences_if_needed(options_text: str) -> List[str]:
    """
    Si 'Opciones' trae varias frases pegadas en una línea, se separan en varias líneas.
    Conserva la puntuación, evita crear mega-opciones.
    """
    raw_lines = [l.strip() for l in str(options_text or "").split("\n") if l.strip()]
    if not raw_lines:
        return []

    # Caso 1: todo en una única línea con varias oraciones
    if len(raw_lines) == 1:
        line = raw_lines[0]
        parts = [p.strip() for p in _SENT_SPLIT.split(line) if p.strip()]
        if len(parts) >= 2:
            return parts

    # Caso 2: alguna línea contiene varias oraciones
    result: List[str] = []
    changed = False
    for l in raw_lines:
        parts = [p.strip() for p in _SENT_SPLIT.split(l) if p.strip()]
        if len(parts) >= 2:
            result.extend(parts)
            changed = True
        else:
            result.append(l)

    return result if changed else raw_lines


# ------------------ Re-agrupado SOLO para tokens cortos ------------------ #
def _regroup_options_smart(raw_text: str, answers: List[str]) -> List[str]:
    """
    Reagrupa 'palabra-por-línea' (ventana 2..6) solo cuando las líneas parecen tokens cortos.
    Si la mayoría son frases, NO reagrupa (evita juntar oraciones en una sola opción).
    """
    raw = [l.strip() for l in str(raw_text or "").split("\n") if l.strip()]
    if not raw:
        return []

    # Si ya encaja, no tocar
    if answers and {_norm(x) for x in answers}.issubset({_norm(o) for o in raw}):
        return raw

    # Blindaje: si la mayoría son oraciones, no reagrupes
    if _mostly_sentences(raw):
        return raw

    # Reagrupado 2..6 tokens cortos buscando casamiento exacto con respuestas
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
                    if end > len(raw):
                        break
                    cand = " ".join(raw[start:end]).replace(" - ", "-").replace("- ", "-")
                    if _norm(cand) == ansn:
                        raw = raw[:start] + [cand] + raw[end:]
                        changed, found = True, True
                        break
                if found:
                    break
        if not raw:
            break
    return raw


# ------------------ Correcciones semánticas (Respuesta ↔ Opción) ------------------ #
def _semantic_fix_row(options: List[str], answers: List[str]) -> Tuple[List[str], List[str], bool, int]:
    """
    Ajusta 'Respuesta Correcta' a la opción real si hay pequeñas variaciones.
    Si no existe, añade la opción faltante al final.
    """
    on = {_norm(o) for o in options}
    new_answers = answers.copy()
    changed_answer = False
    added_options = 0

    for j, a in enumerate(answers):
        an = _norm(a)
        if an in on:
            continue
        # Probar contención: mapea a la opción más larga que contenga/sea contenida
        candidates = [o for o in options if (_norm(o) in an) or (an in _norm(o))]
        if candidates:
            best = max(candidates, key=len)
            new_answers[j] = best
            changed_answer = True
        else:
            # Último recurso: añade la respuesta como nueva opción
            if a not in options:
                options.append(a)
                on.add(an)
                added_options += 1
    return options, new_answers, changed_answer, added_options


# ------------------ Proceso principal de saneado ------------------ #
def _process_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    # Asegurar columnas métricas
    for col in ("Veces Realizada", "Errores"):
        if col not in df.columns:
            df[col] = 0

    for i, row in df.iterrows():
        numero = row.get("Nº", "")
        opts_txt = str(row.get("Opciones", ""))
        answers = _split_answers(row.get("Respuesta Correcta", ""))

        # 1) Auto-split genérico cuando detecta oraciones pegadas
        opts_lines = _split_sentences_if_needed(opts_txt)

        # 2) En Nº 316..335, fuerza el auto-split cuando siga habiendo 'señales' de texto corrido
        try:
            n_int = int(numero)
        except Exception:
            n_int = None

        if n_int is not None and 316 <= n_int <= 335:
            if len(opts_lines) == 1 or any(len(l) > 160 for l in opts_lines):
                opts_lines = _split_sentences_if_needed("\n".join(opts_lines))

        # 3) Re-agrupado solo si son tokens cortos (nunca sobre frases)
        opciones = _regroup_options_smart("\n".join(opts_lines), answers)

        # 4) Ajuste semántico Respuesta ↔ Opción
        opciones, answers_fixed, changed_ans, _ = _semantic_fix_row(opciones, answers)

        # Guardar resultado
        df.at[i, "Opciones"] = "\n".join(opciones)
        if changed_ans:
            df.at[i, "Respuesta Correcta"] = "; ".join(answers_fixed)

    return df


def ensure_clean(in_path: str, out_path: str | None = None, backup: bool = True) -> str:
    """
    Genera (o reutiliza si está actualizado) una versión *_CLEAN.xlsx* con opciones
    bien formateadas (una por línea) y respuestas consistentes. Devuelve su ruta.
    """
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
        pass  # si falla el mtime, reescribimos

    df = pd.read_excel(in_path, engine="openpyxl")

    # Backup (opcional, silencioso)
    try:
        if backup and (not os.path.exists(backup_path)):
            df.to_excel(backup_path, index=False, engine="openpyxl")
    except Exception:
        pass

    # Saneado completo
    df2 = _process_dataframe(df)
    df2.to_excel(out_path, index=False, engine="openpyxl")
    return out_path


if __name__ == "__main__":
    # Ejecución autónoma: no imprime (silencioso)
    DEFAULT_FILE = "Agil - Copia de Preguntas_Examen.xlsx"
    ensure_clean(DEFAULT_FILE)
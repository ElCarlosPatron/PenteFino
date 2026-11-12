"""Leitura e exportação do CSV Comptar; funções independentes da interface."""
import io
import re
import pandas as pd

REQUIRED = ["Codigo", "Descricao", "Saldo", "C1", "C.Dif", "Diferenca", "Ajuste", "Final", "Localizacoes"]


def parse_qty(raw):
    text = str(raw).strip()
    if not re.fullmatch(r"\d+", text):
        raise ValueError(f"Quantidade FINAL inválida: {text!r}. Corrija o CSV de origem.")
    return int(text)


def load_comptar(content):
    if not content:
        raise ValueError("Arquivo vazio.")
    original = None
    for enc in ("utf-8-sig", "cp1252", "latin1"):
        try:
            original = pd.read_csv(io.BytesIO(content), sep=";", encoding=enc,
                                   dtype=str, keep_default_na=False)
            break
        except UnicodeDecodeError:
            continue
        except Exception as exc:
            raise ValueError(f"Formato CSV inválido: {exc}") from exc
    if original is None:
        raise ValueError("Codificação de texto não reconhecida.")
    original.columns = [str(c).strip() for c in original.columns]
    missing = [c for c in REQUIRED if c not in original.columns]
    if missing:
        raise ValueError("Colunas ausentes: " + ", ".join(missing))
    valid_indices = original.index[original["Codigo"].str.strip().ne("")].tolist()
    if not valid_indices:
        raise ValueError("Nenhum produto com código encontrado.")
    work = original.loc[valid_indices, REQUIRED].copy().reset_index(drop=True)
    try:
        work["CONT.FINAL"] = work["Final"].map(parse_qty)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    work["_initial"] = work["CONT.FINAL"].copy()
    work["Conferido"] = False
    return original, work, valid_indices


def export_comptar(original, work, valid_indices):
    if len(work) != len(valid_indices):
        raise ValueError("Quantidade de produtos inconsistente.")
    if not work["Conferido"].all():
        raise ValueError("Existem produtos não conferidos.")
    result = original.copy()
    result["CONT.FINAL"] = ""
    for pos, source_idx in enumerate(valid_indices):
        value = work.at[pos, "CONT.FINAL"]
        if pd.isna(value) or float(value) < 0 or not float(value).is_integer():
            raise ValueError(f"Quantidade inválida no produto {work.at[pos, 'Codigo']}.")
        result.at[source_idx, "CONT.FINAL"] = str(int(value))
    return result.to_csv(index=False, sep=";", lineterminator="\r\n").encode("utf-8-sig")


def is_sem_localizacao(saldo, c1, cdif):
    """SKU com saldo no sistema que não apareceu nas duas contagens do Comptar.

    O arquivo pode conter localizações vazias; a regra usa os números de
    estoque e das duas contagens, não depende do preenchimento de LOCAL.
    """
    def number(value):
        text = str(value if value is not None else "").strip()
        if not text:
            return None
        # Contagens do Comptar são inteiras; aceita também decimais com vírgula.
        if re.fullmatch(r"-?\d+", text):
            return int(text)
        if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", text):
            return int(text.replace(".", ""))
        if re.fullmatch(r"-?\d+,\d+", text):
            return float(text.replace(",", "."))
        return None

    saldo_num, c1_num, cdif_num = number(saldo), number(c1), number(cdif)
    return saldo_num is not None and saldo_num > 0 and c1_num == 0 and cdif_num == 0


def safe_filename(value):
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value.strip()).strip("_") or "SEM_NOME"


def export_adjustments(rows):
    """CSV para Excel brasileiro: ponto e vírgula, UTF-8 BOM e status explícito.

    `rows` vem do relatório consolidado e já contém `quantity` e `status`.
    """
    import csv

    def safe(value):
        text = str(value)
        # Avoid spreadsheet formula injection in externally supplied code/description.
        return "'" + text if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else text

    payload = io.StringIO(newline="")
    writer = csv.writer(payload, delimiter=";", lineterminator="\r\n")
    writer.writerow(["COD", "DESC", "QUANTIDADE", "STATUS"])
    for row in rows:
        writer.writerow([safe(row["sku"]), safe(row["description"]),
                         int(row["quantity"]), row["status"]])
    return payload.getvalue().encode("utf-8-sig")

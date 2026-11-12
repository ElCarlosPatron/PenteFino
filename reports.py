"""Relatórios PDF padronizados do Pente Fino (ReportLab, A4 paisagem)."""
from __future__ import annotations

import io
from datetime import datetime
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, LongTable,
                                TableStyle, PageBreak, KeepTogether)

INK = colors.HexColor("#142D26")
GREEN = colors.HexColor("#0E8160")
MUTED = colors.HexColor("#596D65")
LIGHT = colors.HexColor("#EFF6F2")
BORDER = colors.HexColor("#DCE8E1")
AMBER = colors.HexColor("#A56114")
AMBER_LIGHT = colors.HexColor("#FFF1DE")


def fonts():
    """Use system fonts if present; no font files are distributed with the app."""
    pairs = [
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    for regular, bold in pairs:
        if Path(regular).exists() and Path(bold).exists():
            if "PF-Regular" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("PF-Regular", regular))
                pdfmetrics.registerFont(TTFont("PF-Bold", bold))
            return "PF-Regular", "PF-Bold"
    return "Helvetica", "Helvetica-Bold"


def formatted(iso):
    if not iso:
        return "-"
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M:%S")
    except (ValueError, TypeError):
        return str(iso)


def build_pdf(count, stats, rows, history):
    bodyfont, boldfont = fonts()
    styles = {
        "title": ParagraphStyle("PFTitle", fontName=boldfont, fontSize=23, leading=29, textColor=INK, spaceAfter=9),
        "sub": ParagraphStyle("PFSub", fontName=bodyfont, fontSize=9, leading=14, textColor=MUTED),
        "h2": ParagraphStyle("PFHeading", fontName=boldfont, fontSize=13, leading=18, textColor=INK, spaceBefore=17, spaceAfter=11),
        "table": ParagraphStyle("PFTable", fontName=bodyfont, fontSize=7.4, leading=11, textColor=INK),
        "thead": ParagraphStyle("PFHead", fontName=boldfont, fontSize=7.5, leading=11, textColor=colors.white),
        "warn": ParagraphStyle("PFWarn", fontName=boldfont, fontSize=7.4, leading=11, textColor=AMBER),
        "caption": ParagraphStyle("PFCaption", fontName=bodyfont, fontSize=8, leading=12, textColor=MUTED, spaceAfter=9),
    }
    def cell(value, style="table"):
        return Paragraph(escape(str(value if value is not None else "-")).replace("\n", " "),styles[style])
    def styled_table(data, widths, header=True):
        table = LongTable(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
        cmds = [
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING",(0,0),(-1,-1),8),
            ("RIGHTPADDING",(0,0),(-1,-1),8),
            ("TOPPADDING",(0,0),(-1,-1),7),
            ("BOTTOMPADDING",(0,0),(-1,-1),7),
            ("LINEBELOW",(0,0),(-1,-1),.35,BORDER),
        ]
        if header:
            cmds += [("BACKGROUND",(0,0),(-1,0),INK)]
        table.setStyle(TableStyle(cmds))
        return table
    out = io.BytesIO()
    w,h = landscape(A4)
    doc = SimpleDocTemplate(out, pagesize=(w,h), leftMargin=35,rightMargin=35,
                            topMargin=43,bottomMargin=39, title="Relatório Pente Fino",
                            author="Pente Fino", pageCompression=1)
    width = w - 70
    story = [Paragraph("PENTE FINO | RELATÓRIO FINAL", styles["title"]),
             Paragraph(f"LOJA: {escape(count['store'])} &nbsp;&nbsp;&nbsp; CÓDIGO: {escape(count['code'])}",styles["sub"]),
             Paragraph(f"Arquivo Comptar: {escape(count['filename'])} | Criado em: {formatted(count['created_at'])}",styles["sub"]),
             Spacer(1,17)]
    headline = [
        ("SKUs",str(stats["total"])),
        ("CONFERIDOS",str(stats["reviewed"])),
        ("SEM CONFERÊNCIA",str(stats["pending"])),
        ("CELULARES FINALIZADOS",f"{stats['finished']}/{count['phone_count']}"),
    ]
    metricdata = [[cell(label, "table") for label,value in headline],
                  [Paragraph(f'<font color="#0E8160"><b>{value}</b></font>',
                             ParagraphStyle("metric",fontName=boldfont,fontSize=18,leading=26))
                   for label,value in headline]]
    metrics=Table(metricdata,colWidths=[width/4]*4,hAlign="LEFT")
    metrics.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),LIGHT),
                                 ("BOX",(0,0),(-1,-1),.5,BORDER),
                                 ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
                                 ("LEFTPADDING",(0,0),(-1,-1),13),
                                 ("TOPPADDING",(0,0),(-1,-1),10),
                                 ("BOTTOMPADDING",(0,0),(-1,-1),9)]))
    story.extend([metrics, Paragraph("RESUMO POR CELULAR E OPERADOR", styles["h2"])])
    teamdata = [[cell(t,"thead") for t in ("CEL.","OPERADOR","INÍCIO","FINALIZAÇÃO","CONFERIDOS","FALTAM","ÚLTIMO SKU","RESULTADO")]]
    for ph in stats["phones"]:
        status=("Finalização antecipada" if ph["finished_at"] and ph["pending"]
                else "Finalizado 100%" if ph["finished_at"] else "Em andamento")
        values=(ph["slot"],ph["operator"] or "Sem operador",formatted(ph["joined_at"]),
                formatted(ph["finished_at"]),f"{ph['reviewed']}/{ph['total']}",ph["pending"],ph["last_sku"] or "-",status)
        teamdata.append([cell(v,"warn" if i==7 and ph["pending"] else "table")
                         for i,v in enumerate(values)])
    story.append(styled_table(teamdata,[44,105,112,112,77,65,77,width-592]))
    if stats["pending"]:
        story.append(Spacer(1,13))
        story.append(Paragraph("ATENÇÃO: os SKUs não conferidos mantiveram a quantidade FINAL do Comptar. "
                               "Esses valores NÃO representam uma nova conferência física e estão "
                               "identificados como 'Finalizado antes de conferir'.",styles["warn"]))
    story.append(Paragraph("HISTÓRICO DE OPERADORES E APARELHOS",styles["h2"]))
    story.append(Paragraph("Registra entradas, liberações, reaberturas e finalizações, mesmo após troca de operador.", styles["caption"]))
    events_labels = {
        "joined":"Entrou na contagem", "released":"Acesso liberado", "reopened":"Parte reaberta",
        "finished_early":"Finalizou antes de conferir tudo", "finished_complete":"Finalizou 100%"
    }
    eventdata=[[cell(t,"thead") for t in ("DATA/HORA","CELULAR","OPERADOR","AÇÃO","ÚLTIMO SKU SALVO")]]
    for event in history:
        eventdata.append([cell(formatted(event["at"])),cell(event["slot"]),
                          cell(event["operator"]),cell(events_labels.get(event["event"],event["event"])),
                          cell(event.get("last_sku") or "-")])
    if len(eventdata)>1:
        story.append(styled_table(eventdata,[130,68,175,width-473,100]))
    else:
        story.append(Paragraph("Não há eventos de histórico anteriores disponíveis.", styles["caption"]))
    story.append(PageBreak())
    story.append(Paragraph("RELAÇÃO COMPLETA DOS SKUs",styles["h2"]))
    story.append(Paragraph("QUANTIDADE: valor salvo pelo operador quando conferido; em SKUs não conferidos, "
                           "quantidade original FINAL do Comptar.",styles["caption"]))
    details = [[cell(t,"thead") for t in ("COD","DESCRIÇÃO","QUANTIDADE","STATUS","CEL.","OPERADOR QUE CONFERIU","DATA/HORA")]]
    for r in rows:
        details.append([cell(r["sku"]),cell(r["description"]),cell(r["quantity"]),
                        cell(r["status"],"warn" if r["status"]!="Conferido" else "table"),
                        cell(r["slot"]),cell(r["reviewed_by"] or "-"),cell(formatted(r["reviewed_at"]))])
    colwidths = [62,205,70,161,43,105,width-646]
    detail_table=styled_table(details,colwidths)
    warnings=[i for i,row in enumerate(rows,1) if row["status"]!="Conferido"]
    if warnings:
        detail_table.setStyle(TableStyle([("BACKGROUND",(0,i),(-1,i),AMBER_LIGHT) for i in warnings]))
    story.append(detail_table)
    def decoration(canvas,doc):
        canvas.saveState()
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(.5)
        canvas.line(35,33,w-35,33)
        canvas.setFont(bodyfont,8)
        canvas.setFillColor(MUTED)
        canvas.drawString(35,21,"PENTE FINO | RELATÓRIO DE AUDITORIA")
        canvas.drawRightString(w-35,21,f"Página {doc.page}")
        canvas.restoreState()
    doc.build(story,onFirstPage=decoration,onLaterPages=decoration)
    return out.getvalue()

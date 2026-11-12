"""Exportações fiscais legadas e pacotes informativos para contabilidade."""
import csv
import io
import json
import logging
import re
import zipfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Optional
from uuid import UUID
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.fiscal import NotaFiscal
from app.models.configuracao import Configuracao

logger = logging.getLogger(__name__)

# Diretório temporário para arquivos gerados
UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads" / "fiscal"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

REGIME_DESCRICOES = {
    1: "MEI - Microempreendedor Individual",
    2: "Simples Nacional",
    3: "Lucro Presumido",
    4: "Lucro Real",
}

# Fortaleza permanece em UTC-3 sem horario de verao, entao o offset fixo
# evita depender de zoneinfo no import deste modulo.
EXPORT_TIMEZONE = timezone(timedelta(hours=-3))


def _now_local() -> datetime:
    return datetime.now(EXPORT_TIMEZONE)


_PACOTE_TOMADOR_FIELDS = (
    "tipo_cliente", "cliente_nome", "cliente_documento", "cliente_endereco",
    "cliente_bairro", "cliente_cidade", "cliente_estado", "cliente_cep",
    "cliente_telefone", "cliente_email",
    "cliente_endereco_origem", "cliente_endereco_fonte", "cliente_endereco_conferido_em",
)
_PACOTE_CENTAVO = Decimal("0.01")


def _pacote_data_local(value: Any) -> datetime:
    """Datas históricas sem offset seguem a convenção operacional local da OS."""
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Data de prestação inválida no pacote contábil.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=EXPORT_TIMEZONE)
    return parsed.astimezone(EXPORT_TIMEZONE)


def _pacote_valor(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            raise ValueError("Valor monetário inválido no pacote contábil.")
        return amount.quantize(_PACOTE_CENTAVO, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Valor monetário inválido no pacote contábil.") from exc


def _pacote_documento(value: Any, *, validar_caracteres: bool = True) -> str:
    # CNPJ também admite A-Z. Remover letras criaria outro identificador.
    document = re.sub(r"[./\s-]", "", str(value or "").upper())
    if validar_caracteres and document and not re.fullmatch(r"[A-Z0-9]+", document):
        raise ValueError("CPF/CNPJ do tomador contém caracteres inválidos.")
    return document


def _pacote_tomador(item: dict, dados_tomador: Optional[dict]) -> dict:
    # Uma lista de OS pode conter diferentes tomadores. Um override global não
    # pode transformar cadastros distintos no mesmo CPF/CNPJ.
    override = dados_tomador or {}
    original_doc = _pacote_documento(item.get("cliente_documento") or item.get("clinica_cnpj"))
    override_doc = _pacote_documento(override.get("cliente_documento"))
    if override and (not override_doc or override_doc != original_doc):
        raise ValueError("Dados adicionais devem corresponder ao documento do tomador da OS.")
    clinic_fallbacks = {
        "cliente_nome": item.get("clinica_razao_social") or item.get("clinica_nome"),
        "cliente_documento": item.get("clinica_cnpj"),
        "cliente_endereco": _join_non_empty(", ", [item.get("clinica_endereco"), item.get("clinica_numero"), item.get("clinica_complemento")]),
        "cliente_bairro": item.get("clinica_bairro"), "cliente_cidade": item.get("clinica_cidade"),
        "cliente_estado": item.get("clinica_estado"), "cliente_cep": item.get("clinica_cep"),
        "cliente_telefone": item.get("clinica_telefone"), "cliente_email": item.get("clinica_email"),
    } if item.get("clinica_id") else {}
    result = {
        key: str(override.get(key) or item.get(key) or clinic_fallbacks.get(key) or "").strip()
        for key in _PACOTE_TOMADOR_FIELDS
    }
    result["cliente_documento"] = _pacote_documento(result["cliente_documento"])
    result["tipo_cliente"] = result["tipo_cliente"].upper()
    pattern = {"PF": r"[0-9]{11}", "PJ": r"[A-Z0-9]{12}[0-9]{2}"}.get(result["tipo_cliente"])
    if not result["cliente_nome"] or pattern is None or not re.fullmatch(pattern, result["cliente_documento"]):
        raise ValueError("Nome e CPF/CNPJ do tomador precisam estar confirmados para preparar o pacote.")
    return result


def _pacote_servicos(os_items: list[dict], competencia: str, dados_tomador: Optional[dict]) -> list[dict]:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", competencia or "") or competencia.startswith("0000"):
        raise ValueError("Competência inválida. Use YYYY-MM.")
    if not os_items:
        raise ValueError("Selecione ao menos uma OS para preparar o pacote.")
    ids: set[int] = set()
    result = []
    for item in os_items:
        os_id = item.get("os_id")
        if isinstance(os_id, bool) or not isinstance(os_id, int) or os_id <= 0 or os_id in ids:
            raise ValueError("Seleção contém ID de OS inválido ou repetido.")
        ids.add(os_id)
        if str(item.get("status_os") or "").strip().casefold() == "cancelado":
            raise ValueError("OS cancelada não pode integrar um pacote contábil.")
        data = _pacote_data_local(item.get("data_atendimento"))
        if data.strftime("%Y-%m") != competencia:
            raise ValueError("Todas as OS devem pertencer à competência de prestação selecionada.")
        bruto = _pacote_valor(item.get("valor_servico"))
        desconto = _pacote_valor(item.get("valor_desconto", 0))
        liquido = _pacote_valor(item.get("valor_final"))
        if bruto < 0 or desconto < 0 or liquido <= 0 or bruto - desconto != liquido:
            raise ValueError("Valores bruto, desconto e líquido da OS não reconciliam.")
        result.append({
            **_pacote_tomador(item, dados_tomador),
            "os_id": os_id, "numero_os": str(item.get("numero_os") or os_id),
            "competencia": competencia, "data_prestacao": data.date().isoformat(),
            "servico_nome": str(item.get("servico_nome") or "Serviço veterinário"),
            "valor_servico": bruto, "valor_desconto": desconto, "valor_final": liquido,
            "status_financeiro": str(item.get("status_os") or "Não informado"),
        })
    return sorted(result, key=lambda row: (row["cliente_documento"], row["data_prestacao"], row["os_id"]))


def _pacote_resumo(servicos: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], dict] = {}
    for row in servicos:
        key = (row["cliente_documento"], row["competencia"])
        if key not in grouped:
            grouped[key] = {
                **{field: row[field] for field in _PACOTE_TOMADOR_FIELDS},
                "competencia": row["competencia"], "quantidade_os": 0,
                "valor_servico": Decimal("0.00"), "valor_desconto": Decimal("0.00"),
                "valor_final": Decimal("0.00"), "os_ids": [],
            }
        group = grouped[key]
        group["quantidade_os"] += 1
        group["os_ids"].append(row["os_id"])
        for field in ("valor_servico", "valor_desconto", "valor_final"):
            group[field] += row[field]
        for field in _PACOTE_TOMADOR_FIELDS:
            if not group[field] and row[field]:
                group[field] = row[field]
    return list(grouped.values())


def _pacote_pendencias(items: Optional[list[dict]]) -> list[dict]:
    """Somente campos de conferência; nunca serializa o objeto recebido inteiro."""
    rows = []
    for item in items or []:
        motivos = item.get("motivos_pendencia") or item.get("motivos") or item.get("motivo") or []
        if isinstance(motivos, str):
            motivos = [motivos]
        rows.append({
            "os_id": item.get("os_id"), "numero_os": str(item.get("numero_os") or item.get("os_id") or ""),
            "data_prestacao": str(item.get("data_prestacao") or ""),
            "cliente_nome": str(item.get("cliente_nome") or ""),
            # Cadastros inválidos são pendências visíveis e não participam do
            # agrupamento/totais. Preservar seus caracteres permite corrigi-los.
            "cliente_documento": _pacote_documento(item.get("cliente_documento"), validar_caracteres=False),
            "motivos": [str(reason) for reason in motivos],
        })
    return rows


def _pacote_prestador(config: dict) -> dict:
    return {
        "nome": str(config.get("nome_empresa") or "Fort Cordis"),
        "cnpj_ie_cadastrado": str(config.get("inscricao_estadual") or ""),
        "inscricao_municipal": str(config.get("inscricao_municipal") or ""),
        "endereco": str(config.get("endereco") or ""), "cidade": str(config.get("cidade") or ""),
        "estado": str(config.get("estado") or ""), "telefone": str(config.get("telefone") or ""),
        "email": str(config.get("email") or ""), "cnae_cadastrado": str(config.get("cnae") or ""),
        "regime_tributario": str(config.get("regime_tributario") or ""),
    }


def _pacote_totais(rows: list[dict]) -> dict[str, str]:
    return {
        field: format(sum((row[field] for row in rows), Decimal("0.00")), ".2f")
        for field in ("valor_servico", "valor_desconto", "valor_final")
    }


def _pacote_xlsx(servicos: list[dict], resumo: list[dict], pendencias: list[dict], manifesto: dict) -> bytes:
    Workbook, Alignment, Font, PatternFill, get_column_letter = _load_openpyxl_exports()
    wb = Workbook()
    wb.remove(wb.active)
    sheets = [
        ("Resumo", ["Competência", "Tipo", "Tomador", "CPF/CNPJ", "Endereço", "Bairro", "Cidade", "UF", "CEP", "Telefone", "E-mail", "Quantidade OS", "Bruto", "Desconto", "Líquido"],
         [[r[field] for field in ("competencia", "tipo_cliente", "cliente_nome", "cliente_documento", "cliente_endereco", "cliente_bairro", "cliente_cidade", "cliente_estado", "cliente_cep", "cliente_telefone", "cliente_email", "quantidade_os", "valor_servico", "valor_desconto", "valor_final")] for r in resumo], {13, 14, 15}),
        ("Serviços", ["OS ID", "OS", "Competência", "Data de prestação", "Tipo", "Tomador", "CPF/CNPJ", "Serviço", "Bruto", "Desconto", "Líquido", "Status financeiro"],
         [[r[field] for field in ("os_id", "numero_os", "competencia", "data_prestacao", "tipo_cliente", "cliente_nome", "cliente_documento", "servico_nome", "valor_servico", "valor_desconto", "valor_final", "status_financeiro")] for r in servicos], {9, 10, 11}),
        ("Pendências", ["OS ID", "OS", "Data de prestação", "Tomador", "CPF/CNPJ", "Motivos para conferência"],
         [[r["os_id"], r["numero_os"], r["data_prestacao"], r["cliente_nome"], r["cliente_documento"], "; ".join(r["motivos"])] for r in pendencias], set()),
    ]
    for name, headers, values, money_columns in sheets:
        ws = wb.create_sheet(name)
        ws.append(headers)
        for value_row in values:
            ws.append(value_row)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for row in ws:
            for cell in row:
                # Cadastros são texto, inclusive quando começam com '='.
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                if cell.row == 1:
                    cell.fill = PatternFill("solid", fgColor="173B44")
                    cell.font = Font(bold=True, color="FFFFFF")
                elif cell.column in money_columns:
                    cell.number_format = '#,##0.00'
        for idx, header in enumerate(headers, 1):
            width = max([len(header), *[len(str(row[idx - 1] or "")) for row in values]])
            ws.column_dimensions[get_column_letter(idx)].width = min(max(width + 2, 14), 44)
        ws.row_dimensions[1].height = 30
        for row in ws.iter_rows(min_row=2):
            lines = max(
                sum(max(1, (len(part) + int(ws.column_dimensions[cell.column_letter].width) - 3)
                        // (int(ws.column_dimensions[cell.column_letter].width) - 2))
                    for part in str(cell.value or "").split("\n"))
                for cell in row
            )
            ws.row_dimensions[row[0].row].height = min(409, max(22, lines * 13 + 8))
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.print_title_rows = "1:1"
    ws = wb.create_sheet("Prestador e lote")
    metadata = [
        ["Relatório informativo para contador", "Não é nota fiscal e não comprova envio ou emissão."],
        ["Lote", manifesto["lote_id"]], ["Competência de prestação", manifesto["competencia"]],
        ["Gerado em (UTC-03:00)", manifesto["gerado_em"]],
        *[[key.replace("_", " "), value] for key, value in manifesto["prestador"].items()],
        ["Total bruto", Decimal(manifesto["totais"]["valor_servico"])],
        ["Total desconto", Decimal(manifesto["totais"]["valor_desconto"])],
        ["Total líquido", Decimal(manifesto["totais"]["valor_final"])],
        ["Conferência", "A competência segue a data de prestação conferida da OS, independentemente do recebimento."],
        ["Tributos", "ISS e demais enquadramentos devem ser conferidos pelo contador."],
    ]
    if manifesto.get("rotina"):
        metadata.extend([["Modo de preparação", manifesto["rotina"]["modo"]],
                         ["Corte da rotina (Fortaleza)", manifesto["rotina"].get("corte_em") or "Por serviço"]])
    for row in metadata:
        ws.append(row)
    for row in ws:
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = "s"
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        row[0].font = Font(bold=True)
    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 88
    wb.properties.title = "Serviços por competência para contador"
    wb.properties.subject = "Relatório informativo de serviços; sem emissão fiscal"
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _pacote_pdf(servicos: list[dict], resumo: list[dict], pendencias: list[dict], manifesto: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm,
                            topMargin=1.4 * cm, bottomMargin=1.6 * cm,
                            title="Conferência de serviços por competência", author=manifesto["prestador"]["nome"])
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("PacoteNormal", parent=styles["Normal"], fontSize=9, leading=12, spaceAfter=4)
    introduction = ParagraphStyle("PacoteIntroduction", parent=normal, keepWithNext=True)
    small = ParagraphStyle("PacoteSmall", parent=normal, fontSize=8, leading=10, spaceAfter=0)
    money = ParagraphStyle("PacoteMoney", parent=small, alignment=2)
    heading = ParagraphStyle("PacoteHeading", parent=styles["Heading2"], fontSize=11, leading=14,
                             textColor=colors.HexColor("#173B44"), spaceBefore=12, spaceAfter=6,
                             keepWithNext=True)

    def p(value: Any, style=normal):
        return Paragraph(escape(str(value or "-")).replace("\n", "<br/>"), style)

    def table(values: list[list], widths: list[float], *, repeat=0):
        obj = Table(values, colWidths=widths, repeatRows=repeat, splitInRow=1)
        rules = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5),
                 ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 5),
                 ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LINEBELOW", (0, 0), (-1, -1), .35, colors.HexColor("#DBE3E5"))]
        if repeat:
            rules += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF1F2"))]
        obj.setStyle(TableStyle(rules))
        return obj

    elements = [Paragraph("Serviços para o contador", styles["Title"]),
                p(f"Competência de prestação: {manifesto['competencia']} | Lote: {manifesto['lote_id']}"),
                p(f"Gerado em: {manifesto['gerado_em']} (horário de Fortaleza)"),
                p("Relatório informativo de conferência. Não é nota fiscal e não comprova envio ou emissão.")]
    if manifesto.get("rotina"):
        rotina = manifesto["rotina"]
        elements.append(p(f"Preparação: {rotina['modo']} | Corte: {rotina.get('corte_em') or 'Por serviço'} | Fortaleza | Confirmação manual"))
    prestador = manifesto["prestador"]
    elements.append(Paragraph("Prestador", heading))
    fields = [("Nome", prestador["nome"]), ("CNPJ/IE cadastrado", prestador["cnpj_ie_cadastrado"]),
              ("Inscrição municipal", prestador["inscricao_municipal"]),
              ("Endereço", _join_non_empty(" / ", [prestador["endereco"], prestador["cidade"], prestador["estado"]])),
              ("Contato", _join_non_empty(" / ", [prestador["telefone"], prestador["email"]])),
              ("CNAE cadastrado do prestador", prestador["cnae_cadastrado"]), ("Regime cadastrado", prestador["regime_tributario"])]
    elements.append(table([[p(label, small), p(value, small)] for label, value in fields], [4.6 * cm, doc.width - 4.6 * cm]))
    totals = manifesto["totais"]
    elements += [Paragraph("Resumo do lote", heading),
                 p(f"{len(servicos)} OS | {len(resumo)} tomadores | Bruto: {_format_currency(Decimal(totals['valor_servico']))} | Descontos: {_format_currency(Decimal(totals['valor_desconto']))} | Líquido: {_format_currency(Decimal(totals['valor_final']))}"),
                 p("Valores do serviço independem do recebimento. ISS e demais enquadramentos devem ser conferidos pelo contador.")]
    for group in resumo:
        elements.append(Paragraph("Tomador - " + escape(group["cliente_nome"]), heading))
        info = [("CPF/CNPJ", group["cliente_documento"]), ("Endereço", _format_endereco_completo(group)),
                ("Cidade / UF / CEP", _join_non_empty(" / ", [group["cliente_cidade"], group["cliente_estado"], group["cliente_cep"]])),
                ("Origem do endereço", "Cadastro CNPJ conferido" if group.get("cliente_endereco_origem") == "cadastro_cnpj" else "Cadastro do tomador"),
                ("Contato", _join_non_empty(" / ", [group["cliente_telefone"], group["cliente_email"]]))]
        elements.append(table([[p(label, small), p(value, small)] for label, value in info], [3.5 * cm, doc.width - 3.5 * cm]))
        elements.append(Spacer(1, .2 * cm))
        values = [[p(text, small) for text in ["OS / prestação", "Serviço", "Bruto", "Desconto", "Líquido", "Financeiro"]]]
        for row in servicos:
            if row["cliente_documento"] == group["cliente_documento"]:
                values.append([p(f"{row['numero_os']}\n{_format_date(row['data_prestacao'])}", small), p(row["servico_nome"], small),
                               p(_format_currency(row["valor_servico"]), money), p(_format_currency(row["valor_desconto"]), money),
                               p(_format_currency(row["valor_final"]), money), p(row["status_financeiro"], small)])
        widths = [3.0 * cm, doc.width - 11.0 * cm, 2.0 * cm, 2.0 * cm, 2.0 * cm, 2.0 * cm]
        elements.append(table(values, widths, repeat=1))
        elements.append(p(f"Total do tomador: {_format_currency(group['valor_final'])} | {group['quantidade_os']} OS"))
    elements.append(Paragraph("Pendências para conferência", heading))
    if pendencias:
        elements.append(p("As OS abaixo não integram os totais dos serviços selecionados neste lote.", introduction))
        values = [[p(value, small) for value in ["OS", "Tomador", "Motivos"]]]
        values += [[p(row["numero_os"], small), p(row["cliente_nome"], small), p("; ".join(row["motivos"]), small)] for row in pendencias]
        elements.append(table(values, [3 * cm, 5 * cm, doc.width - 8 * cm], repeat=1))
    else:
        elements.append(p("Nenhuma pendência informada na prévia deste lote."))
    footer = f"Fort Cordis | Conferência | {manifesto['competencia']} | Lote {manifesto['lote_id'][:8]}"
    doc.build(elements, onFirstPage=lambda canvas, obj: _draw_pdf_footer(canvas, obj, footer),
              onLaterPages=lambda canvas, obj: _draw_pdf_footer(canvas, obj, footer))
    return buffer.getvalue()


def gerar_pacote_contador(
    os_items: list[dict[str, Any]], db_session, *, competencia: str, lote_id: str,
    pendencias: Optional[list[dict]] = None, dados_tomador: Optional[dict[str, Any]] = None,
    contexto_rotina: Optional[dict[str, Any]] = None,
) -> tuple[bytes, str]:
    """Prepara informações para contador; não emite nota nem realiza envio.

    O chamador persiste estes bytes junto ao vínculo exclusivo das OS, em uma
    única transação. Downloads e retries devem reutilizar o ZIP persistido.
    """
    try:
        lote_id = str(UUID(str(lote_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Identificador do lote inválido.") from exc
    servicos = _pacote_servicos(os_items, competencia, dados_tomador)
    resumo = _pacote_resumo(servicos)
    pending_rows = _pacote_pendencias(pendencias)
    manifesto = {
        "versao": 1, "tipo": "informacoes_para_contador", "lote_id": lote_id,
        "competencia": competencia, "gerado_em": _now_local().isoformat(timespec="seconds"),
        "fuso_horario": "America/Fortaleza", "criterio_competencia": "data_prestacao_os_conferida",
        "os_ids": [row["os_id"] for row in servicos], "quantidade_os": len(servicos),
        "quantidade_tomadores": len(resumo), "quantidade_pendencias": len(pending_rows),
        "totais": _pacote_totais(servicos), "prestador": _pacote_prestador(_get_configuracao(db_session)),
        "tomadores": [
            {**{field: row[field] for field in _PACOTE_TOMADOR_FIELDS}, "competencia": competencia,
             "os_ids": row["os_ids"], "quantidade_os": row["quantidade_os"],
             "totais": {key: format(row[key], ".2f") for key in ("valor_servico", "valor_desconto", "valor_final")}}
            for row in resumo
        ],
        "observacao": "Relatório informativo. Não comprova envio ao contador ou emissão de nota fiscal.",
    }
    if contexto_rotina is not None:
        manifesto["rotina"] = {
            "modo": contexto_rotina["modo"], "data_corte": contexto_rotina.get("data_corte"),
            "corte_em": contexto_rotina.get("corte_em"), "timezone": "America/Fortaleza", "automatico": False,
        }
    texto = [f"Informações para emissão pelo contador - competência de prestação {competencia}",
             f"Prestador: {manifesto['prestador']['nome']}", f"Lote: {lote_id}",
             f"Gerado em: {manifesto['gerado_em']}", "",
             "Seguem os serviços conferidos por data de prestação, independentemente do recebimento."]
    if contexto_rotina is not None:
        texto += [f"Preparação: {manifesto['rotina']['modo']} | Corte: {manifesto['rotina']['corte_em'] or 'Por serviço'} | Fortaleza | Ação manual"]
    for group in resumo:
        texto += ["", f"Tomador: {group['cliente_nome']} | CPF/CNPJ: {group['cliente_documento']}",
                  f"Competência: {competencia} | {group['quantidade_os']} OS",
                  f"Bruto: {_format_currency(group['valor_servico'])} | Desconto: {_format_currency(group['valor_desconto'])} | Líquido: {_format_currency(group['valor_final'])}"]
    texto += ["", f"Total dos serviços: {_format_currency(Decimal(manifesto['totais']['valor_final']))}",
              f"Pendências fora dos totais: {len(pending_rows)}. Detalhes na planilha e no PDF.",
              "Solicito conferir os dados e o enquadramento tributário antes da emissão.",
              "Este pacote contém informações e não é nota fiscal."]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("servicos_contador.xlsx", _pacote_xlsx(servicos, resumo, pending_rows, manifesto))
        archive.writestr("conferencia_contador.pdf", _pacote_pdf(servicos, resumo, pending_rows, manifesto))
        archive.writestr("mensagem_contador.txt", "\n".join(texto).encode("utf-8"))
        archive.writestr("manifesto.json", json.dumps(manifesto, ensure_ascii=False, indent=2).encode("utf-8"))
    return output.getvalue(), f"FortCordis_{competencia}_{lote_id[:8]}.zip"


def _load_openpyxl_exports():
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    return Workbook, Alignment, Font, PatternFill, get_column_letter


def _get_configuracao(db_session) -> dict:
    """Carrega dados da empresa (prestador) da configuração."""
    config = db_session.query(Configuracao).first()
    if not config:
        return {}
    return {
        "nome_empresa": config.nome_empresa or "",
        "endereco": config.endereco or "",
        "telefone": config.telefone or "",
        "email": config.email or "",
        "website": config.website or "",
        "cidade": config.cidade or "",
        "estado": config.estado or "",
        "inscricao_municipal": config.inscricao_municipal or "",
        "inscricao_estadual": config.inscricao_estadual or "",
        "cnae": config.cnae or "",
        "regime_tributario": REGIME_DESCRICOES.get(
            config.regime_tributario, ""
        ) if config.regime_tributario else "",
        "codigo_municipio": config.codigo_municipio_servico or "230440",  # Fortaleza
        "mostrar_logomarca": bool(config.mostrar_logomarca) if config.mostrar_logomarca is not None else True,
        "logomarca_dados": config.logomarca_dados,
    }


def _nota_to_dict(nota: NotaFiscal) -> dict:
    """Converte NotaFiscal em dict."""
    return {
        "numero": nota.numero or "",
        "serie": nota.serie or "1",
        "tipo_cliente": nota.tipo_cliente or "",
        "cliente_nome": nota.cliente_nome or "",
        "cliente_documento": nota.cliente_documento or "",
        "cliente_endereco": nota.cliente_endereco or "",
        "cliente_bairro": nota.cliente_bairro or "",
        "cliente_cidade": nota.cliente_cidade or "",
        "cliente_estado": nota.cliente_estado or "",
        "cliente_cep": nota.cliente_cep or "",
        "cliente_telefone": nota.cliente_telefone or "",
        "cliente_email": nota.cliente_email or "",
        "valor_servico": float(nota.valor_servico or 0),
        "valor_desconto": float(nota.valor_desconto or 0),
        "valor_final": float(nota.valor_final or 0),
        "aliquota_iss": nota.aliquota_iss or 5.0,
        "valor_iss": float(nota.valor_iss or 0),
        "atividade_cnae": nota.atividade_cnae or "",
        "descricao_servico": nota.descricao_servico or "",
        "natureza_operacao": nota.natureza_operacao or "Tributação no município",
        "os_id": nota.os_id,
        "created_at": nota.created_at or "",
    }


# ─── PDF ───────────────────────────────────────────────────────────────────────

def exportar_pdf(notas: list[NotaFiscal], db_session) -> tuple[bytes, str]:
    """
    Gera um PDF com uma ou mais notas fiscais em formato profissional.
    Retorna (bytes do PDF, nome do arquivo).
    """
    config = _get_configuracao(db_session)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title",
        parent=styles["Heading1"],
        fontSize=16,
        alignment=1,
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        fontSize=9,
        alignment=1,
        spaceAfter=12,
    )
    section_style = ParagraphStyle(
        "Section",
        parent=styles["Heading3"],
        fontSize=11,
        spaceAfter=6,
        spaceBefore=12,
        textColor=colors.HexColor("#2c3e50"),
    )
    field_style = ParagraphStyle(
        "Field",
        parent=styles["Normal"],
        fontSize=9,
        spaceAfter=2,
    )

    elements = []

    for i, nota in enumerate(notas):
        if i > 0:
            elements.append(Spacer(1, 1.5 * cm))
        nd = _nota_to_dict(nota)

        # Cabeçalho
        elements.append(Paragraph("NOTA FISCAL DE SERVIÇOS", title_style))
        elements.append(
            Paragraph(
                f"<b>Nº {nd['numero']}</b> &nbsp;&nbsp; Série: {nd['serie']}",
                subtitle_style,
            )
        )

        # Dados do Prestador
        elements.append(Paragraph("PRESTADOR DE SERVIÇOS", section_style))
        elements.append(
            Paragraph(f"<b>Razão Social:</b> {config.get('nome_empresa', 'N/A')}", field_style)
        )
        elements.append(
            Paragraph(
                f"<b>Endereço:</b> {config.get('endereco', 'N/A')} - "
                f"{config.get('cidade', '')}, {config.get('estado', '')}",
                field_style,
            )
        )
        elements.append(
            Paragraph(
                f"<b>CNPJ:</b> {config.get('inscricao_estadual', 'N/A')} &nbsp;&nbsp; "
                f"<b>IM:</b> {config.get('inscricao_municipal', 'N/A')} &nbsp;&nbsp; "
                f"<b>CNAE:</b> {config.get('cnae', 'N/A')}",
                field_style,
            )
        )
        elements.append(
            Paragraph(
                f"<b>Telefone:</b> {config.get('telefone', '')} &nbsp;&nbsp; "
                f"<b>Email:</b> {config.get('email', '')}",
                field_style,
            )
        )

        # Dados do Tomador
        elements.append(Paragraph("TOMADOR DE SERVIÇOS", section_style))
        elements.append(
            Paragraph(f"<b>Nome/Razão Social:</b> {nd['cliente_nome']}", field_style)
        )
        elements.append(
            Paragraph(
                f"<b>{'CPF' if nd['tipo_cliente'] == 'PF' else 'CNPJ'}:</b> "
                f"{nd['cliente_documento']}",
                field_style,
            )
        )
        elements.append(
            Paragraph(
                f"<b>Endereço:</b> {nd['cliente_endereco']}, {nd['cliente_bairro']} - "
                f"{nd['cliente_cidade']}, {nd['cliente_estado']} | CEP: {nd['cliente_cep']}",
                field_style,
            )
        )
        if nd["cliente_telefone"]:
            elements.append(
                Paragraph(
                    f"<b>Telefone:</b> {nd['cliente_telefone']} &nbsp;&nbsp; "
                    f"<b>Email:</b> {nd['cliente_email'] or 'N/A'}",
                    field_style,
                )
            )

        # Dados do Serviço
        elements.append(Paragraph("DISCRIMINAÇÃO DO(S) SERVIÇO(S)", section_style))
        elements.append(
            Paragraph(
                f"<b>CNAE:</b> {nd['atividade_cnae']} &nbsp;&nbsp; "
                f"<b>Natureza:</b> {nd['natureza_operacao']}",
                field_style,
            )
        )
        elements.append(
            Paragraph(
                f"<b>Descrição:</b> {nd['descricao_servico'] or 'Serviço veterinário especializado.'}",
                field_style,
            )
        )
        if nd.get("os_id"):
            elements.append(
                Paragraph(f"<b>OS Ref.:</b> #{nd['os_id']}", field_style)
            )

        # Tabela de Valores
        elements.append(Paragraph("VALORES", section_style))
        table_data = [
            ["Discriminação", "Valor (R$)"],
            ["Valor do Serviço", f"{nd['valor_servico']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")],
            ["(-) Desconto", f"({nd['valor_desconto']:,.2f})".replace(",", "X").replace(".", ",").replace("X", ".")],
            ["= Valor Final", f"{nd['valor_final']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")],
            [f"ISS ({nd['aliquota_iss']}%)", f"{nd['valor_iss']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")],
        ]
        table = Table(table_data, colWidths=[10 * cm, 6 * cm])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#ecf0f1")),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f9f9f9")]),
                ]
            )
        )
        elements.append(table)

        # Observações
        if nd.get("observacoes"):
            elements.append(Spacer(1, 0.3 * cm))
            elements.append(
                Paragraph(f"<b>Observações:</b> {nd['observacoes']}", field_style)
            )

        # Rodapé
        elements.append(Spacer(1, 0.5 * cm))
        elements.append(
            Paragraph(
                f"<i>Documento gerado em {_now_local().strftime('%d/%m/%Y %H:%M')} | "
                f"{config.get('nome_empresa', 'Fort Cordis')}</i>",
                subtitle_style,
            )
        )

    doc.build(elements)
    buffer.seek(0)
    filename = f"notas_fiscais_{_now_local().strftime('%Y%m%d_%H%M%S')}.pdf"
    return buffer.read(), filename


# ─── CSV ───────────────────────────────────────────────────────────────────────

def exportar_csv(notas: list[NotaFiscal], db_session) -> tuple[bytes, str]:
    """
    Gera um arquivo CSV com os dados das notas fiscais.
    Colunas compatíveis com sistemas de importação contábil (NFX Manager).
    """
    config = _get_configuracao(db_session)

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_ALL)

    # Cabeçalho
    writer.writerow([
        "Numero NF",
        "Serie",
        "Tipo Cliente",
        "Razao Social Tomador",
        "CNPJ/CPF Tomador",
        "Endereco Tomador",
        "Bairro Tomador",
        "Cidade Tomador",
        "UF Tomador",
        "CEP Tomador",
        "Telefone Tomador",
        "Email Tomador",
        "Valor Servico",
        "Desconto",
        "Valor Final",
        "Aliquota ISS",
        "Valor ISS",
        "CNAE Atividade",
        "Descricao Servico",
        "Natureza Operacao",
        "Municipio Servico",
        "Regime Tributario",
        "Prestador Nome",
        "Prestador CNPJ",
        "Prestador IM",
        "Data Emissao",
        "OS Referencia",
    ])

    for nota in notas:
        nd = _nota_to_dict(nota)
        writer.writerow([
            nd["numero"],
            nd["serie"],
            nd["tipo_cliente"],
            nd["cliente_nome"],
            nd["cliente_documento"],
            nd["cliente_endereco"],
            nd["cliente_bairro"],
            nd["cliente_cidade"],
            nd["cliente_estado"],
            nd["cliente_cep"],
            nd["cliente_telefone"],
            nd["cliente_email"],
            f"{nd['valor_servico']:.2f}".replace(".", ","),
            f"{nd['valor_desconto']:.2f}".replace(".", ","),
            f"{nd['valor_final']:.2f}".replace(".", ","),
            f"{nd['aliquota_iss']:.2f}".replace(".", ","),
            f"{nd['valor_iss']:.2f}".replace(".", ","),
            nd["atividade_cnae"],
            nd["descricao_servico"],
            nd["natureza_operacao"],
            config.get("codigo_municipio", "230440"),
            config.get("regime_tributario", ""),
            config.get("nome_empresa", ""),
            config.get("inscricao_estadual", ""),
            config.get("inscricao_municipal", ""),
            nd["created_at"][:10] if nd["created_at"] else "",
            str(nd.get("os_id", "")),
        ])

    content = output.getvalue().encode("utf-8-sig")
    filename = f"notas_fiscais_{_now_local().strftime('%Y%m%d_%H%M%S')}.csv"
    return content, filename


# ─── Excel ────────────────────────────────────────────────────────────────────

def exportar_xlsx(notas: list[NotaFiscal], db_session) -> tuple[bytes, str]:
    """
    Gera um arquivo Excel com os dados das notas fiscais.
    """
    Workbook, Alignment, Font, PatternFill, get_column_letter = _load_openpyxl_exports()
    config = _get_configuracao(db_session)
    wb = Workbook()

    # Aba 1: Notas Fiscais
    ws = wb.active
    ws.title = "Notas Fiscais"

    headers = [
        "Numero NF", "Serie", "Tipo", "Cliente", "Documento",
        "Endereco", "Bairro", "Cidade", "UF", "CEP",
        "Telefone", "Email", "Valor Servico", "Desconto", "Valor Final",
        "Aliquota ISS (%)", "Valor ISS", "CNAE", "Descricao Servico",
        "Natureza", "Municipio", "Regime", "Data Emissao", "OS Ref.",
    ]
    ws.append(headers)

    header_fill = PatternFill(start_color="2C3E50", end_color="2C3E50", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    for col, _ in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    for nota in notas:
        nd = _nota_to_dict(nota)
        row = [
            nd["numero"],
            nd["serie"],
            nd["tipo_cliente"],
            nd["cliente_nome"],
            nd["cliente_documento"],
            nd["cliente_endereco"],
            nd["cliente_bairro"],
            nd["cliente_cidade"],
            nd["cliente_estado"],
            nd["cliente_cep"],
            nd["cliente_telefone"],
            nd["cliente_email"],
            nd["valor_servico"],
            nd["valor_desconto"],
            nd["valor_final"],
            nd["aliquota_iss"],
            nd["valor_iss"],
            nd["atividade_cnae"],
            nd["descricao_servico"],
            nd["natureza_operacao"],
            config.get("codigo_municipio", ""),
            config.get("regime_tributario", ""),
            nd["created_at"][:10] if nd["created_at"] else "",
            str(nd.get("os_id", "")),
        ]
        ws.append(row)

    # Ajuste de largura das colunas
    for col in ws.columns:
        max_length = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            except (TypeError, AttributeError):
                pass
        ws.column_dimensions[col_letter].width = min(max_length + 2, 40)

    # Aba 2: Resumo
    ws2 = wb.create_sheet("Resumo")
    ws2.append(["RESUMO FISCAL"])
    ws2.cell(row=1, column=1).font = Font(bold=True, size=14)
    ws2.append([])
    ws2.append(["Prestador de Serviços"])
    ws2.append(["Razão Social", config.get("nome_empresa", "")])
    ws2.append(["IM", config.get("inscricao_municipal", "")])
    ws2.append(["IE/CNPJ", config.get("inscricao_estadual", "")])
    ws2.append(["CNAE", config.get("cnae", "")])
    ws2.append(["Regime Tributário", config.get("regime_tributario", "")])
    ws2.append(["Município", f"{config.get('cidade', '')} ({config.get('estado', '')})"])
    ws2.append([])
    ws2.append(["Totais"])
    total_servico = sum(float(n.valor_servico or 0) for n in notas)
    total_desconto = sum(float(n.valor_desconto or 0) for n in notas)
    total_final = sum(float(n.valor_final or 0) for n in notas)
    total_iss = sum(float(n.valor_iss or 0) for n in notas)
    ws2.append(["Total Valor Serviço", f"R$ {total_servico:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")])
    ws2.append(["Total Desconto", f"R$ {total_desconto:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")])
    ws2.append(["Total Valor Final", f"R$ {total_final:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")])
    ws2.append(["Total ISS", f"R$ {total_iss:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")])
    ws2.append(["Quantidade de Notas", len(notas)])
    ws2.column_dimensions["A"].width = 25
    ws2.column_dimensions["B"].width = 40

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    filename = f"notas_fiscais_{_now_local().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return buffer.read(), filename


def exportar_os_csv(
    os_items: list[dict[str, Any]],
    db_session,
    dados_tomador: Optional[dict[str, Any]] = None,
) -> tuple[bytes, str]:
    """Exporta dados consolidados por clinica para contabilidade (CSV)."""
    config = _get_configuracao(db_session)
    rows = _build_consolidated_export_rows(os_items, config, dados_tomador=dados_tomador)
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_ALL)

    writer.writerow(_consolidated_export_headers())
    for row in rows:
        writer.writerow(_consolidated_export_values(row, numbers_as_text=True))

    content = output.getvalue().encode("utf-8-sig")
    filename = f"dados_contabeis_{_now_local().strftime('%Y%m%d_%H%M%S')}.csv"
    return content, filename


def exportar_os_xlsx(
    os_items: list[dict[str, Any]],
    db_session,
    dados_tomador: Optional[dict[str, Any]] = None,
) -> tuple[bytes, str]:
    """Exporta dados consolidados por clinica para contabilidade (XLSX)."""
    Workbook, Alignment, Font, PatternFill, get_column_letter = _load_openpyxl_exports()
    config = _get_configuracao(db_session)
    rows = _build_consolidated_export_rows(os_items, config, dados_tomador=dados_tomador)
    wb = Workbook()
    ws = wb.active
    ws.title = "Dados Fiscais"
    headers = _consolidated_export_headers()
    ws.append(headers)

    header_fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    for idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    total_servico = 0.0
    total_iss = 0.0

    for row in rows:
        total_servico += float(row["valor_servico"] or 0)
        total_iss += float(row["valor_iss"] or 0)
        ws.append(_consolidated_export_values(row, numbers_as_text=False))

    for col in ws.columns:
        max_length = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            except (TypeError, AttributeError):
                pass
        ws.column_dimensions[col_letter].width = min(max_length + 2, 42)

    ws2 = wb.create_sheet("Resumo")
    ws2.append(["RESUMO EXPORTACAO CONTABIL"])
    ws2.cell(row=1, column=1).font = Font(bold=True, size=14)
    ws2.append([])
    ws2.append(["Prestador", config.get("nome_empresa", "")])
    ws2.append(["Clinicas consolidadas", len(rows)])
    ws2.append(["Total Valor Servico", _format_currency(total_servico)])
    ws2.append(["Total ISS", _format_currency(total_iss)])
    ws2.append(["Gerado em", _now_local().strftime("%d/%m/%Y %H:%M")])
    ws2.column_dimensions["A"].width = 28
    ws2.column_dimensions["B"].width = 42

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    filename = f"dados_contabeis_{_now_local().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return buffer.read(), filename


def _build_logo_flowable(
    config: dict[str, Any],
    max_width: float = 3.2 * cm,
    max_height: float = 2.0 * cm,
):
    if not config.get("mostrar_logomarca", True):
        return None
    raw_logo = config.get("logomarca_dados")
    if not raw_logo:
        return None
    try:
        logo_io = io.BytesIO(raw_logo)
        logo_reader = ImageReader(logo_io)
        width, height = logo_reader.getSize()
        if not width or not height:
            return None
        scale = min(max_width / float(width), max_height / float(height))
        if scale <= 0:
            return None
        logo = Image(io.BytesIO(raw_logo), width=width * scale, height=height * scale)
        logo.hAlign = "LEFT"
        return logo
    except Exception:
        return None


def _draw_pdf_footer(canvas, doc, footer_text: str):
    canvas.saveState()
    footer_y = 0.7 * cm
    line_y = footer_y + 0.35 * cm
    canvas.setStrokeColor(colors.HexColor("#D1D5DB"))
    canvas.setLineWidth(0.5)
    canvas.line(doc.leftMargin, line_y, A4[0] - doc.rightMargin, line_y)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#6B7280"))
    canvas.drawString(doc.leftMargin, footer_y, (footer_text or "")[:150])
    canvas.drawRightString(A4[0] - doc.rightMargin, footer_y, f"Pagina {canvas.getPageNumber()}")
    canvas.restoreState()


def exportar_os_pdf(
    os_items: list[dict[str, Any]],
    db_session,
    dados_tomador: Optional[dict[str, Any]] = None,
) -> tuple[bytes, str]:
    """Exporta dados consolidados por clinica para contabilidade em PDF."""
    config = _get_configuracao(db_session)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleContabil", parent=styles["Heading1"], fontSize=14, alignment=1, spaceAfter=6)
    normal_style = ParagraphStyle("NormalContabil", parent=styles["Normal"], fontSize=9, leading=12)
    section_style = ParagraphStyle("SectionContabil", parent=styles["Heading3"], fontSize=10, spaceAfter=4, textColor=colors.HexColor("#1F2937"))

    rows = _build_consolidated_export_rows(os_items, config, dados_tomador=dados_tomador)
    total_servico = sum(float(r["valor_servico"] or 0) for r in rows)
    total_iss = sum(float(r["valor_iss"] or 0) for r in rows)
    generated_at = _now_local().strftime("%d/%m/%Y %H:%M")

    header_body_text = (
        f"<b>Prestador:</b> {config.get('nome_empresa', 'Fort Cordis')}<br/>"
        f"<b>Gerado em:</b> {generated_at}<br/>"
        f"<b>Clinicas consolidadas:</b> {len(rows)}<br/>"
        f"<b>Total servicos:</b> {_format_currency(total_servico)}<br/>"
        f"<b>Total ISS:</b> {_format_currency(total_iss)}"
    )
    header_text = f"<b>DADOS FISCAIS PARA CONTABILIDADE</b><br/>{header_body_text}"

    elements = []
    logo = _build_logo_flowable(config)
    if logo:
        header_table = Table(
            [[logo, Paragraph(header_text, normal_style)]],
            colWidths=[3.6 * cm, doc.width - (3.6 * cm)],
        )
        header_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        elements.append(header_table)
    else:
        elements.append(Paragraph("DADOS FISCAIS PARA CONTABILIDADE", title_style))
        elements.append(Paragraph(header_body_text, normal_style))
    elements.append(Spacer(1, 0.3 * cm))

    for row in rows:
        clinica_nome = str(row.get("clinica_nome") or row.get("cliente_nome") or "Clinica sem nome")
        elements.append(
            Paragraph(
                f"CLINICA/TOMADOR: {clinica_nome} | Total servicos: {_format_currency(float(row['valor_servico'] or 0))}",
                section_style,
            )
        )
        tipo_cliente = str(row.get("tipo_cliente") or "PJ").upper()
        documento_label = "CNPJ" if tipo_cliente == "PJ" else "CPF"
        endereco_completo = _format_endereco_completo(row)

        info_rows: list[list[str]] = [
            ["Razao/Nome", str(row.get("cliente_nome") or "-")],
            [documento_label, str(row.get("cliente_documento") or "-")],
            ["Endereco completo", endereco_completo],
            ["Cidade/UF/CEP", _join_non_empty(" / ", [row.get("cliente_cidade"), row.get("cliente_estado"), row.get("cliente_cep")]) or "-"],
        ]
        if tipo_cliente == "PJ":
            info_rows.append(["Telefone", str(row.get("cliente_telefone") or "-")])
            info_rows.append(["E-mail", str(row.get("cliente_email") or "-")])

        info_rows.extend(
            [
                ["Data para emissao da NF", str(row.get("data_referencia_nf") or row.get("data_emissao") or "-")],
                ["Valor do servico", _format_currency(float(row["valor_servico"] or 0))],
                ["Aliquota ISS", _format_number(row.get("aliquota_iss")) + "%"],
                ["Valor ISS", _format_currency(float(row["valor_iss"] or 0))],
                ["Atividade", str(row.get("atividade_cnae") or "-")],
                ["Descricao do Servico", str(row.get("descricao_servico") or "-")],
                ["Natureza da Operacao", str(row.get("natureza_operacao") or "-")],
                ["Municipio do Servico", str(row.get("municipio_servico") or "-")],
                ["Regime Tributario", str(row.get("regime_tributario") or "-")],
            ]
        )

        table = Table(info_rows, colWidths=[4.2 * cm, 12.3 * cm])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F3F4F6")),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D1D5DB")),
                ]
            )
        )
        elements.append(table)

        elements.append(Spacer(1, 0.3 * cm))

    footer_text = "Documento gerado pelo sistema FortCordis"
    if str(config.get("website") or "").strip():
        footer_text = f"{footer_text} | {str(config.get('website')).strip()}"

    doc.build(
        elements,
        onFirstPage=lambda canvas, doc_obj: _draw_pdf_footer(canvas, doc_obj, footer_text),
        onLaterPages=lambda canvas, doc_obj: _draw_pdf_footer(canvas, doc_obj, footer_text),
    )
    buffer.seek(0)
    filename = f"dados_contabeis_{_now_local().strftime('%Y%m%d_%H%M%S')}.pdf"
    return buffer.read(), filename


def _consolidated_export_headers() -> list[str]:
    return [
        "Tipo Cliente",
        "Razao Social Tomador",
        "CNPJ/CPF Tomador",
        "Endereco Tomador",
        "Bairro Tomador",
        "Cidade Tomador",
        "UF Tomador",
        "CEP Tomador",
        "Telefone Tomador",
        "Email Tomador",
        "Data para emissao da NF",
        "Valor do Servico",
        "Aliquota ISS",
        "Valor ISS",
        "CNAE Atividade",
        "Descricao do Servico",
        "Natureza da Operacao",
        "Municipio do Servico",
        "Regime Tributario",
        "Prestador Nome",
        "Prestador CNPJ",
        "Prestador IM",
        "Clinica",
    ]


def _build_consolidated_export_rows(
    os_items: list[dict[str, Any]],
    config: dict[str, Any],
    dados_tomador: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    detail_rows = [_build_export_row(item, config, dados_tomador=dados_tomador) for item in os_items]
    consolidated: list[dict[str, Any]] = []
    for clinic_rows in _group_rows_by_clinic(detail_rows).values():
        first = clinic_rows[0]
        valor_servico = sum(float(row.get("valor_final") or 0) for row in clinic_rows)
        aliquota_iss = _safe_float(first.get("aliquota_iss"), 5.0)
        valor_iss = round(valor_servico * (aliquota_iss / 100), 2)
        consolidated.append(
            {
                "tipo_cliente": first.get("tipo_cliente") or "PJ",
                "cliente_nome": _first_non_empty_value(clinic_rows, "cliente_nome"),
                "cliente_documento": _first_non_empty_value(clinic_rows, "cliente_documento"),
                "cliente_endereco": _first_non_empty_value(clinic_rows, "cliente_endereco"),
                "cliente_bairro": _first_non_empty_value(clinic_rows, "cliente_bairro"),
                "cliente_cidade": _first_non_empty_value(clinic_rows, "cliente_cidade"),
                "cliente_estado": _first_non_empty_value(clinic_rows, "cliente_estado"),
                "cliente_cep": _first_non_empty_value(clinic_rows, "cliente_cep"),
                "cliente_telefone": _first_non_empty_value(clinic_rows, "cliente_telefone"),
                "cliente_email": _first_non_empty_value(clinic_rows, "cliente_email"),
                "data_referencia_nf": _first_non_empty_value(
                    clinic_rows,
                    "data_referencia_nf",
                    _first_non_empty_value(clinic_rows, "data_emissao"),
                ),
                "valor_servico": valor_servico,
                "aliquota_iss": aliquota_iss,
                "valor_iss": valor_iss,
                "atividade_cnae": _first_non_empty_value(clinic_rows, "atividade_cnae"),
                "descricao_servico": _first_non_empty_value(clinic_rows, "descricao_servico"),
                "natureza_operacao": _first_non_empty_value(clinic_rows, "natureza_operacao"),
                "municipio_servico": _first_non_empty_value(clinic_rows, "municipio_servico"),
                "regime_tributario": _first_non_empty_value(clinic_rows, "regime_tributario"),
                "prestador_nome": _first_non_empty_value(clinic_rows, "prestador_nome"),
                "prestador_cnpj": _first_non_empty_value(clinic_rows, "prestador_cnpj"),
                "prestador_im": _first_non_empty_value(clinic_rows, "prestador_im"),
                "clinica_id": first.get("clinica_id") or "",
                "clinica_nome": _first_non_empty_value(clinic_rows, "clinica_nome"),
            }
        )
    return consolidated


def _consolidated_export_values(row: dict[str, Any], *, numbers_as_text: bool) -> list[Any]:
    valor_servico = row["valor_servico"]
    aliquota_iss = row["aliquota_iss"]
    valor_iss = row["valor_iss"]
    if numbers_as_text:
        valor_servico = _format_number(valor_servico)
        aliquota_iss = _format_number(aliquota_iss)
        valor_iss = _format_number(valor_iss)
    else:
        valor_servico = float(valor_servico or 0)
        aliquota_iss = float(aliquota_iss or 0)
        valor_iss = float(valor_iss or 0)

    return [
        row["tipo_cliente"],
        row["cliente_nome"],
        row["cliente_documento"],
        row["cliente_endereco"],
        row["cliente_bairro"],
        row["cliente_cidade"],
        row["cliente_estado"],
        row["cliente_cep"],
        row["cliente_telefone"],
        row["cliente_email"],
        row["data_referencia_nf"],
        valor_servico,
        aliquota_iss,
        valor_iss,
        row["atividade_cnae"],
        row["descricao_servico"],
        row["natureza_operacao"],
        row["municipio_servico"],
        row["regime_tributario"],
        row["prestador_nome"],
        row["prestador_cnpj"],
        row["prestador_im"],
        row["clinica_nome"],
    ]


def _build_export_row(
    item: dict[str, Any],
    config: dict[str, Any],
    dados_tomador: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    tomador = _resolve_tomador(item, dados_tomador or {})
    aliquota_iss = _safe_float(tomador.get("aliquota_iss"), 5.0)
    valor_servico = _safe_float(item.get("valor_servico"), 0.0)
    valor_desconto = _safe_float(item.get("valor_desconto"), 0.0)
    valor_final = _safe_float(item.get("valor_final"), max(0.0, valor_servico - valor_desconto))
    valor_iss = round(valor_final * (aliquota_iss / 100), 2)

    data_emissao = _format_date(item.get("data_atendimento")) or _now_local().strftime("%d/%m/%Y")
    return {
        "numero_nf": "",
        "serie": "1",
        "tipo_cliente": tomador.get("tipo_cliente", "PJ"),
        "cliente_nome": tomador.get("cliente_nome", ""),
        "cliente_documento": tomador.get("cliente_documento", ""),
        "cliente_endereco": tomador.get("cliente_endereco", ""),
        "cliente_bairro": tomador.get("cliente_bairro", ""),
        "cliente_cidade": tomador.get("cliente_cidade", ""),
        "cliente_estado": tomador.get("cliente_estado", ""),
        "cliente_cep": tomador.get("cliente_cep", ""),
        "cliente_telefone": tomador.get("cliente_telefone", ""),
        "cliente_email": tomador.get("cliente_email", ""),
        "valor_servico": valor_servico,
        "valor_desconto": valor_desconto,
        "valor_final": valor_final,
        "aliquota_iss": aliquota_iss,
        "valor_iss": valor_iss,
        "atividade_cnae": tomador.get("atividade_cnae", ""),
        "descricao_servico": tomador.get("descricao_servico") or "Servicos veterinarios prestados conforme periodo selecionado.",
        "natureza_operacao": tomador.get("natureza_operacao") or "Tributacao no municipio",
        "municipio_servico": config.get("codigo_municipio", "230440"),
        "regime_tributario": config.get("regime_tributario", ""),
        "prestador_nome": config.get("nome_empresa", ""),
        "prestador_cnpj": config.get("inscricao_estadual", ""),
        "prestador_im": config.get("inscricao_municipal", ""),
        "data_emissao": data_emissao,
        "os_referencia": item.get("os_id") or item.get("numero_os") or "",
        "status_os": item.get("status_os") or "",
        "clinica_id": item.get("clinica_id") or "",
        "clinica_nome": item.get("clinica_nome") or "",
        "paciente_nome": item.get("paciente_nome") or "",
        "tutor_nome": item.get("tutor_nome") or "",
        "servico_nome": item.get("servico_nome") or "",
        "data_referencia_nf": _format_date(tomador.get("data_referencia_nf")) or "",
    }


def _resolve_tomador(item: dict[str, Any], dados_tomador: dict[str, Any]) -> dict[str, Any]:
    endereco_base = _join_non_empty(", ", [item.get("clinica_endereco"), item.get("clinica_numero")])
    return {
        "tipo_cliente": dados_tomador.get("tipo_cliente") or item.get("tipo_cliente") or "PJ",
        "cliente_nome": dados_tomador.get("cliente_nome") or item.get("cliente_nome") or item.get("clinica_nome") or "",
        "cliente_documento": dados_tomador.get("cliente_documento") or item.get("cliente_documento") or item.get("clinica_cnpj") or "",
        "cliente_endereco": dados_tomador.get("cliente_endereco") or endereco_base,
        "cliente_bairro": dados_tomador.get("cliente_bairro") or item.get("clinica_bairro") or "",
        "cliente_cidade": dados_tomador.get("cliente_cidade") or item.get("clinica_cidade") or "",
        "cliente_estado": dados_tomador.get("cliente_estado") or item.get("clinica_estado") or "",
        "cliente_cep": dados_tomador.get("cliente_cep") or item.get("clinica_cep") or "",
        "cliente_telefone": dados_tomador.get("cliente_telefone") or item.get("clinica_telefone") or "",
        "cliente_email": dados_tomador.get("cliente_email") or item.get("clinica_email") or "",
        "atividade_cnae": dados_tomador.get("atividade_cnae") or item.get("clinica_atividade_cnae") or "",
        "descricao_servico": dados_tomador.get("descricao_servico") or "",
        "natureza_operacao": dados_tomador.get("natureza_operacao") or "",
        "aliquota_iss": dados_tomador.get("aliquota_iss"),
        "data_referencia_nf": dados_tomador.get("data_referencia_nf") or "",
    }


def _join_non_empty(separator: str, values: list[Any]) -> str:
    parts = [str(v).strip() for v in values if str(v or "").strip()]
    return separator.join(parts)


def _group_rows_by_clinic(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = str(
            row.get("clinica_id")
            or row.get("clinica_nome")
            or row.get("cliente_documento")
            or row.get("cliente_nome")
            or "Clinica sem nome"
        )
        grouped.setdefault(key, []).append(row)
    return grouped


def _first_non_empty_value(rows: list[dict[str, Any]], key: str, default: str = "") -> str:
    for row in rows:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return default


def _format_os_referencias(rows: list[dict[str, Any]]) -> str:
    referencias: list[str] = []
    vistos: set[str] = set()
    for row in rows:
        referencia = str(row.get("os_referencia") or "").strip()
        if not referencia:
            continue
        if referencia in vistos:
            continue
        vistos.add(referencia)
        referencias.append(referencia)
    return ", ".join(referencias) if referencias else "-"


def _format_endereco_completo(row: dict[str, Any]) -> str:
    cidade_uf = _join_non_empty("/", [row.get("cliente_cidade"), row.get("cliente_estado")])
    return _join_non_empty(
        ", ",
        [
            row.get("cliente_endereco"),
            row.get("cliente_bairro"),
            cidade_uf,
            f"CEP {row.get('cliente_cep')}" if row.get("cliente_cep") else "",
        ],
    ) or "-"


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_date(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    text = str(value).strip()
    if not text:
        return ""
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).strftime("%d/%m/%Y")
    except ValueError:
        return text[:10]


def _format_number(value: Any) -> str:
    try:
        return f"{float(value or 0):.2f}".replace(".", ",")
    except (TypeError, ValueError):
        return "0,00"


def _format_currency(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

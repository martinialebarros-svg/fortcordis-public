"""Geração de PDF de laudos ecocardiográficos"""
import os
import re
import math
import tempfile
from io import BytesIO
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, List, Optional, Tuple
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, CondPageBreak, Image, KeepTogether
)
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
from app.utils.echo_unit_provenance import (
    ambiguous_echo_length_keys,
    normalize_confirmed_echo_lengths,
)
from app.utils.referencia_eco_defaults import (
    aplicar_defaults_publicados_caninos,
    normalizar_especie_referencia,
)
from app.utils.echo_ae_ao_reference import (
    CANINE_AE_AO_REFERENCE_TEXT,
    CANINE_AE_AO_METHOD_NOTE,
    CANINE_AE_AO_SWEDISH_METHOD,
    CANINE_AE_AO_SWEDISH_METHOD_NOTE,
    canine_ae_ao_clinical_limit_applies,
)
from app.utils.echo_low_weight_reference import (
    LOW_WEIGHT_PREFIXES, low_weight_age_context, low_weight_reference_seed,
)
from app.utils.echo_diastolic import (
    diastolic_references, diastolic_notes, diastolic_indices_awaiting_confirmation,
)
from app.utils.echo_diastolic_aliases import (
    ECHO_DIASTOLIC_CANONICAL_KEYS, normalize_echo_diastolic_aliases,
)


# Cores do tema - preto e cinza com fontes brancas (teste)
COR_PRIMARIA = colors.HexColor('#000000')   # Preto - títulos de seção
COR_SECUNDARIA = colors.HexColor('#374151') # Cinza escuro
COR_CINZA_ESCURO = colors.HexColor('#374151')   # Cinza escuro
COR_CINZA_MEDIO = colors.HexColor('#6b7280')
COR_CINZA_CLARO = colors.HexColor('#e5e7eb')    # Cinza claro para linhas alternadas
COR_HEADER_BG = colors.HexColor('#4b5563')      # Cinza médio - cabeçalhos de coluna (texto branco)
COR_BRANCO = colors.white
COR_PRETO = colors.black

# Largura do conteúdo (igual à soma das colunas das tabelas de dados)
LARGURA_TABELAS = 180 * mm


def _to_float(valor: Any) -> Optional[float]:
    """Converte valor para float de forma tolerante (aceita string com vírgula)."""
    if valor is None or valor == "":
        return None
    try:
        if isinstance(valor, str):
            return float(valor.replace(",", "."))
        return float(valor)
    except (TypeError, ValueError):
        return None


def _to_float_peso(valor: Any) -> Optional[float]:
    """Converte peso para float (aceita sufixo kg e virgula)."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        try:
            return float(valor)
        except (TypeError, ValueError):
            return None

    texto = str(valor).strip().lower().replace(",", ".")
    texto = texto.replace("kgs", "").replace("kg", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", texto)
    if not match:
        return None
    try:
        return float(match.group(0))
    except (TypeError, ValueError):
        return None


def _esc(valor: Any) -> str:
    """Escapa texto para uso seguro em reportlab Paragraph."""
    if valor is None:
        return ""
    return xml_escape(str(valor))


def medidas_com_unidade_ambigua(medidas: Dict[str, Any]) -> set[str]:
    """Identifica o conjunto que antes seria convertido sem unidade de origem."""
    return ambiguous_echo_length_keys(medidas or {})


def normalizar_medidas_para_pdf(medidas: Dict[str, Any]) -> Dict[str, Any]:
    """
    Preserva os valores gravados. Magnitude não comprova unidade em laudos legados.
    """
    return normalize_confirmed_echo_lengths(normalize_echo_diastolic_aliases(medidas or {}))


def recalcular_dived_normalizado_para_pdf(dados_pdf: Dict[str, Any]) -> None:
    """
    Recalcula os índices caninos de Modo M por Cornell (expoente 0,294)
    e de 2D por Visser (expoente 0,316) somente quando aplicáveis.
    """
    medidas = dados_pdf.get("medidas")
    if not isinstance(medidas, dict):
        return

    paciente = dados_pdf.get("paciente")
    paciente_dict = paciente if isinstance(paciente, dict) else {}
    especie = normalizar_especie_referencia(paciente_dict.get("especie"))

    peso_kg = _to_float_peso(paciente_dict.get("peso"))
    ambiguas = dados_pdf.get("unidades_ambiguas", set())
    if especie != "Canina" or "DIVEd" in ambiguas:
        medidas.pop("DIVEd_normalizado", None)
    elif peso_kg is not None and peso_kg > 0:
        dived_m = _to_float(medidas.get("DIVEd"))
        if dived_m is not None and dived_m > 0:
            medidas["DIVEd_normalizado"] = round(dived_m / 10 / peso_kg ** 0.294, 2)

    if "DIVEd_normalizado_2D" not in referencias_2d_caninas_publicadas(dados_pdf):
        medidas.pop("DIVEd_normalizado_2D", None)
    else:
        dived_2d = _to_float(medidas.get("DIVEd_2D"))
        medidas["DIVEd_normalizado_2D"] = round(dived_2d / 10 / peso_kg ** 0.316, 2)


def recalcular_marcadores_felinos_para_pdf(dados_pdf: Dict[str, Any]) -> None:
    """Deriva apenas índices com medidas de origem conhecidas, sem alterar o laudo salvo."""
    medidas = dados_pdf.get("medidas")
    if not isinstance(medidas, dict):
        return
    paciente = dados_pdf.get("paciente")
    especie = normalizar_especie_referencia(paciente.get("especie") if isinstance(paciente, dict) else None)
    ambiguas = dados_pdf.get("unidades_ambiguas", set())
    if especie == "Felina" and not {"AE_diametro_max", "AE_diametro_min"}.intersection(ambiguas):
        ae_max = _to_float(medidas.get("AE_diametro_max"))
        ae_min = _to_float(medidas.get("AE_diametro_min"))
        if ae_max is not None and ae_min is not None and 0 < ae_min <= ae_max:
            medidas["Fracao_encurtamento_AE"] = round((ae_max - ae_min) / ae_max * 100, 2)


SAIDAS_DOPPLER = (
    ("Vmax_aorta", "Grad_aorta", "aorta"),
    ("Vmax_VSVE", "Grad_VSVE", "via de saída do VE"),
    ("Vmax_VSVD", "Grad_VSVD", "via de saída do VD"),
    ("Vmax_pulmonar", "Grad_pulmonar", "pulmonar"),
)


def _medida_preenchida(valor: Any) -> bool:
    return valor is not None and (not isinstance(valor, str) or bool(valor.strip()))


def derivar_gradientes_saidas_para_pdf(dados_pdf: Dict[str, Any]) -> None:
    """Deriva gradientes ausentes ou explicitamente calculados, no mesmo local.

    A cópia de apresentação nunca substitui um valor informado/importado ou de
    origem desconhecida, inclusive inválidos que precisam de conferência. Uma
    velocidade arredondada não recupera a precisão do gradiente importado.
    """
    medidas = dados_pdf.get("medidas")
    if not isinstance(medidas, dict):
        return
    for velocidade, gradiente, _ in SAIDAS_DOPPLER:
        calculado = medidas.get(f"{gradiente}_origem") == "calculado"
        if _medida_preenchida(medidas.get(gradiente)) and not calculado:
            continue
        vmax = _to_float(medidas.get(velocidade))
        valor = 4 * vmax * vmax if vmax is not None and math.isfinite(vmax) and vmax > 0 else None
        if valor is None or not math.isfinite(valor):
            if calculado:
                medidas.pop(gradiente, None)
                medidas.pop(f"{gradiente}_origem", None)
                medidas.pop(f"{gradiente}_rotulo_origem", None)
            continue
        medidas[gradiente] = round(valor, 2)
        medidas[f"{gradiente}_origem"] = "calculado"
        medidas.pop(f"{gradiente}_rotulo_origem", None)


def parametros_saidas_para_pdf(medidas: Dict[str, Any]) -> List[Dict]:
    """Mantém as quatro aquisições separadas e explicita apenas derivações conhecidas."""
    parametros = []
    for velocidade, gradiente, local in SAIDAS_DOPPLER:
        for chave, label, unidade in (
            (velocidade, f"Vmax {local}", "m/s"),
            (gradiente, f"Gradiente {local}", "mmHg"),
        ):
            if chave == gradiente and medidas.get(f"{chave}_origem") == "calculado":
                label += " (calculado: 4 × V²)"
            valor = medidas.get(chave)
            numero = _to_float(valor)
            parametros.append({
                "chave": chave, "label": label, "unidade": unidade,
                "ref_min": None, "ref_max": None, "preservar_precisao": True,
                "value_recorded": _medida_preenchida(valor),
                "value_unconfirmed": _medida_preenchida(valor) and (
                    numero is None or not math.isfinite(numero) or numero < 0
                ),
            })
    return parametros


def notas_saidas_para_pdf(medidas: Dict[str, Any]) -> List[str]:
    """Sinaliza procedência ausente sem reatribuir campos históricos a outro local."""
    sem_origem = []
    notas = []
    for velocidade, gradiente, local in SAIDAS_DOPPLER:
        for chave, label in ((velocidade, f"Vmax {local}"), (gradiente, f"Gradiente {local}")):
            if not _medida_preenchida(medidas.get(chave)):
                continue
            origem = medidas.get(f"{chave}_origem")
            rotulo = str(medidas.get(f"{chave}_rotulo_origem") or "").strip()
            if rotulo:
                notas.append(f"Rótulo de origem de {label}: {rotulo}.")
            if origem not in {"importado", "informado", "calculado"}:
                sem_origem.append(label)
    if sem_origem:
        notas.insert(0, "Origem não confirmada: " + "; ".join(sem_origem) +
                     ". Campos e valores legados mantidos; confira o exame de origem.")
    return notas


def _formatar_medida_com_precisao(valor: Any, numero: float) -> str:
    """Mantém a precisão registrada nas saídas, com no mínimo duas casas."""
    try:
        decimal = Decimal(str(valor).strip().replace(",", "."))
        return format(decimal, f".{max(2, -decimal.as_tuple().exponent)}f")
    except (InvalidOperation, TypeError, ValueError):
        return f"{numero:.2f}"


def _bloco_sem_quebra(*flowables):
    """
    Retorna um bloco que tenta manter os elementos juntos na mesma pagina.
    Se nao houver espaco suficiente, o bloco inicia na pagina seguinte.
    """
    itens = [f for f in flowables if f is not None]
    return KeepTogether(itens)


def formatar_referencia(ref_min: Optional[float], ref_max: Optional[float], unidade: str) -> str:
    """Formata faixa de referência incluindo unidade quando aplicável."""
    if ref_min is None or ref_max is None:
        return "--"
    if ref_min == 0 and ref_max == 0:
        return "--"
    sufixo = f" {unidade}" if unidade else ""
    return f"{ref_min:.2f} - {ref_max:.2f}{sufixo}"


def interpretar_parametro(valor: float, ref_min: float, ref_max: float) -> Tuple[str, colors.Color]:
    """
    Retorna interpretação textual e cor com base na faixa de referência.
    """
    if ref_min is None or ref_max is None:
        return "", COR_PRETO

    if valor < ref_min:
        return "Abaixo", colors.HexColor("#2563eb")
    if valor > ref_max:
        return "Acima", colors.HexColor("#dc2626")
    return "Normal", colors.HexColor("#15803d")


# Mapeamento: chave da medida no laudo -> prefixo de campo na tabela referencias_eco
MAPEAMENTO_REFERENCIA_ECO = {
    "DIVEd": "lvid_d",
    "DIVES": "lvid_s",
    "SIVd": "ivs_d",
    "SIVs": "ivs_s",
    "PLVEd": "lvpw_d",
    "PLVES": "lvpw_s",
    "VDF": "edv",
    "VSF": "esv",
    "DeltaD_FS": "fs",
    "TAPSE": "tapse",
    "MAPSE": "mapse",
    "Aorta": "ao",
    "Atrio_esquerdo": "la",
    "AE_Ao": "la_ao",
    "Ao_nivel_AP": "ao",
    "AP": "ap",
    "AP_Ao": "ap_ao",
    "Onda_E": "mv_e",
    "Onda_A": "mv_a",
    "E_A": "mv_ea",
    "TD": "mv_dt",
    "TRIV": "ivrt",
    "e_doppler": "tdi_e",
    "a_doppler": "tdi_a",
    "E_E_linha": "e_e_linha",
    "Vmax_aorta": "vmax_ao",
    "Vmax_pulmonar": "vmax_pulm",
}


def aplicar_referencia_eco(parametros: List[Dict], referencia_eco: Optional[Dict[str, Any]]) -> List[Dict]:
    """
    Exibe apenas faixas disponíveis na referência selecionada para o paciente.

    Limites fixos legados não podem ser aplicados indiscriminadamente a espécies,
    pesos e métodos distintos.
    """
    params_atualizados: List[Dict] = []
    for param in parametros:
        atualizado = dict(param)
        atualizado["ref_min"] = None
        atualizado["ref_max"] = None
        atualizado.pop("ref_text", None)

        prefixo = MAPEAMENTO_REFERENCIA_ECO.get(str(param.get("chave", "")))
        if prefixo and referencia_eco and (prefixo != "fs" or referencia_eco.get("fs_source")):
            metadata = referencia_eco.get("range_metadata", {}).get(prefixo, {})
            if prefixo in LOW_WEIGHT_PREFIXES and metadata.get("status") == "estimated":
                lower, upper = metadata.get("estimate_min"), metadata.get("estimate_max")
                if lower is not None and upper is not None:
                    label = "Adultos" if metadata.get("estimate_context") == "age_unconfirmed" else "Est."
                    atualizado["ref_text"] = f"{label}: {lower:.2f}-{upper:.2f} mm*"
            ref_min = referencia_eco.get(f"{prefixo}_min")
            ref_max = referencia_eco.get(f"{prefixo}_max")
            if ref_min is not None and ref_max is not None:
                if str(param.get("chave")) in {"e_doppler", "a_doppler"}:
                    ref_min = float(ref_min) / 100
                    ref_max = float(ref_max) / 100
                atualizado["ref_min"] = ref_min
                atualizado["ref_max"] = ref_max

        params_atualizados.append(atualizado)

    return params_atualizados


def referencias_2d_caninas_publicadas(dados_pdf: Dict[str, Any]) -> Dict[str, Tuple[float, float]]:
    """Visser 2019, tabelas 1-2: apenas medidas 2D com vista confirmada."""
    paciente = dados_pdf.get("paciente") or {}
    medidas = dados_pdf.get("medidas") or {}
    if not dados_pdf.get("referencia_eco") or normalizar_especie_referencia(paciente.get("especie") or "") != "Canina":
        return {}
    # A confirmed adult acquisition protocol cannot override a patient known
    # to be growing. Unknown age retains the existing explicit-view contract.
    if low_weight_age_context(paciente.get("idade")) == "juvenile":
        return {}
    if medidas.get("VE_tecnica_relatorio") != "2d":
        return {}
    vista = medidas.get("VE_vista_2D")
    if vista not in {"eixo_curto", "eixo_longo"}:
        return {}
    peso = _to_float_peso(paciente.get("peso"))
    if peso is None or not math.isfinite(peso) or not 2.6 <= peso <= 67.8:
        return {}

    limites = {
        "eixo_curto": {"DIVEd_2D": (1.14, 1.61, 0.316), "DIVES_2D": (0.56, 0.93, 0.392), "DeltaD_FS_2D": (21.9, 49.3, None)},
        "eixo_longo": {"DIVEd_2D": (1.15, 1.55, 0.316), "DIVES_2D": (0.68, 1.09, 0.351), "DeltaD_FS_2D": (19.1, 41.7, None)},
    }[vista]
    ambiguas = dados_pdf.get("unidades_ambiguas") or set()
    faixas = {}
    for chave in ("DIVEd_2D", "DIVES_2D"):
        valor = _to_float(medidas.get(chave))
        if chave in ambiguas or valor is None or not math.isfinite(valor) or valor <= 0:
            continue
        minimo, maximo, expoente = limites[chave]
        faixas[chave] = (round(minimo * 10 * peso ** expoente, 2), round(maximo * 10 * peso ** expoente, 2))

    if "DIVEd_2D" in faixas:
        minimo, maximo, _ = limites["DIVEd_2D"]
        faixas["DIVEd_normalizado_2D"] = (minimo, maximo)

    d = _to_float(medidas.get("DIVEd_2D"))
    s = _to_float(medidas.get("DIVES_2D"))
    fs = _to_float(medidas.get("DeltaD_FS_2D"))
    if ("DIVEd_2D" in faixas and "DIVES_2D" in faixas and d and s and fs is not None
            and math.isfinite(fs) and 0 < s <= d and abs(fs - (d - s) / d * 100) <= 1):
        minimo, maximo, _ = limites["DeltaD_FS_2D"]
        faixas["DeltaD_FS_2D"] = (minimo, maximo)
    return faixas


def aplicar_referencias_2d_publicadas(parametros: List[Dict], dados_pdf: Dict[str, Any]) -> List[Dict]:
    faixas = referencias_2d_caninas_publicadas(dados_pdf)
    return [{**param, **({"ref_min": faixas[param["chave"]][0], "ref_max": faixas[param["chave"]][1]}
                       if param["chave"] in faixas else {})} for param in parametros]


def filtrar_parametros_preenchidos(parametros: List[Dict], medidas: Dict[str, Any]) -> List[Dict]:
    """Keep recorded outflow values and limitations; omit generic zero defaults."""
    filled = []
    for param in parametros:
        if param.get("value_unmeasurable") is True:
            filled.append(param)
            continue
        value = _to_float(medidas.get(param["chave"]))
        if param["chave"] in ECHO_DIASTOLIC_CANONICAL_KEYS:
            if value is not None and math.isfinite(value) and value > 0:
                filled.append(param)
        elif param.get("value_recorded") is True or (value or 0) != 0:
            filled.append(param)
    return filled


def create_pdf_styles():
    """Cria estilos para o PDF"""
    styles = getSampleStyleSheet()
    
    styles.add(ParagraphStyle(
        'TituloPrincipal',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=COR_PRETO,
        spaceAfter=6,
        alignment=1,  # Center
        fontName='Helvetica-Bold'
    ))
    styles.add(ParagraphStyle(
        'TituloPrincipalLeft',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=COR_PRETO,
        spaceAfter=6,
        alignment=0,  # Left (alinhado às tabelas no cabeçalho)
        fontName='Helvetica-Bold'
    ))
    
    styles.add(ParagraphStyle(
        'Subtitulo',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=COR_PRETO,
        spaceAfter=12,
        fontName='Helvetica-Bold'
    ))
    
    styles.add(ParagraphStyle(
        'InfoLabel',
        parent=styles['Normal'],
        fontSize=9,
        textColor=COR_CINZA_MEDIO,
        fontName='Helvetica'
    ))
    
    styles.add(ParagraphStyle(
        'InfoValue',
        parent=styles['Normal'],
        fontSize=9,
        textColor=COR_PRETO,
        fontName='Helvetica-Bold'
    ))
    
    styles.add(ParagraphStyle(
        'SecaoTitulo',
        parent=styles['Heading3'],
        fontSize=13,
        textColor=COR_BRANCO,
        backColor=COR_PRIMARIA,
        spaceAfter=6,
        spaceBefore=12,
        leftIndent=0,
        rightIndent=0,
        fontName='Helvetica-Bold'
    ))
    
    # Estilo para títulos de tabela (texto branco em fundo preto)
    styles.add(ParagraphStyle(
        'TabelaTitulo',
        parent=styles['Normal'],
        fontSize=10,
        textColor=COR_BRANCO,
        fontName='Helvetica-Bold'
    ))
    
    # Estilo para cabeçalhos de coluna (texto branco em fundo cinza)
    styles.add(ParagraphStyle(
        'TabelaHeader',
        parent=styles['Normal'],
        fontSize=9,
        textColor=COR_BRANCO,
        fontName='Helvetica-Bold'
    ))
    
    styles.add(ParagraphStyle(
        'QualitativaLabel',
        parent=styles['Normal'],
        fontSize=10,
        textColor=COR_CINZA_ESCURO,
        fontName='Helvetica-Bold'
    ))
    
    styles.add(ParagraphStyle(
        'QualitativaTexto',
        parent=styles['Normal'],
        fontSize=10,
        textColor=COR_PRETO,
        fontName='Helvetica'
    ))
    
    styles.add(ParagraphStyle(
        'Conclusao',
        parent=styles['Normal'],
        fontSize=11,
        textColor=COR_PRETO,
        fontName='Helvetica',
        spaceAfter=6,
        leading=14
    ))
    
    styles.add(ParagraphStyle(
        'Rodape',
        parent=styles['Normal'],
        fontSize=8,
        textColor=COR_CINZA_MEDIO,
        alignment=1,
        fontName='Helvetica-Oblique'
    ))
    styles.add(ParagraphStyle(
        'ReferenciaTitulo',
        parent=styles['Normal'],
        fontSize=8.5,
        leading=10,
        spaceAfter=2,
        textColor=COR_CINZA_ESCURO,
        fontName='Helvetica-Bold',
    ))
    styles.add(ParagraphStyle(
        'ReferenciaTexto',
        parent=styles['Normal'],
        fontSize=8,
        leading=10,
        spaceAfter=1,
        textColor=COR_CINZA_ESCURO,
        fontName='Helvetica',
    ))
    
    return styles


def criar_titulo_secao(texto: str) -> Table:
    """Cria o título de seção (ANÁLISE QUANTITATIVA, etc.) como tabela de uma célula
    com a mesma largura das tabelas de dados, para alinhar a linha e o bloco."""
    styles = create_pdf_styles()
    data = [[Paragraph(texto, styles['SecaoTitulo'])]]
    table = Table(data, colWidths=[LARGURA_TABELAS])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), COR_PRIMARIA),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return table


# Dimensões da logo (tamanho original no cabeçalho)
MAX_LOGO_WIDTH = 55 * mm
MAX_LOGO_HEIGHT = 40 * mm
# Coluna da logo menor para o título "LAUDO ECOCARDIOGRÁFICO" ficar alinhado à esquerda com as tabelas
LARGURA_COLUNA_LOGO =50 * mm


def criar_cabecalho(
    dados: Dict[str, Any],
    temp_logo_path: str = None,
    titulo_principal: str = "LAUDO ECOCARDIOGRAFICO",
    mostrar_linha_ritmo: bool = True,
    label_data_exame: str = "Data do exame",
) -> List:
    """Cria o cabecalho do laudo com bloco de titulo e grade de informacoes."""
    elements = []
    styles = create_pdf_styles()
    paciente = dados.get("paciente", {})
    clinica = dados.get("clinica", "")
    data_exame = paciente.get("data_exame", datetime.now().strftime("%d/%m/%Y"))

    titulo_bloco_style = ParagraphStyle(
        "CabecalhoTituloBloco",
        parent=styles["TituloPrincipalLeft"],
        fontSize=17,
        leading=19,
        spaceAfter=0,
    )
    info_card_style = ParagraphStyle(
        "CabecalhoInfoCard",
        parent=styles["Normal"],
        fontSize=10,
        leading=12,
        textColor=COR_PRETO,
    )

    def _valor_padrao(valor: Any) -> str:
        texto = str(valor).strip() if valor not in (None, "") else ""
        return texto or "-"

    def _montar_linha(*partes: str) -> str:
        partes_validas = [parte for parte in partes if parte and parte != "-"]
        return " | ".join(partes_validas) if partes_validas else "-"

    def _criar_card_info(label: str, valor: str) -> Paragraph:
        return Paragraph(
            f"<font name='Helvetica-Bold' size='7' color='#6b7280'>{_esc(label.upper())}</font><br/>"
            f"{_esc(valor)}",
            info_card_style,
        )

    def _adicionar_card(cards: List[Tuple[str, str]], label: str, valor: str, obrigatorio: bool = False) -> None:
        if obrigatorio or valor != "-":
            cards.append((label, valor))

    if temp_logo_path and os.path.exists(temp_logo_path):
        try:
            img_reader = ImageReader(temp_logo_path)
            img_width, img_height = img_reader.getSize()
            aspect = img_height / float(img_width) if img_width else 1
            if aspect > (MAX_LOGO_HEIGHT / MAX_LOGO_WIDTH):
                draw_height = MAX_LOGO_HEIGHT
                draw_width = MAX_LOGO_HEIGHT / aspect
            else:
                draw_width = MAX_LOGO_WIDTH
                draw_height = MAX_LOGO_WIDTH * aspect
            logo = Image(temp_logo_path, width=draw_width, height=draw_height)
            logo.hAlign = "LEFT"
            subtitulo_linhas = [
                "<font size='8' color='#6b7280'>CARDIOLOGIA VETERINARIA</font>",
                f"<font size='17'><b>{_esc(titulo_principal)}</b></font>",
            ]
            linha_secundaria = _montar_linha(_valor_padrao(clinica), _valor_padrao(data_exame))
            if linha_secundaria != "-":
                subtitulo_linhas.append(
                    f"<font size='9' color='#374151'>{_esc(linha_secundaria)}</font>"
                )
            titulo = Paragraph("<br/>".join(subtitulo_linhas), titulo_bloco_style)
            largura_titulo = LARGURA_TABELAS - LARGURA_COLUNA_LOGO
            header_data = [[logo, titulo]]
            header_table = Table(header_data, colWidths=[LARGURA_COLUNA_LOGO, largura_titulo])
            header_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 0), (1, 0), "LEFT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, -1), 0.8, COR_CINZA_CLARO),
            ]))
            elements.append(header_table)
        except Exception as e:
            print(f"Erro ao adicionar logomarca: {e}")
            elements.append(Paragraph(_esc(titulo_principal), styles["TituloPrincipal"]))
    else:
        titulo_sem_logo = [
            "<font size='8' color='#6b7280'>CARDIOLOGIA VETERINARIA</font>",
            f"<font size='17'><b>{_esc(titulo_principal)}</b></font>",
        ]
        linha_secundaria = _montar_linha(_valor_padrao(clinica), _valor_padrao(data_exame))
        if linha_secundaria != "-":
            titulo_sem_logo.append(
                f"<font size='9' color='#374151'>{_esc(linha_secundaria)}</font>"
            )
        elements.append(Paragraph("<br/>".join(titulo_sem_logo), titulo_bloco_style))

    elements.append(Spacer(1, 2.5 * mm))

    peso = paciente.get("peso", "")
    peso_str = f"{peso} kg" if peso not in (None, "", "N/A") else "-"
    ritmo = (paciente.get("ritmo", "") or "").strip()
    fc = (paciente.get("fc", "") or "").strip()
    estado = (paciente.get("estado", "") or "").strip()
    fc_str = f"{fc} bpm" if fc else ""

    cards: List[Tuple[str, str]] = []
    _adicionar_card(cards, "Paciente", _valor_padrao(paciente.get("nome")), obrigatorio=True)
    _adicionar_card(cards, "Tutor", _valor_padrao(paciente.get("tutor")), obrigatorio=True)
    _adicionar_card(
        cards,
        "Especie | Raca",
        _montar_linha(_valor_padrao(paciente.get("especie")), _valor_padrao(paciente.get("raca"))),
        obrigatorio=True,
    )
    _adicionar_card(
        cards,
        "Sexo | Idade | Peso",
        _montar_linha(_valor_padrao(paciente.get("sexo")), _valor_padrao(paciente.get("idade")), peso_str),
        obrigatorio=True,
    )
    _adicionar_card(cards, "Solicitante", _valor_padrao(paciente.get("solicitante")))
    _adicionar_card(cards, "Clinica", _valor_padrao(clinica))
    _adicionar_card(cards, label_data_exame, _valor_padrao(data_exame), obrigatorio=True)

    if mostrar_linha_ritmo and any([ritmo, fc_str, estado]):
        cards.append(("Ritmo | FC | Estado", _montar_linha(ritmo, fc_str, estado)))

    if len(cards) % 2 != 0:
        cards.append(("", ""))

    info_data = []
    for idx in range(0, len(cards), 2):
        linha = []
        for label, valor in cards[idx:idx + 2]:
            if label:
                linha.append(_criar_card_info(label, valor))
            else:
                linha.append(Paragraph("", info_card_style))
        info_data.append(linha)

    info_table = Table(info_data, colWidths=[90 * mm, 90 * mm])
    info_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, COR_CINZA_CLARO),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, COR_CINZA_CLARO),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fafafa")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(_bloco_sem_quebra(info_table))
    elements.append(Spacer(1, 3 * mm))

    return elements


def criar_tabela_medidas(titulo: str, parametros: List[Dict], dados: Dict[str, Any], 
                         mostrar_referencia: bool = True, mostrar_interpretacao: bool = False) -> Table:
    """Cria uma tabela de medidas ecocardiográficas
    
    Args:
        titulo: Título da seção
        parametros: Lista de parâmetros com chave, label, unidade, ref_min, ref_max
        dados: Dicionário com os valores das medidas
        mostrar_referencia: Se True, mostra coluna de referência
        mostrar_interpretacao: Se True, mostra coluna de interpretação
    """
    styles = create_pdf_styles()
    
    # Determinar colunas a exibir
    colunas = ["Parâmetro", "Valor"]
    if mostrar_referencia:
        colunas.append("Referência")
    if mostrar_interpretacao:
        colunas.append("Interpretação")
    
    # Calcular larguras das colunas - ajustado para layout do modelo
    num_colunas = len(colunas)
    if num_colunas == 2:
        col_widths = [130*mm, 50*mm]
    elif num_colunas == 3:
        col_widths = [100*mm, 40*mm, 40*mm]
    else:  # 4 colunas
        col_widths = [80*mm, 35*mm, 35*mm, 30*mm]
    
    # Cabeçalho da tabela (título da seção) - texto branco em fundo azul
    header_cells = [Paragraph(f"<b>{titulo}</b>", styles['TabelaTitulo'])] + [''] * (num_colunas - 1)
    data = [header_cells]
    
    # Sub-cabeçalho com nomes das colunas - texto escuro em fundo claro
    subheader_cells = [Paragraph(f"<b>{col}</b>", styles['TabelaHeader']) for col in colunas]
    data.append(subheader_cells)
    
    # Dados
    for param in parametros:
        chave = param['chave']
        label = param['label']
        unidade = param.get('unidade', '')
        ref_min = param.get('ref_min')
        ref_max = param.get('ref_max')
        ref_text = param.get('ref_text')  # Referência em texto fixo (ex: ">0,25 m/s")
        
        valor = dados.get('medidas', {}).get(chave, 0)
        valor_float = _to_float(valor) or 0
        unidade_ambigua = chave in dados.get('unidades_ambiguas', set())
        
        # Formata valor
        if param.get("value_unmeasurable") is True:
            # A fusion flag invalidates individual peaks/ratios for display.
            # Keep the original numeric history in dados/DB untouched.
            valor_str = "Não mensurável"
            ref_str = (ref_text or "--") if mostrar_referencia else ""
            interp_str = ""
            interp_color = COR_PRETO
        elif param.get("value_unconfirmed") is True:
            valor_str = f"{_esc(valor)} (valor a confirmar)"
            ref_str = "--"
            interp_str = ""
            interp_color = COR_PRETO
        elif valor_float == 0 and not param.get("value_recorded"):
            valor_str = "--"
            ref_str = (ref_text if ref_text else formatar_referencia(ref_min, ref_max, unidade)) if mostrar_referencia else ""
            interp_str = ""
            interp_color = COR_PRETO
        else:
            numero_formatado = (
                _formatar_medida_com_precisao(valor, valor_float)
                if param.get("preservar_precisao") else f"{valor_float:.2f}"
            )
            valor_str = f"{numero_formatado} (unidade a confirmar)" if unidade_ambigua else f"{numero_formatado} {unidade}".strip()
            ref_str = "--" if unidade_ambigua else ((ref_text if ref_text else formatar_referencia(ref_min, ref_max, unidade)) if mostrar_referencia else "")
            
            if not unidade_ambigua and ref_min is not None and ref_max is not None and not (ref_min == 0 and ref_max == 0):
                interp_str, interp_color = interpretar_parametro(valor_float, ref_min, ref_max)
            else:
                interp_str = ""
                interp_color = COR_PRETO
        
        # Construir linha conforme colunas visíveis
        row = [
            Paragraph(label, styles['Normal']),
            Paragraph(valor_str, styles['Normal'])
        ]
        if mostrar_referencia:
            row.append(Paragraph(ref_str, styles['Normal']))
        if mostrar_interpretacao:
            row.append(Paragraph(f"<font color='{interp_color.hexval()}'>{interp_str}</font>", styles['Normal']))
        
        data.append(row)
    
    # Criar tabela
    table = Table(data, colWidths=col_widths, repeatRows=2)
    
    # Estilos base - cores do modelo original
    table_style = [
        # Título da seção (fundo azul escuro)
        ('BACKGROUND', (0, 0), (-1, 0), COR_PRIMARIA),
        ('TEXTCOLOR', (0, 0), (-1, 0), COR_BRANCO),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('SPAN', (0, 0), (-1, 0)),
        ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
        ('LEFTPADDING', (0, 0), (-1, 0), 6),
        
        # Cabeçalho das colunas (fundo cinza, texto branco)
        ('BACKGROUND', (0, 1), (-1, 1), COR_HEADER_BG),
        ('TEXTCOLOR', (0, 1), (-1, 1), COR_BRANCO),
        ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 1), (-1, 1), 9),
        ('ALIGN', (1, 1), (-1, 1), 'CENTER'),
        
        # Linhas de dados
        ('FONTSIZE', (0, 2), (-1, -1), 9),
        ('ALIGN', (1, 2), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        
        # Grade
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BOX', (0, 0), (-1, -1), 1, COR_PRIMARIA),
        
        # Alternância de cores nas linhas de dados
        ('ROWBACKGROUNDS', (0, 2), (-1, -1), [COR_BRANCO, COR_CINZA_CLARO]),
    ]
    
    table.setStyle(TableStyle(table_style))
    
    return table


def criar_tabela_medidas_com_interpretacao(titulo: str, parametros: List[Dict], dados: Dict[str, Any]) -> Table:
    """Cria uma tabela de medidas com colunas Valor, Referência e Interpretação
    
    Usado para seções como Átrio Esquerdo/Aorta, Doppler-Saídas, etc.
    """
    styles = create_pdf_styles()
    
    colunas = ["Parâmetro", "Valor", "Referência", "Interpretação"]
    col_widths = [80*mm, 30*mm, 35*mm, 35*mm]
    
    # Cabeçalho da tabela - texto branco em fundo azul
    header_cells = [Paragraph(f"<b>{titulo}</b>", styles['TabelaTitulo'])] + [''] * 3
    data = [header_cells]
    
    # Sub-cabeçalho - texto escuro em fundo claro
    subheader_cells = [Paragraph(f"<b>{col}</b>", styles['TabelaHeader']) for col in colunas]
    data.append(subheader_cells)
    
    # Dados
    for param in parametros:
        chave = param['chave']
        label = param['label']
        unidade = param.get('unidade', '')
        ref_min = param.get('ref_min')
        ref_max = param.get('ref_max')
        
        valor = dados.get('medidas', {}).get(chave, 0)
        valor_float = _to_float(valor) or 0
        
        if valor_float == 0:
            valor_str = "--"
            ref_str = "--"
            interp_str = ""
            interp_color = COR_PRETO
        else:
            valor_str = f"{valor_float:.2f} {unidade}".strip()
            ref_str = formatar_referencia(ref_min, ref_max, "")
            
            if ref_min is not None and ref_max is not None and not (ref_min == 0 and ref_max == 0):
                interp_str, interp_color = interpretar_parametro(valor_float, ref_min, ref_max)
            else:
                interp_str = "--"
                interp_color = COR_PRETO
        
        row = [
            Paragraph(label, styles['Normal']),
            Paragraph(valor_str, styles['Normal']),
            Paragraph(ref_str, styles['Normal']),
            Paragraph(f"<font color='{interp_color.hexval()}'>{interp_str}</font>", styles['Normal'])
        ]
        data.append(row)
    
    table = Table(data, colWidths=col_widths)
    
    table_style = [
        ('BACKGROUND', (0, 0), (-1, 0), COR_PRIMARIA),
        ('TEXTCOLOR', (0, 0), (-1, 0), COR_BRANCO),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('SPAN', (0, 0), (-1, 0)),
        ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
        ('LEFTPADDING', (0, 0), (-1, 0), 6),
        
        ('BACKGROUND', (0, 1), (-1, 1), COR_HEADER_BG),
        ('TEXTCOLOR', (0, 1), (-1, 1), COR_BRANCO),
        ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 1), (-1, 1), 9),
        ('ALIGN', (1, 1), (-1, 1), 'CENTER'),
        
        ('FONTSIZE', (0, 2), (-1, -1), 9),
        ('ALIGN', (1, 2), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BOX', (0, 0), (-1, -1), 1, COR_PRIMARIA),
        ('ROWBACKGROUNDS', (0, 2), (-1, -1), [COR_BRANCO, COR_CINZA_CLARO]),
    ]
    
    table.setStyle(TableStyle(table_style))
    return table


def criar_secao_ad_vd(texto: str) -> List:
    """Cria a seção AD/VD como texto (não tabela) - conforme modelo de referência"""
    elements = []
    styles = create_pdf_styles()
    
    if not texto or not texto.strip():
        return elements
    
    # Título da seção - texto branco em fundo azul
    titulo_data = [[Paragraph("<b>AD/VD (Subjetivo)</b>", styles['TabelaTitulo'])]]
    titulo_table = Table(titulo_data, colWidths=[180*mm])
    titulo_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COR_PRIMARIA),
        ('LEFTPADDING', (0, 0), (-1, 0), 6),
        ('TOPPADDING', (0, 0), (-1, 0), 4),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
    ]))
    # Texto do AD/VD
    texto_data = [[Paragraph(_esc(texto.strip()), styles['Normal'])]]
    texto_table = Table(texto_data, colWidths=[180*mm])
    texto_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COR_BRANCO),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.grey),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))

    elements.append(_bloco_sem_quebra(titulo_table, texto_table))
    
    return elements


def criar_secao_qualitativa(qualitativa: Dict[str, str], assinatura: Optional[List] = None) -> List:
    """Cria a seção de análise qualitativa com hierarquia visual por grupo."""
    elements = []
    styles = create_pdf_styles()
    grupo_style = ParagraphStyle(
        "QualitativaGrupo",
        parent=styles["QualitativaLabel"],
        fontSize=10.5,
        textColor=COR_PRETO,
        spaceAfter=1,
    )
    item_label_style = ParagraphStyle(
        "QualitativaItemLabel",
        parent=styles["QualitativaTexto"],
        leftIndent=4 * mm,
        spaceAfter=0.5 * mm,
    )
    item_body_style = ParagraphStyle(
        "QualitativaItemBody",
        parent=styles["QualitativaTexto"],
        leftIndent=9 * mm,
        spaceAfter=0.25 * mm,
        leading=12,
    )
    bloco_texto_style = ParagraphStyle(
        "QualitativaBlocoTexto",
        parent=styles["QualitativaTexto"],
        leftIndent=4 * mm,
        spaceAfter=0.25 * mm,
        leading=12,
    )

    def _quebrar_itens(texto_bruto: str) -> List[str]:
        itens: List[str] = []
        atual = ""
        for linha in texto_bruto.splitlines():
            linha_limpa = linha.strip()
            if not linha_limpa:
                continue
            if linha_limpa.startswith(("-", "*", "•")):
                if atual:
                    itens.append(atual.strip())
                atual = linha_limpa[1:].strip()
            elif atual:
                atual = f"{atual} {linha_limpa}"
            else:
                atual = linha_limpa
        if atual:
            itens.append(atual.strip())
        return itens

    campos = [
        ("valvas", "Valvas"),
        ("camaras", "Câmaras esquerdas"),
        ("ad_vd", "Câmaras direitas"),
        ("funcao", "Função"),
        ("pericardio", "Pericárdio"),
        ("vasos", "Vasos sanguíneos"),
    ]
    grupos_renderizados = []

    for chave, label in campos:
        texto = qualitativa.get(chave, "").strip()
        if not texto:
            continue

        bloco = [Paragraph(_esc(label), grupo_style)]
        itens = _quebrar_itens(texto)

        if itens:
            for item in itens:
                titulo_item, separador, corpo_item = item.partition(":")
                titulo_item = titulo_item.strip()
                corpo_item = corpo_item.strip()

                if separador:
                    bloco.append(
                        Paragraph(f"&bull; <b>{_esc(titulo_item)}</b>", item_label_style)
                    )
                    bloco.append(Paragraph(_esc(corpo_item), item_body_style))
                else:
                    bloco.append(Paragraph(f"&bull; {_esc(item)}", bloco_texto_style))
        else:
            bloco.append(Paragraph(_esc(texto), bloco_texto_style))

        grupos_renderizados.append(bloco)

    if not grupos_renderizados:
        return elements

    assinatura = assinatura or []
    elements.append(
        _bloco_sem_quebra(
            Spacer(1, 4 * mm),
            criar_titulo_secao("ANÁLISE QUALITATIVA"),
            Spacer(1, 2 * mm),
            *grupos_renderizados[0],
            *(assinatura if len(grupos_renderizados) == 1 else []),
        )
    )
    elements.append(Spacer(1, 0.5 * mm))

    for indice, grupo in enumerate(grupos_renderizados[1:], 1):
        ultimo_grupo = indice == len(grupos_renderizados) - 1
        elements.append(_bloco_sem_quebra(*grupo, *(assinatura if ultimo_grupo else [])))
        elements.append(Spacer(1, 0.5 * mm))

    return elements


def criar_secao_referencias_eco(dados_pdf: Dict[str, Any]) -> List:
    """Relaciona estudos primários pertinentes, sem atribuir faixas legadas a eles."""
    paciente = dados_pdf.get("paciente") or {}
    medidas = dados_pdf.get("medidas") or {}
    referencia = dados_pdf.get("referencia_eco") or {}
    # A bibliografia de fluxos documenta dados publicados mesmo quando não há
    # linha de referência selecionada; não transforma estatísticas descritivas
    # em limites individuais nem atribui a elas as faixas do cadastro.
    tem_fluxo_saida = any(
        valor is not None and math.isfinite(valor) and valor > 0
        for valor in (_to_float(medidas.get("Vmax_aorta")), _to_float(medidas.get("Vmax_pulmonar")))
    )
    tem_limiar_ae_ao_canino = canine_ae_ao_clinical_limit_applies(dados_pdf)
    consultas_diastolicas = diastolic_references(medidas, paciente.get("especie"))
    bibliografia_diastolica = [ref["bibliography"] for ref in consultas_diastolicas.values() if ref["bibliography"]]
    if not referencia and not tem_fluxo_saida and not tem_limiar_ae_ao_canino and not bibliografia_diastolica:
        return []
    especie = normalizar_especie_referencia(paciente.get("especie") or "")
    modo_m = str(medidas.get("VE_tecnica_relatorio") or "").lower() != "2d"
    tem_modo_m = modo_m and any(_to_float(medidas.get(chave)) for chave in (
        "DIVEd", "DIVES", "SIVd", "SIVs", "PLVEd", "PLVES",
    ))
    tapse = _to_float(medidas.get("TAPSE")) is not None
    mapse = _to_float(medidas.get("MAPSE")) is not None
    medidas_m = [(chave, prefixo) for chave, prefixo in MAPEAMENTO_REFERENCIA_ECO.items()
                 if prefixo in LOW_WEIGHT_PREFIXES]
    metadados_m = referencia.get("range_metadata", {})

    def _medida_m_exibida(chave: str) -> bool:
        valor = _to_float(medidas.get(chave))
        return (modo_m and chave not in (dados_pdf.get("unidades_ambiguas") or set())
                and valor is not None and math.isfinite(valor) and valor > 0)

    def _modelo_m_exibido(chave: str, prefixo: str, doi: str) -> bool:
        metadata = metadados_m.get(prefixo, {})
        status = metadata.get("status")
        if (metadata.get("doi") != doi or status not in {"published", "estimated"}
                or not _medida_m_exibida(chave)):
            return False
        limites = (metadata.get("estimate_min"), metadata.get("estimate_max")) if status == "estimated" else (
            referencia.get(f"{prefixo}_min"), referencia.get(f"{prefixo}_max"))
        inferior, superior = (_to_float(limite) for limite in limites)
        return (inferior is not None and superior is not None
                and math.isfinite(inferior) and math.isfinite(superior) and 0 < inferior < superior)

    estudos: List[str] = []
    if referencia and especie == "Canina":
        if referencias_2d_caninas_publicadas(dados_pdf):
            estudos.append(
                "Visser et al. (2019). Echocardiographic quantitation of left heart size "
                "and function in 122 healthy dogs. DOI: 10.1111/jvim.15562."
            )
        if tem_modo_m:
            if any(_modelo_m_exibido(chave, prefixo, "10.3389/fvets.2022.918457")
                   for chave, prefixo in medidas_m):
                estudos.append(
                    "Isayama et al. (2022). Reference Values of M-mode Echocardiographic Parameter in Adult Toy Breed Dogs. "
                    "Limites alométricos aproximados da Tabela 2, calculados pelo peso. DOI: 10.3389/fvets.2022.918457."
                )
            estudos.append(
                "Cornell et al. (2004). Allometric scaling of M-mode cardiac measurements "
                "in normal adult dogs. DOI: 10.1111/j.1939-1676.2004.tb02551.x."
            )
        if modo_m and _to_float(medidas.get("DeltaD_FS")) is not None and referencia.get("fs_source"):
            estudos.append(
                "Visser et al. (2019). Echocardiographic quantitation of left heart size "
                "and function in 122 healthy dogs. DOI: 10.1111/jvim.15562."
            )
        tapse_metadata = referencia.get("range_metadata", {}).get("tapse", {})
        if (tapse and tapse_metadata.get("status") == "published"
                and tapse_metadata.get("doi") == "10.1016/j.jvc.2014.10.003"
                and referencia.get("tapse_min") is not None
                and referencia.get("tapse_max") is not None):
            estudos.append(
                "Visser et al. (2015). Echocardiographic assessment of right "
                "ventricular systolic function in conscious healthy dogs. "
                "DOI: 10.1016/j.jvc.2014.10.003."
            )
        if mapse:
            estudos.append(
                "Schober &amp; Luis Fuentes (2001). Mitral annulus motion in normal dogs "
                "and dogs with cardiac disease. DOI: 10.1111/j.1740-8261.2001.tb00904.x."
            )
    elif referencia and especie == "Felina":
        tem_modelo_m = any(metadados_m.get(prefixo, {}).get("model_weight_kg") is not None
                           for _, prefixo in medidas_m)
        # The new carrier alone does not make an adult source applicable.
        # Preserve the pre-existing bibliography contract for legacy catalogs.
        tem_fonte_m = tem_modo_m and (not tem_modelo_m or any(
            _modelo_m_exibido(chave, prefixo, "10.1111/jvim.14569") for chave, prefixo in medidas_m))
        la_ao_metadata = referencia.get("range_metadata", {}).get("la_ao", {})
        if (tem_fonte_m or (modo_m and referencia.get("fs_source") and _to_float(medidas.get("DeltaD_FS")) is not None)
                or (la_ao_metadata.get("status") == "published" and _to_float(medidas.get("AE_Ao")) is not None)):
            estudos.append(
                "Häggström et al. (2016). Effect of body weight on echocardiographic "
                "measurements in 19,866 pure-bred cats. DOI: 10.1111/jvim.14569."
            )
        if tapse or mapse:
            estudos.append(
                "Spalla et al. (2017). Mitral and tricuspid annular plane systolic "
                "excursion in cats with hypertrophic cardiomyopathy. DOI: 10.1111/jvim.14697."
            )
        if any(_to_float(medidas.get(key)) is not None for key in (
            "AE_diametro_max", "AE_diametro_min", "Fracao_encurtamento_AE",
            "Fluxo_auricular", "Vmax_VSVE",
        )):
            estudos.append(
                "Fuentes et al. (2020). ACVIM consensus statement on cardiomyopathies "
                "in cats. DOI: 10.1111/jvim.15745."
            )
        if _to_float(medidas.get("Fluxo_auricular")) is not None:
            estudos.append(
                "Schober et al. (2006). Left atrial appendage flow velocity and "
                "spontaneous echo contrast in cats. DOI: 10.1111/j.1939-1676.2006.tb02831.x."
            )
        if _to_float(medidas.get("Fracao_encurtamento_AE")) is not None:
            estudos.append(
                "Kochie et al. (2021). Effects of pimobendan on left atrial transport "
                "function in cats. DOI: 10.1111/jvim.15976."
            )

    if tem_limiar_ae_ao_canino:
        if medidas.get("AE_Ao_metodo") == CANINE_AE_AO_SWEDISH_METHOD:
            estudos.extend([
                "Hansson et al. (2002). Left atrial to aortic root indices using "
                "two-dimensional and M-mode echocardiography in Cavalier King Charles "
                "spaniels with and without left atrial enlargement. "
                "DOI: 10.1111/j.1740-8261.2002.tb01051.x.",
                "Georgiev et al. (2013). Common two-dimensional echocardiographic "
                "estimates of aortic linear dimensions are interchangeable. "
                "DOI: 10.1016/j.jvc.2013.02.002.",
            ])
        else:
            estudos.append(
                "Rishniw &amp; Erb (2000). Evaluation of four 2-dimensional "
                "echocardiographic methods of assessing left atrial size in dogs. "
                "DOI: 10.1111/j.1939-1676.2000.tb02252.x."
            )
        estudos.append(
            "Rishniw (2023). Proposed limits for ordinal echocardiographic "
            "estimates of left atrial enlargement in dogs. "
            "DOI: 10.1016/j.jvc.2023.04.003."
        )

    if tem_fluxo_saida and especie == "Canina":
        estudos.append(
            "Petrus et al. (2010). Fluxos aórtico e pulmonar por Doppler pulsado "
            "em 30 cães clinicamente sadios; Ao 1,26 ± 0,13 e pulmonar "
            "0,95 ± 0,18 m/s (médias ± DP). "
            "DOI: 10.1590/S0100-736X2010000700013."
        )
    elif tem_fluxo_saida and especie == "Felina":
        estudos.append(
            "Domanjko Petric et al. (2012). Fluxos aórtico e pulmonar por Doppler "
            "pulsado em 53 gatos domésticos saudáveis sem sedação; Ao 0,77–1,40 "
            "e pulmonar 0,65–1,21 m/s (mínimos e máximos observados). "
            "DOI: 10.1016/j.jvc.2012.04.004."
        )

    estudos.extend(bibliografia_diastolica)
    estudos = list(dict.fromkeys(estudos))
    if not estudos:
        return []

    styles = create_pdf_styles()
    elementos = [Spacer(1, 3 * mm)]
    elementos.append(Paragraph("REFERÊNCIAS BIBLIOGRÁFICAS", styles["ReferenciaTitulo"]))
    elementos.extend(Paragraph(_esc(estudo.replace("&amp;", "&")), styles["ReferenciaTexto"]) for estudo in estudos)
    if referencia.get("reference_origin") == "computed" and tem_modo_m:
        model_metadata = [metadados_m.get(prefixo, {}) for chave, prefixo in medidas_m
                          if any(_modelo_m_exibido(chave, prefixo, doi)
                                 for doi in ("10.3389/fvets.2022.918457", "10.1111/jvim.14569"))]
        measured_metadata = [metadados_m.get(prefixo, {}) for chave, prefixo in medidas_m
                             if _medida_m_exibida(chave)]
        notes = []
        if any(meta.get("calculation") == "allometric" and meta.get("status") in {"published", "estimated"} for meta in model_metadata):
            notes.append("Dimensões em modo M: limites alométricos aproximados calculados para o peso real, a partir da Tabela 2 de Isayama et al. (2022).")
        if any(meta.get("calculation") == "interpolated" and meta.get("status") in {"published", "estimated"} for meta in model_metadata):
            notes.append("Dimensões em modo M: limites aproximados por interpolação entre os pesos da Tabela 3 de Häggström et al. (2016).")
        if any(meta.get("estimate_context") == "weight_extrapolation" for meta in model_metadata):
            notes.append("* Est.: estimativa por extrapolação abaixo de 1,5 kg; não constitui intervalo individual validado e não permite classificação automática.")
        if low_weight_age_context(paciente.get("idade")) == "unknown" and any(
            meta.get("status") == "estimated" for meta in model_metadata
        ):
            notes.append("* Adultos: limites publicados para adultos, apenas para consulta; confirmar idade/maturidade antes de aplicar ao paciente.")
        if any(meta.get("status") == "unavailable" and meta.get("model_weight_kg") for meta in measured_metadata):
            notes.append("Referência de adultos não aplicada a paciente em crescimento; sem referência pediátrica reconciliada.")
        notes.append("Interpretar dimensões e espessuras em conjunto com morfologia, técnica e demais achados; os limites não são cortes diagnósticos isolados.")
        elementos.extend(Paragraph(_esc(note), styles["ReferenciaTexto"]) for note in notes)
    return elementos


def criar_secao_pressao_arterial(pressao: Optional[Dict[str, Any]]) -> List:
    """Cria secao de pressao arterial para laudo eco quando houver dados anexados."""
    elements = []
    styles = create_pdf_styles()

    if not pressao:
        return elements

    def _to_int(value: Any) -> Optional[int]:
        try:
            if value is None or value == "":
                return None
            if isinstance(value, str):
                value = value.replace(",", ".").strip()
            return int(round(float(value)))
        except Exception:
            return None

    pas_1 = _to_int(pressao.get("pas_1"))
    pas_2 = _to_int(pressao.get("pas_2"))
    pas_3 = _to_int(pressao.get("pas_3"))
    pas_media = _to_int(pressao.get("pas_media"))

    valores = [v for v in [pas_1, pas_2, pas_3] if v is not None and v > 0]
    if pas_media is None and valores:
        pas_media = int(round(sum(valores) / len(valores)))

    metodo = (pressao.get("metodo") or "Doppler").strip() or "Doppler"
    manguito = (pressao.get("manguito") or "").strip()
    membro = (pressao.get("membro") or "").strip()
    decubito = (pressao.get("decubito") or "").strip()
    obs_extra = (pressao.get("obs_extra") or "").strip()

    tem_medicoes = bool(valores or (pas_media is not None and pas_media > 0))
    if not tem_medicoes:
        return elements

    classificacao = "Sem classificacao (media indisponivel)."
    if pas_media is not None and pas_media > 0:
        if pas_media <= 140:
            classificacao = "Normal (110 a 140 mmHg)"
        elif pas_media <= 159:
            classificacao = "Levemente elevada (141 a 159 mmHg)"
        elif pas_media <= 179:
            classificacao = "Moderadamente elevada (160 a 179 mmHg)"
        else:
            classificacao = "Severamente elevada (>= 180 mmHg)"

    resumo_label_style = ParagraphStyle(
        "PressaoResumoLabel",
        parent=styles["Normal"],
        fontSize=8.5,
        textColor=COR_CINZA_ESCURO,
        alignment=1,
        fontName="Helvetica-Bold",
    )
    resumo_valor_style = ParagraphStyle(
        "PressaoResumoValor",
        parent=styles["Normal"],
        fontSize=11,
        textColor=COR_PRETO,
        alignment=1,
        fontName="Helvetica-Bold",
        leading=13,
    )
    detalhe_label_style = ParagraphStyle(
        "PressaoDetalheLabel",
        parent=styles["Normal"],
        fontSize=8.5,
        textColor=COR_CINZA_ESCURO,
        alignment=1,
        fontName="Helvetica-Bold",
    )
    detalhe_valor_style = ParagraphStyle(
        "PressaoDetalheValor",
        parent=styles["Normal"],
        fontSize=9.5,
        textColor=COR_PRETO,
        alignment=1,
        leading=12,
    )
    texto_box_style = ParagraphStyle(
        "PressaoTextoBox",
        parent=styles["Normal"],
        fontSize=10,
        textColor=COR_PRETO,
        leading=13,
    )

    classificacao_bg = colors.HexColor("#ecfdf5")
    classificacao_border = colors.HexColor("#15803d")
    if pas_media is not None and pas_media > 0:
        if pas_media <= 140:
            classificacao_bg = colors.HexColor("#ecfdf5")
            classificacao_border = colors.HexColor("#15803d")
        elif pas_media <= 159:
            classificacao_bg = colors.HexColor("#fefce8")
            classificacao_border = colors.HexColor("#ca8a04")
        elif pas_media <= 179:
            classificacao_bg = colors.HexColor("#fff7ed")
            classificacao_border = colors.HexColor("#ea580c")
        else:
            classificacao_bg = colors.HexColor("#fef2f2")
            classificacao_border = colors.HexColor("#dc2626")

    bloco_secao = [Spacer(1, 4 * mm), criar_titulo_secao("PRESSAO ARTERIAL (ANEXO)"), Spacer(1, 2 * mm)]

    tabela_resumo = Table(
        [[
            Paragraph("1a afericao", resumo_label_style),
            Paragraph("2a afericao", resumo_label_style),
            Paragraph("3a afericao", resumo_label_style),
            Paragraph("PAS media", resumo_label_style),
        ], [
            Paragraph(f"{pas_1 or '-'} mmHg", resumo_valor_style),
            Paragraph(f"{pas_2 or '-'} mmHg", resumo_valor_style),
            Paragraph(f"{pas_3 or '-'} mmHg", resumo_valor_style),
            Paragraph(f"{pas_media or '-'} mmHg", resumo_valor_style),
        ]],
        colWidths=[45 * mm, 45 * mm, 45 * mm, 45 * mm],
    )
    tabela_resumo.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, COR_CINZA_CLARO),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, COR_CINZA_CLARO),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    bloco_secao.append(tabela_resumo)
    bloco_secao.append(Spacer(1, 2 * mm))

    tabela_procedimento = Table(
        [[
            Paragraph("Metodo", detalhe_label_style),
            Paragraph("Manguito", detalhe_label_style),
            Paragraph("Membro", detalhe_label_style),
            Paragraph("Decubito", detalhe_label_style),
        ], [
            Paragraph(_esc(metodo or "-"), detalhe_valor_style),
            Paragraph(_esc(manguito or "-"), detalhe_valor_style),
            Paragraph(_esc(membro or "-"), detalhe_valor_style),
            Paragraph(_esc(decubito or "-"), detalhe_valor_style),
        ]],
        colWidths=[45 * mm, 45 * mm, 45 * mm, 45 * mm],
    )
    tabela_procedimento.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, COR_CINZA_CLARO),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, COR_CINZA_CLARO),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    bloco_secao.append(tabela_procedimento)
    bloco_secao.append(Spacer(1, 2 * mm))

    tabela_classificacao = Table(
        [[Paragraph(f"<b>Classificacao PAS</b><br/>{_esc(classificacao)}", texto_box_style)]],
        colWidths=[180 * mm],
    )
    tabela_classificacao.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, classificacao_border),
        ("BACKGROUND", (0, 0), (-1, -1), classificacao_bg),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    bloco_secao.append(tabela_classificacao)

    if obs_extra:
        bloco_secao.append(Spacer(1, 2 * mm))
        tabela_obs = Table(
            [[Paragraph("<b>Observacoes adicionais</b><br/>" + _esc(obs_extra), texto_box_style)]],
            colWidths=[180 * mm],
        )
        tabela_obs.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.8, COR_CINZA_CLARO),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fafafa")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        bloco_secao.append(tabela_obs)

    elements.append(_bloco_sem_quebra(*bloco_secao))

    return elements


def criar_secao_conclusao(conclusao: str) -> List:
    """Cria a seção de conclusão"""
    elements = []
    styles = create_pdf_styles()
    
    if not conclusao or not conclusao.strip():
        return elements
    
    conclusao_box_style = ParagraphStyle(
        "ConclusaoBox",
        parent=styles["Conclusao"],
        fontSize=10.5,
        leading=14,
        spaceAfter=1.5 * mm,
    )
    conclusao_item_label_style = ParagraphStyle(
        "ConclusaoItemLabel",
        parent=styles["Conclusao"],
        leftIndent=4 * mm,
        spaceAfter=0.5 * mm,
    )
    conclusao_item_body_style = ParagraphStyle(
        "ConclusaoItemBody",
        parent=styles["Conclusao"],
        leftIndent=9 * mm,
        leading=14,
        spaceAfter=1.5 * mm,
    )

    def _separar_blocos(texto_bruto: str) -> List[str]:
        blocos: List[str] = []
        atual: List[str] = []
        for linha in texto_bruto.splitlines():
            if linha.strip():
                atual.append(linha.strip())
            elif atual:
                blocos.append("\n".join(atual).strip())
                atual = []
        if atual:
            blocos.append("\n".join(atual).strip())
        return blocos

    def _quebrar_itens(texto_bruto: str) -> List[str]:
        itens: List[str] = []
        atual = ""
        for linha in texto_bruto.splitlines():
            linha_limpa = linha.strip()
            if not linha_limpa:
                continue
            if linha_limpa.startswith(("-", "*", "•")):
                if atual:
                    itens.append(atual.strip())
                atual = linha_limpa[1:].strip()
            elif atual:
                atual = f"{atual} {linha_limpa}"
            else:
                atual = linha_limpa
        if atual:
            itens.append(atual.strip())
        return itens

    elements.append(Spacer(1, 4*mm))
    elements.append(criar_titulo_secao("CONCLUSÃO"))
    elements.append(Spacer(1, 2*mm))

    conteudo = []
    for bloco in _separar_blocos(conclusao.strip()):
        linhas_validas = [linha.strip() for linha in bloco.splitlines() if linha.strip()]
        tem_marcadores = any(linha.startswith(("-", "*", "•")) for linha in linhas_validas)

        if tem_marcadores:
            for item in _quebrar_itens(bloco):
                titulo_item, separador, corpo_item = item.partition(":")
                titulo_item = titulo_item.strip()
                corpo_item = corpo_item.strip()

                if separador:
                    conteudo.append(
                        Paragraph(f"&bull; <b>{_esc(titulo_item)}</b>", conclusao_item_label_style)
                    )
                    conteudo.append(Paragraph(_esc(corpo_item), conclusao_item_body_style))
                else:
                    conteudo.append(Paragraph(f"&bull; {_esc(item)}", conclusao_box_style))
        else:
            conteudo.append(
                Paragraph(_esc(bloco).replace("\n", "<br/>"), conclusao_box_style)
            )

    caixa_conclusao = Table([[conteudo]], colWidths=[180 * mm])
    caixa_conclusao.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, COR_CINZA_CLARO),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fafafa")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(_bloco_sem_quebra(caixa_conclusao))
    
    return elements


def criar_secao_assinatura(
    nome_veterinario: str,
    crmv: str = "",
    temp_assinatura_path: str = None,
    compacto: bool = False,
) -> List:
    """Cria a seção de assinatura"""
    elements = []
    styles = create_pdf_styles()
    
    elements.append(Spacer(1, (3 if compacto else 10)*mm))
    
    # Linha divisória antes da assinatura
    line_data = [['']]
    line_table = Table(line_data, colWidths=[180*mm])
    line_table.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, -1), 1, colors.grey),
    ]))
    elements.append(line_table)
    elements.append(Spacer(1, (2 if compacto else 5)*mm))
    
    # Se tem assinatura em imagem
    if temp_assinatura_path and os.path.exists(temp_assinatura_path):
        try:
            # Calcular dimensões preservando aspect ratio
            MAX_ASS_WIDTH = 50*mm
            MAX_ASS_HEIGHT = 25*mm
            
            img_reader = ImageReader(temp_assinatura_path)
            img_width, img_height = img_reader.getSize()
            aspect = img_height / float(img_width) if img_width else 1
            
            # Ajustar para caber no espaço máximo mantendo proporção
            if aspect > (MAX_ASS_HEIGHT / MAX_ASS_WIDTH):
                # Altura é o fator limitante
                draw_height = MAX_ASS_HEIGHT
                draw_width = MAX_ASS_HEIGHT / aspect
            else:
                # Largura é o fator limitante
                draw_width = MAX_ASS_WIDTH
                draw_height = MAX_ASS_WIDTH * aspect
            
            ass_img = Image(temp_assinatura_path, width=draw_width, height=draw_height)
            ass_img.hAlign = 'LEFT'
            elements.append(ass_img)
        except Exception as e:
            print(f"Erro ao adicionar assinatura: {e}")
    
    # Nome e CRMV
    elements.append(Paragraph(f"<b>{_esc(nome_veterinario)}</b>", styles['Normal']))
    if crmv:
        elements.append(Paragraph(f"Médico Veterinário - CRMV: {_esc(crmv)}", styles['Normal']))
    elif nome_veterinario.strip().lower() != "médico veterinário":
        elements.append(Paragraph("Médico Veterinário", styles['Normal']))
    
    return elements


def criar_rodape(texto_rodape: str = None) -> List:
    """Cria o rodapé para o final do conteúdo (não usado mais, ver footer_todas_paginas)"""
    elements = []
    styles = create_pdf_styles()
    
    texto = texto_rodape or "Fort Cordis Cardiologia Veterinária | Fortaleza-CE"
    
    elements.append(Spacer(1, 8*mm))
    elements.append(Paragraph(_esc(texto), styles['Rodape']))
    
    return elements


def footer_todas_paginas(canvas_obj, doc, texto_rodape: str = None):
    """Adiciona rodapé em todas as páginas do PDF - conforme modelo de referência"""
    canvas_obj.saveState()
    
    texto = texto_rodape or "Fort Cordis Cardiologia Veterinária | Fortaleza-CE"
    
    # Configurações do rodapé
    canvas_obj.setFont('Helvetica-Oblique', 8)
    canvas_obj.setFillColor(COR_CINZA_MEDIO)
    
    # Posição do rodapé (centralizado na parte inferior)
    page_width = A4[0]
    y_position = 10*mm
    
    # Texto do rodapé centralizado
    canvas_obj.drawCentredString(page_width / 2, y_position, texto)
    
    canvas_obj.restoreState()


def gerar_pdf_laudo_eco(
    dados: Dict[str, Any],
    logomarca_bytes: bytes = None,
    assinatura_bytes: bytes = None,
    nome_veterinario: str = None,
    crmv: str = None,
    texto_rodape: str = None,
    *,
    preview: bool = False,
) -> bytes:
    """
    Gera o PDF completo do laudo ecocardiográfico.
    
    Args:
        dados: Dicionário com:
            - paciente: dict com nome, especie, raca, sexo, idade, peso, tutor, data_exame
            - medidas: dict com valores das medidas
            - qualitativa: dict com valvas, camaras, funcao, pericardio, vasos, ad_vd
            - conclusao: string
            - clinica: string (opcional)
            - imagens: list de bytes (opcional)
        logomarca_bytes: bytes da imagem da logomarca
        assinatura_bytes: bytes da imagem da assinatura
        nome_veterinario: nome do veterinário para assinatura
        crmv: número do CRMV do veterinário
        texto_rodape: texto personalizado para o rodapé
    
    Returns:
        bytes: Conteúdo do PDF
    """
    temp_files = []
    
    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=15*mm,
            leftMargin=15*mm,
            topMargin=15*mm,
            bottomMargin=15*mm
        )
        
        elements = []
        
        # Criar arquivos temporários para imagens
        temp_logo_path = None
        temp_assinatura_path = None
        
        if logomarca_bytes:
            temp_logo = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_logo.write(logomarca_bytes)
            temp_logo.close()
            temp_logo_path = temp_logo.name
            temp_files.append(temp_logo_path)
        
        if assinatura_bytes:
            temp_ass = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_ass.write(assinatura_bytes)
            temp_ass.close()
            temp_assinatura_path = temp_ass.name
            temp_files.append(temp_assinatura_path)
        
        # 1. Cabeçalho: logo + título, depois dados do paciente
        dados_pdf = dict(dados)
        dados_pdf["unidades_ambiguas"] = medidas_com_unidade_ambigua(dados.get("medidas", {}))
        dados_pdf["medidas"] = normalizar_medidas_para_pdf(dados.get("medidas", {}))
        # A direct renderer caller can bypass both DB-backed PDF loaders. Apply
        # the same safety policy here before any row or bibliography is built.
        paciente = dados_pdf.get("paciente") or {}
        referencia = dados.get("referencia_eco") or low_weight_reference_seed(
            paciente.get("especie"), _to_float_peso(paciente.get("peso")), paciente.get("idade"),
        )
        if referencia:
            paciente = dados_pdf.get("paciente") or {}
            especie = normalizar_especie_referencia(paciente.get("especie"))
            especie_referencia = normalizar_especie_referencia(referencia.get("especie"))
            if especie and especie_referencia and especie != especie_referencia:
                dados_pdf["referencia_eco"] = None
            else:
                peso = _to_float_peso(paciente.get("peso"))
                if peso is None or not math.isfinite(peso) or peso <= 0:
                    dados_pdf["referencia_eco"] = None
                else:
                    dados_pdf["referencia_eco"] = aplicar_defaults_publicados_caninos(
                        {**referencia, "especie": especie or especie_referencia,
                         "patient_age": paciente.get("idade")},
                        peso_kg=peso, medidas=dados_pdf["medidas"],
                    )
        recalcular_dived_normalizado_para_pdf(dados_pdf)
        recalcular_marcadores_felinos_para_pdf(dados_pdf)
        derivar_gradientes_saidas_para_pdf(dados_pdf)
        elements.extend(criar_cabecalho(dados_pdf, temp_logo_path))

        # A conclusão já escrita pelo veterinário fica visível na primeira
        # página, sem duplicação nem interpretação gerada pelo sistema.
        conclusao = dados_pdf.get('conclusao', '')
        elements.extend(criar_secao_conclusao(conclusao))
        if conclusao and conclusao.strip():
            elements.append(Spacer(1, 3 * mm))

        # 2. Análise Quantitativa (título com mesma largura das tabelas)
        elements.append(criar_titulo_secao("ANÁLISE QUANTITATIVA"))
        elements.append(Spacer(1, 2*mm))
        if dados_pdf["unidades_ambiguas"]:
            elements.append(Paragraph(
                "Unidade a confirmar nas medidas indicadas; confira o exame de origem antes de interpretar essas dimensões.",
                create_pdf_styles()["Normal"],
            ))
            elements.append(Spacer(1, 2*mm))
        referencia_selecionada = dados_pdf.get("referencia_eco")
        if not referencia_selecionada:
            tem_consulta_diastolica = any(
                ref["kind"] in {"descriptive", "reference_interval"} for ref in diastolic_references(
                    dados_pdf.get("medidas") or {}, (dados_pdf.get("paciente") or {}).get("especie"),
                ).values()
            )
            nota_sem_faixa = (
                "Traço indica referência indisponível."
                if tem_consulta_diastolica
                else "Traço indica faixa de referência indisponível."
                if canine_ae_ao_clinical_limit_applies(dados_pdf)
                else "Faixas de referência indisponíveis para este paciente; traço indica faixa indisponível."
            )
            elements.append(Paragraph(
                nota_sem_faixa,
                create_pdf_styles()["Normal"],
            ))
            elements.append(Spacer(1, 2 * mm))
        
        # =================================================================
        # Definição dos parâmetros - Layout conforme modelo de referência
        # =================================================================
        
        # Grupo: VE - Modo B e Modo M (tabela única com todos os parâmetros)
        # Conforme solicitado: COM Referência, SEM Interpretação
        params_ve_modo_m = [
            {'chave': 'DIVEd', 'label': 'DIVEd (Diâmetro interno do VE em diástole)', 'unidade': 'mm', 'ref_min': 16.0, 'ref_max': 24.0},
            {'chave': 'DIVEd_normalizado', 'label': 'DIVEd normalizado (DIVEd [cm] / peso^0,294)', 'unidade': '', 'ref_min': None, 'ref_max': None},
            {'chave': 'SIVd', 'label': 'SIVd (Septo interventricular em diástole)', 'unidade': 'mm', 'ref_min': 3.5, 'ref_max': 5.5},
            {'chave': 'PLVEd', 'label': 'PLVEd (Parede livre do VE em diástole)', 'unidade': 'mm', 'ref_min': 3.5, 'ref_max': 5.5},
            {'chave': 'DIVES', 'label': 'DIVEs (Diâmetro interno do VE em sístole)', 'unidade': 'mm', 'ref_min': 9.0, 'ref_max': 16.0},
            {'chave': 'SIVs', 'label': 'SIVs (Septo interventricular em sístole)', 'unidade': 'mm', 'ref_min': 4.5, 'ref_max': 7.5},
            {'chave': 'PLVES', 'label': 'PLVEs (Parede livre do VE em sístole)', 'unidade': 'mm', 'ref_min': 5.0, 'ref_max': 8.0},
            {'chave': 'VDF', 'label': 'VDF (Teicholz)', 'unidade': 'ml', 'ref_min': 0, 'ref_max': 0},
            {'chave': 'VSF', 'label': 'VSF (Teicholz)', 'unidade': 'ml', 'ref_min': 0, 'ref_max': 0},
            {'chave': 'FE_Teicholz', 'label': 'FE (Teicholz)', 'unidade': '%', 'ref_min': 55, 'ref_max': 80},
            {'chave': 'DeltaD_FS', 'label': 'Delta D / %FS', 'unidade': '%', 'ref_min': 28, 'ref_max': 42},
        ]
        params_ve_modo_2d = [
            {'chave': 'DIVEd_2D', 'label': 'DIVEd 2D (Diâmetro interno do VE em diástole)', 'unidade': 'mm', 'ref_min': 16.0, 'ref_max': 24.0},
            {'chave': 'DIVEd_normalizado_2D', 'label': 'DIVEd normalizado 2D - Visser (DIVEd [cm] / peso^0,316)', 'unidade': '', 'ref_min': None, 'ref_max': None},
            {'chave': 'SIVd_2D', 'label': 'SIVd 2D (Septo interventricular em diástole)', 'unidade': 'mm', 'ref_min': 3.5, 'ref_max': 5.5},
            {'chave': 'PLVEd_2D', 'label': 'PLVEd 2D (Parede livre do VE em diástole)', 'unidade': 'mm', 'ref_min': 3.5, 'ref_max': 5.5},
            {'chave': 'DIVES_2D', 'label': 'DIVEs 2D (Diâmetro interno do VE em sístole)', 'unidade': 'mm', 'ref_min': 9.0, 'ref_max': 16.0},
            {'chave': 'SIVs_2D', 'label': 'SIVs 2D (Septo interventricular em sístole)', 'unidade': 'mm', 'ref_min': 4.5, 'ref_max': 7.5},
            {'chave': 'PLVES_2D', 'label': 'PLVEs 2D (Parede livre do VE em sístole)', 'unidade': 'mm', 'ref_min': 5.0, 'ref_max': 8.0},
            {'chave': 'VDF_2D', 'label': 'VDF 2D (Teicholz)', 'unidade': 'ml', 'ref_min': 0, 'ref_max': 0},
            {'chave': 'VSF_2D', 'label': 'VSF 2D (Teicholz)', 'unidade': 'ml', 'ref_min': 0, 'ref_max': 0},
            {'chave': 'FE_Teicholz_2D', 'label': 'FE 2D (Teicholz)', 'unidade': '%', 'ref_min': 55, 'ref_max': 80},
            {'chave': 'DeltaD_FS_2D', 'label': 'Delta D / %FS 2D', 'unidade': '%', 'ref_min': 28, 'ref_max': 42},
        ]
        params_excursao_anular = [
            {'chave': 'TAPSE', 'label': 'TAPSE (excursão sistólica do plano anular tricúspide)', 'unidade': 'mm', 'ref_min': None, 'ref_max': None},
            {'chave': 'MAPSE', 'label': 'MAPSE (excursão sistólica do plano anular mitral)', 'unidade': 'mm', 'ref_min': None, 'ref_max': None},
        ]
        
        # Grupo: Átrio Esquerdo / Aorta - SEM Interpretação
        params_ae_aorta = [
            {'chave': 'Aorta', 'label': 'Aorta', 'unidade': 'mm', 'ref_min': None, 'ref_max': None},
            {'chave': 'Atrio_esquerdo', 'label': 'Átrio esquerdo', 'unidade': 'mm', 'ref_min': None, 'ref_max': None},
            {'chave': 'AE_Ao', 'label': 'AE/Ao (Átrio esquerdo/Aorta)', 'unidade': '', 'ref_min': 0.80, 'ref_max': 1.60},
        ]
        # Medidas específicas felinos (dentro da mesma tabela AE/Ao)
        paciente_especie = (dados_pdf.get("paciente") or {}).get("especie") or ""
        if normalizar_especie_referencia(paciente_especie) == "Felina":
            params_ae_aorta.extend([
                {'chave': 'AE_diametro_max', 'label': 'AE - diâmetro máximo', 'unidade': 'mm', 'ref_min': None, 'ref_max': None},
                {'chave': 'AE_diametro_min', 'label': 'AE - diâmetro mínimo', 'unidade': 'mm', 'ref_min': None, 'ref_max': None},
                {'chave': 'Fracao_encurtamento_AE', 'label': 'Fração de encurtamento do AE', 'unidade': '%', 'ref_min': None, 'ref_max': None},
                {'chave': 'Fluxo_auricular', 'label': 'Velocidade máxima do apêndice atrial esquerdo', 'unidade': 'm/s', 'ref_min': None, 'ref_max': None},
            ])
        
        # Grupo: Artéria Pulmonar / Aorta - SEM Interpretação
        params_ap_aorta = [
            {'chave': 'AP', 'label': 'AP (Artéria pulmonar)', 'unidade': 'mm', 'ref_min': None, 'ref_max': None},
            {'chave': 'Ao_nivel_AP', 'label': 'Ao (Aorta - nível AP)', 'unidade': 'mm', 'ref_min': None, 'ref_max': None},
            {'chave': 'AP_Ao', 'label': 'AP/Ao (Artéria pulmonar/Aorta)', 'unidade': '', 'ref_min': None, 'ref_max': None},
        ]
        
        # Grupo: Doppler - Saídas - SEM Interpretação
        params_doppler_saidas = parametros_saidas_para_pdf(dados_pdf["medidas"])
        
        # Grupo: Diastólica - SEM Interpretação
        params_diastolica = [
            {'chave': 'Onda_E', 'label': 'Onda E', 'unidade': 'm/s', 'ref_min': None, 'ref_max': None},
            {'chave': 'Onda_A', 'label': 'Onda A', 'unidade': 'm/s', 'ref_min': None, 'ref_max': None},
            {'chave': 'E_A', 'label': 'E/A (relação E/A)', 'unidade': '', 'ref_min': None, 'ref_max': None},
            {'chave': 'TD', 'label': 'TD (tempo desaceleração)', 'unidade': 'ms', 'ref_min': None, 'ref_max': None},
            {'chave': 'TRIV', 'label': 'TRIV (tempo relaxamento isovolumétrico)', 'unidade': 'ms', 'ref_min': None, 'ref_max': None},
            {'chave': 'E_TRIV', 'label': 'E/TRIV (índice E [cm/s] / TRIV [ms])', 'unidade': '', 'ref_min': None, 'ref_max': None},
            {'chave': 'MR_dp_dt', 'label': 'MR dp/dt', 'unidade': 'mmHg/s', 'ref_min': None, 'ref_max': None},
            {'chave': 'e_doppler', 'label': "e' (Doppler tecidual)", 'unidade': 'm/s', 'ref_min': None, 'ref_max': None},
            {'chave': 'a_doppler', 'label': "a' (Doppler tecidual)", 'unidade': 'm/s', 'ref_min': None, 'ref_max': None},
            {'chave': 'doppler_tecidual_relacao', 'label': "Doppler tecidual (Relação e'/a')", 'unidade': '', 'ref_min': None, 'ref_max': None},
            {'chave': 'E_E_linha', 'label': "E/E'", 'unidade': '', 'ref_min': None, 'ref_max': None},
        ]
        
        # Grupo: Regurgitações - SEM Interpretação
        params_regurgitacoes = [
            {'chave': 'IM_Vmax', 'label': 'IM (insuficiência mitral) Vmax', 'unidade': 'm/s', 'ref_min': None, 'ref_max': None},
            {'chave': 'IM_Grad', 'label': 'Gradiente da insuficiência mitral (4 × V²)', 'unidade': 'mmHg', 'ref_min': None, 'ref_max': None},
            {'chave': 'IT_Vmax', 'label': 'IT (insuficiência tricúspide) Vmax', 'unidade': 'm/s', 'ref_min': None, 'ref_max': None},
            {'chave': 'IT_Grad', 'label': 'Gradiente da insuficiência tricúspide (4 × V²)', 'unidade': 'mmHg', 'ref_min': None, 'ref_max': None},
            {'chave': 'PAD_estimada', 'label': 'Pressão atrial direita estimada', 'unidade': 'mmHg', 'ref_min': None, 'ref_max': None},
            {'chave': 'PSAP', 'label': 'PSAP estimada (gradiente IT + PAD estimada)', 'unidade': 'mmHg', 'ref_min': None, 'ref_max': None},
            {'chave': 'IA_Vmax', 'label': 'IA (insuficiência aórtica) Vmax', 'unidade': 'm/s', 'ref_min': None, 'ref_max': None},
            {'chave': 'IA_Grad', 'label': 'Gradiente da insuficiência aórtica (4 × V²)', 'unidade': 'mmHg', 'ref_min': None, 'ref_max': None},
            {'chave': 'IP_Vmax', 'label': 'IP (insuficiência pulmonar) Vmax', 'unidade': 'm/s', 'ref_min': None, 'ref_max': None},
            {'chave': 'IP_Grad', 'label': 'Gradiente da insuficiência pulmonar (4 × V²)', 'unidade': 'mmHg', 'ref_min': None, 'ref_max': None},
        ]
        
        # Aplicar referências do banco de dados se disponíveis
        referencia_eco = dados_pdf.get("referencia_eco")
        params_ve_modo_m = aplicar_referencia_eco(params_ve_modo_m, referencia_eco)
        params_ve_modo_2d = aplicar_referencia_eco(params_ve_modo_2d, referencia_eco)
        params_ve_modo_2d = aplicar_referencias_2d_publicadas(params_ve_modo_2d, dados_pdf)
        params_excursao_anular = aplicar_referencia_eco(params_excursao_anular, referencia_eco)
        params_ae_aorta = aplicar_referencia_eco(params_ae_aorta, referencia_eco)
        tem_limiar_ae_ao_canino = canine_ae_ao_clinical_limit_applies(dados_pdf)
        if tem_limiar_ae_ao_canino:
            # This clinical threshold is independent of the numeric catalog;
            # do not reinstate its unsupported lower bound or label a PI.
            params_ae_aorta = [
                {**param, "ref_min": None, "ref_max": None,
                 "ref_text": CANINE_AE_AO_REFERENCE_TEXT}
                if param["chave"] == "AE_Ao" else param
                for param in params_ae_aorta
            ]
        params_ap_aorta = aplicar_referencia_eco(params_ap_aorta, referencia_eco)
        params_doppler_saidas = aplicar_referencia_eco(params_doppler_saidas, referencia_eco)
        params_diastolica = aplicar_referencia_eco(params_diastolica, referencia_eco)
        consultas_diastolicas = diastolic_references(
            dados_pdf.get("medidas") or {}, (dados_pdf.get("paciente") or {}).get("especie"),
        )
        indices_diastolicos_a_confirmar = diastolic_indices_awaiting_confirmation(
            dados_pdf.get("medidas") or {}, (dados_pdf.get("paciente") or {}).get("especie"),
        )
        # Only a published individual reference interval receives min/max bounds.
        # Means/SD and fusion guards remain neutral; no catalog fallback.
        params_diastolica = [
            {**param, "ref_min": consultas_diastolicas[param["chave"]].get("min"),
             "ref_max": consultas_diastolicas[param["chave"]].get("max"),
             "ref_text": consultas_diastolicas[param["chave"]]["text"] or None,
             "value_unconfirmed": param["chave"] in indices_diastolicos_a_confirmar,
             "value_unmeasurable": consultas_diastolicas[param["chave"]]["kind"] == "uninterpretable"}
            if param["chave"] in consultas_diastolicas else param
            for param in params_diastolica
        ]
        params_regurgitacoes = aplicar_referencia_eco(params_regurgitacoes, referencia_eco)
        
        # =================================================================
        # Montar tabelas conforme modelo de referência
        # =================================================================
        
        medidas_pdf = dados_pdf.get("medidas") or {}
        tecnica_ve = str(medidas_pdf.get("VE_tecnica_relatorio") or "").lower()
        tem_modo_m = any(_to_float(medidas_pdf.get(item["chave"])) for item in params_ve_modo_m)
        tem_modo_2d = any(_to_float(medidas_pdf.get(item["chave"])) for item in params_ve_modo_2d)
        if tecnica_ve == "2d" or (tem_modo_2d and not tem_modo_m):
            titulo_ve = "VE - Modo 2D"
            params_ve_relatorio = params_ve_modo_2d
        else:
            titulo_ve = "VE - Modo M"
            params_ve_relatorio = params_ve_modo_m

        grupos_medidas = (
            (titulo_ve, params_ve_relatorio),
            ("Excursão do plano anular", params_excursao_anular),
            ("Átrio esquerdo/ Aorta", params_ae_aorta),
            ("Artéria pulmonar/ Aorta", params_ap_aorta),
            ("Doppler - Saídas", params_doppler_saidas),
            ("Diastólica", params_diastolica),
            ("Regurgitações", params_regurgitacoes),
        )
        grupos_preenchidos = [
            (titulo, filtrar_parametros_preenchidos(parametros, medidas_pdf))
            for titulo, parametros in grupos_medidas
        ]
        if not any(parametros for _, parametros in grupos_preenchidos):
            elements.append(Paragraph("Medidas não registradas.", create_pdf_styles()["Normal"]))
        for titulo, parametros in grupos_preenchidos:
            if not parametros:
                continue
            bloco_tabela = [criar_tabela_medidas(
                titulo,
                parametros,
                dados_pdf,
                mostrar_referencia=True,
                mostrar_interpretacao=False,
            )]
            if titulo == "Átrio esquerdo/ Aorta" and tem_limiar_ae_ao_canino:
                bloco_tabela.extend([
                    Spacer(1, 1 * mm),
                    Paragraph(
                        CANINE_AE_AO_SWEDISH_METHOD_NOTE
                        if medidas_pdf.get("AE_Ao_metodo") == CANINE_AE_AO_SWEDISH_METHOD
                        else CANINE_AE_AO_METHOD_NOTE,
                        create_pdf_styles()["ReferenciaTexto"],
                    ),
                ])
            if titulo == "Doppler - Saídas":
                for nota in notas_saidas_para_pdf(medidas_pdf):
                    bloco_tabela.extend([Spacer(1, 1 * mm), Paragraph(_esc(nota), create_pdf_styles()["ReferenciaTexto"])])
            if titulo == "Diastólica":
                for nota in diastolic_notes(medidas_pdf, (dados_pdf.get("paciente") or {}).get("especie")):
                    bloco_tabela.extend([Spacer(1, 1 * mm), Paragraph(_esc(nota), create_pdf_styles()["ReferenciaTexto"])])
            if titulo == "Diastólica" and consultas_diastolicas:
                # The branded header can leave space for the table but not for
                # all cohort/method notes. Allow row-wise pagination instead
                # of moving the whole clinical block to an otherwise empty page.
                elements.extend(bloco_tabela)
                elements.append(Spacer(1, 3 * mm))
            else:
                elements.append(
                    _bloco_sem_quebra(
                        *bloco_tabela,
                        Spacer(1, 3 * mm),
                    )
                )
        
        # 3. Análise Qualitativa
        qualitativa = dados_pdf.get('qualitativa', {})
        imagens = dados_pdf.get('imagens', [])
        pressao_arterial = dados_pdf.get("pressao_arterial")
        vet_nome = nome_veterinario or dados_pdf.get('veterinario_nome') or "Médico Veterinário"
        vet_crmv = crmv or dados_pdf.get('veterinario_crmv') or ""
        assinatura = criar_secao_assinatura(vet_nome, vet_crmv, temp_assinatura_path, compacto=True)
        referencias = criar_secao_referencias_eco(dados_pdf)
        secao_pressao = criar_secao_pressao_arterial(pressao_arterial)
        qualitativa_preenchida = bool(qualitativa and any(
            qualitativa.get(k, '').strip() for k in ['valvas', 'camaras', 'ad_vd', 'funcao', 'pericardio', 'vasos']
        ))
        # A grade de imagens pode vir depois da assinatura sem separá-la do
        # último grupo qualitativo quando a página narrativa fica cheia.
        assinatura_com_qualitativa = qualitativa_preenchida and not secao_pressao
        if qualitativa_preenchida:
            elements.extend(criar_secao_qualitativa(
                qualitativa,
                assinatura=assinatura if assinatura_com_qualitativa else None,
            ))

        # Pressao arterial anexada ao laudo ecocardiografico (quando existir).
        elements.extend(secao_pressao)
        
        # 5. Assinatura
        if not assinatura_com_qualitativa:
            elements.extend(assinatura)
        if referencias:
            elements.append(_bloco_sem_quebra(*referencias))

        # 7. Imagens (se houver) - Layout conforme modelo de referência
        if imagens:
            # A gap belongs to an image section, never to the end of a report:
            # it can otherwise create a footer-only page at the frame boundary.
            elements.append(Spacer(1, 5*mm))
            paciente_imagens = dados_pdf.get("paciente") or {}
            nome_imagens = _esc(paciente_imagens.get("nome") or "")
            data_imagens = _esc(paciente_imagens.get("data_exame") or "")
            identificacao_imagens = " | ".join(
                parte for parte in (
                    f"Paciente: {nome_imagens}" if nome_imagens else "",
                    f"Data do exame: {data_imagens}" if data_imagens else "",
                ) if parte
            )
            # Aproveita a página da assinatura quando houver espaço para uma
            # linha completa de imagens; evita iniciar a grade espremida no
            # rodapé da narrativa.
            elements.append(CondPageBreak(130 * mm))
            
            # Layout 2x3 (6 imagens por página) - similar ao modelo de referência
            IMG_WIDTH = 85*mm
            IMG_HEIGHT = 60*mm
            ESPACAMENTO = 3*mm
            legenda_imagem_style = ParagraphStyle(
                "LegendaImagemEco",
                parent=create_pdf_styles()["Normal"],
                fontSize=8,
                leading=10,
                alignment=1,
                textColor=COR_CINZA_ESCURO,
            )
            
            # Processar imagens em grupos de 6, deixando o fluxo da tabela
            # continuar na página seguinte sem criar uma página quase vazia.
            for page_idx in range(0, len(imagens), 6):
                # Pegar até 6 imagens para esta página
                page_imagens = imagens[page_idx:page_idx + 6]
                
                # Criar grid 2x3 (2 colunas, 3 linhas)
                table_data = []
                row = []
                
                for idx, imagem_pdf in enumerate(page_imagens):
                    try:
                        img_bytes = imagem_pdf.get("conteudo") if isinstance(imagem_pdf, dict) else imagem_pdf
                        descricao_imagem = str(imagem_pdf.get("descricao") or "").strip() if isinstance(imagem_pdf, dict) else ""
                        if not img_bytes:
                            continue
                            
                        # Criar arquivo temporário para a imagem
                        temp_img = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
                        temp_img.write(img_bytes)
                        temp_img.close()
                        temp_files.append(temp_img.name)
                        
                        # Adicionar imagem ao grid com proporção preservada
                        try:
                            img_reader = ImageReader(temp_img.name)
                            img_width, img_height = img_reader.getSize()
                            
                            # Calcular proporção para caber no espaço
                            aspect = img_height / float(img_width) if img_width else 1
                            if aspect > (IMG_HEIGHT / IMG_WIDTH):
                                draw_height = IMG_HEIGHT
                                draw_width = IMG_HEIGHT / aspect if aspect else IMG_WIDTH
                            else:
                                draw_width = IMG_WIDTH
                                draw_height = IMG_WIDTH * aspect
                        except:
                            draw_width = IMG_WIDTH
                            draw_height = IMG_HEIGHT
                        
                        img = Image(temp_img.name, width=draw_width, height=draw_height)
                        img.hAlign = "CENTER"
                        numero_imagem = page_idx + idx + 1
                        texto_legenda = f"<b>Imagem {numero_imagem}</b>"
                        if descricao_imagem:
                            texto_legenda += f" - {_esc(descricao_imagem)}"
                        row.append([img, Spacer(1, 1*mm), Paragraph(texto_legenda, legenda_imagem_style)])
                        
                        # Cada linha tem 2 imagens
                        if len(row) == 2:
                            table_data.append(row)
                            row = []
                    except Exception as e:
                        print(f"Erro ao adicionar imagem {page_idx + idx}: {e}")
                        import traceback
                        traceback.print_exc()
                
                # Adicionar última linha se incompleta
                if row:
                    while len(row) < 2:
                        row.append("")
                    table_data.append(row)
                
                # Criar tabela com as imagens
                if table_data:
                    col_widths = [IMG_WIDTH + ESPACAMENTO, IMG_WIDTH + ESPACAMENTO]
                    styles = create_pdf_styles()
                    header_rows = [[Paragraph("IMAGENS", styles["SecaoTitulo"]), ""]]
                    if identificacao_imagens:
                        header_rows.append([Paragraph(identificacao_imagens, styles["Normal"]), ""])

                    # A tabela pode continuar na página seguinte quando as
                    # legendas ocupam mais espaço. Repete título e paciente
                    # junto às imagens que passarem para a próxima página.
                    img_table = Table(
                        header_rows + table_data,
                        colWidths=col_widths,
                        repeatRows=len(header_rows),
                    )
                    img_table.setStyle(TableStyle([
                        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('LEFTPADDING', (0, 0), (-1, -1), ESPACAMENTO),
                        ('RIGHTPADDING', (0, 0), (-1, -1), ESPACAMENTO),
                        ('TOPPADDING', (0, 0), (-1, -1), ESPACAMENTO),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), ESPACAMENTO),
                        ('SPAN', (0, 0), (-1, 0)),
                        ('BACKGROUND', (0, 0), (-1, 0), COR_PRIMARIA),
                        ('LEFTPADDING', (0, 0), (-1, 0), 6),
                        ('RIGHTPADDING', (0, 0), (-1, 0), 6),
                        ('TOPPADDING', (0, 0), (-1, 0), 4),
                        ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
                        *([('SPAN', (0, 1), (-1, 1))] if identificacao_imagens else []),
                    ]))
                    elements.append(img_table)
                    elements.append(Spacer(1, 3*mm))
        
        # Gerar PDF com rodapé em todas as páginas
        rodape_texto = texto_rodape or "Fort Cordis Cardiologia Veterinária | Fortaleza-CE"
        
        def add_footer(canvas_obj, doc):
            footer_todas_paginas(canvas_obj, doc, rodape_texto)
            if preview:
                # Canvas-only identity: preserve the clinical layout/page count
                # while making every extracted/printed page visibly unofficial.
                canvas_obj.saveState()
                canvas_obj.setFont("Helvetica-Bold", 8)
                canvas_obj.setFillColor(colors.HexColor("#9B1C31"))
                canvas_obj.drawCentredString(A4[0] / 2, A4[1] - 9 * mm, "PRÉVIA - NÃO EMITIDO")
                canvas_obj.restoreState()
        
        doc.build(elements, onFirstPage=add_footer, onLaterPages=add_footer)
        buffer.seek(0)
        return buffer.getvalue()
        
    finally:
        # Limpar arquivos temporários
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
            except Exception as e:
                print(f"Erro ao remover arquivo temporário {temp_file}: {e}")



def gerar_pdf_laudo_pressao(
    dados: Dict[str, Any],
    logomarca_bytes: bytes = None,
    assinatura_bytes: bytes = None,
    nome_veterinario: str = None,
    crmv: str = None,
    texto_rodape: str = None,
) -> bytes:
    """Gera PDF para laudo de pressao arterial."""
    temp_files = []

    def _to_int(value: Any) -> Optional[int]:
        try:
            if value is None or value == "":
                return None
            if isinstance(value, str):
                value = value.replace(",", ".").strip()
            return int(round(float(value)))
        except Exception:
            return None

    def _classificar_pas(pas_media: Optional[int]) -> str:
        if pas_media is None or pas_media <= 0:
            return "Sem classificacao (media indisponivel)."
        if pas_media <= 140:
            return "Normal (110 a 140 mmHg)"
        if pas_media <= 159:
            return "Levemente elevada (141 a 159 mmHg)"
        if pas_media <= 179:
            return "Moderadamente elevada (160 a 179 mmHg)"
        return "Severamente elevada (>=180 mmHg)"

    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=15 * mm,
            leftMargin=15 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
        )

        elements = []
        styles = create_pdf_styles()

        temp_logo_path = None
        temp_assinatura_path = None

        if logomarca_bytes:
            temp_logo = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_logo.write(logomarca_bytes)
            temp_logo.close()
            temp_logo_path = temp_logo.name
            temp_files.append(temp_logo_path)

        if assinatura_bytes:
            temp_ass = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_ass.write(assinatura_bytes)
            temp_ass.close()
            temp_assinatura_path = temp_ass.name
            temp_files.append(temp_assinatura_path)

        dados_pdf = dict(dados or {})
        pressao = dados_pdf.get("pressao_arterial") or {}

        pas_1 = _to_int(pressao.get("pas_1")) or 0
        pas_2 = _to_int(pressao.get("pas_2")) or 0
        pas_3 = _to_int(pressao.get("pas_3")) or 0
        valores = [v for v in [pas_1, pas_2, pas_3] if v > 0]
        pas_media = _to_int(pressao.get("pas_media"))
        if pas_media is None and valores:
            pas_media = int(round(sum(valores) / len(valores)))

        metodo = (pressao.get("metodo") or "Doppler").strip() or "Doppler"
        manguito = (pressao.get("manguito") or "").strip()
        membro = (pressao.get("membro") or "").strip()
        decubito = (pressao.get("decubito") or "").strip()
        obs_extra = (pressao.get("obs_extra") or "").strip()

        elements.extend(
            criar_cabecalho(
                dados_pdf,
                temp_logo_path,
                titulo_principal="LAUDO DE PRESSAO ARTERIAL",
                mostrar_linha_ritmo=False,
            )
        )

        elements.append(_bloco_sem_quebra(criar_titulo_secao("LAUDO PRESSAO ARTERIAL"), Spacer(1, 2 * mm)))

        afericoes_txt = "<br/>".join([
            f"1a afericao: Pressao Sistolica {pas_1} mmHg",
            f"2a afericao: Pressao Sistolica {pas_2} mmHg",
            f"3a afericao: Pressao Sistolica {pas_3} mmHg",
            f"<b>PA Sistolica Media: {pas_media or 0} mmHg</b>",
            f"Metodo: {metodo}",
        ])

        observacoes_proc = []
        if manguito:
            observacoes_proc.append(f"Manguito: {manguito}")
        if membro:
            observacoes_proc.append(f"Membro: {membro}")
        if decubito:
            observacoes_proc.append(f"Decubito: {decubito}")
        if not observacoes_proc:
            observacoes_proc.append("Sem observacoes de procedimento.")

        box_data = [
            [Paragraph("<b>Afericao de Pressao Arterial</b>", styles['Normal']), Paragraph("<b>Observacoes do Procedimento</b>", styles['Normal'])],
            [Paragraph(afericoes_txt, styles['Normal']), Paragraph("<br/>".join(_esc(v) for v in observacoes_proc), styles['Normal'])],
        ]
        box_table = Table(box_data, colWidths=[90 * mm, 90 * mm])
        box_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.7, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f3f4f6')),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        classificacao = dados_pdf.get("conclusao") or _classificar_pas(pas_media)
        bloco_pressao = [
            box_table,
            Spacer(1, 3 * mm),
            Paragraph(f"<b>Classificacao:</b> {_esc(classificacao)}", styles['Conclusao']),
        ]

        if obs_extra:
            bloco_pressao.extend([
                Spacer(1, 2 * mm),
                Paragraph(f"<b>Outras observacoes:</b> {_esc(obs_extra)}", styles['Normal']),
            ])

        bloco_pressao.append(Spacer(1, 4 * mm))
        elements.append(_bloco_sem_quebra(*bloco_pressao))

        refs = [
            "<b>Valores de Referencia (PAS)</b>",
            "Normal: 110 a 140 mmHg",
            "Levemente elevada: 141 a 159 mmHg",
            "Moderadamente elevada: 160 a 179 mmHg",
            "Severamente elevada: >=180 mmHg",
        ]
        ref_table = Table([[Paragraph("<br/>".join(refs), styles['Normal'])]], colWidths=[180 * mm])
        ref_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#15803d')),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(_bloco_sem_quebra(ref_table))

        elements.append(Spacer(1, 4 * mm))
        elements.append(
            Paragraph(
                "<i>* Os valores de pressao arterial devem ser correlacionados com o quadro clinico e reavaliados quando necessario.</i>",
                styles['Normal'],
            )
        )
        elements.append(Spacer(1, 1 * mm))
        elements.append(
            Paragraph(
                "<i>* A pressao foi aferida por metodo Doppler e pode apresentar variacao em relacao ao metodo invasivo.</i>",
                styles['Normal'],
            )
        )

        vet_nome = nome_veterinario or dados_pdf.get('veterinario_nome') or "Medico Veterinario"
        vet_crmv = crmv or dados_pdf.get('veterinario_crmv') or ""
        elements.extend(criar_secao_assinatura(vet_nome, vet_crmv, temp_assinatura_path))

        rodape_texto = texto_rodape or "Fort Cordis Cardiologia Veterinaria | Fortaleza-CE"

        def add_footer(canvas_obj, doc_obj):
            footer_todas_paginas(canvas_obj, doc_obj, rodape_texto)

        doc.build(elements, onFirstPage=add_footer, onLaterPages=add_footer)
        buffer.seek(0)
        return buffer.getvalue()
    finally:
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
            except Exception as e:
                print(f"Erro ao remover arquivo temporario {temp_file}: {e}")



# Mantém compatibilidade com código anterior
gerar_pdf_laudo = gerar_pdf_laudo_eco


def gerar_pdf_laudo_ultrassom_abdominal(
    dados: Dict[str, Any],
    logomarca_bytes: bytes = None,
    assinatura_bytes: bytes = None,
    nome_veterinario: str = None,
    crmv: str = None,
    texto_rodape: str = None,
) -> bytes:
    """Gera PDF para laudo de ultrassonografia abdominal."""
    temp_files = []
    orgaos_ordenados = [
        ("figado", "Figado"),
        ("vesicula_biliar", "Vesicula biliar"),
        ("estomago", "Estomago"),
        ("alcas_intestinais", "Alcas intestinais"),
        ("duodeno", "Duodeno"),
        ("colon", "Colon"),
        ("juncao_ileo_ceco_colica", "Juncao ileo-ceco-colica"),
        ("baco", "Baco"),
        ("rins", "Rins"),
        ("bexiga", "Bexiga"),
        ("pancreas", "Pancreas"),
        ("adrenais", "Adrenais"),
        ("prostata", "Prostata"),
        ("testiculos", "Testiculos"),
        ("utero", "Utero"),
        ("ovarios", "Ovarios"),
    ]

    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=15 * mm,
            leftMargin=15 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
        )

        elements = []
        styles = create_pdf_styles()

        temp_logo_path = None
        temp_assinatura_path = None

        if logomarca_bytes:
            temp_logo = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            temp_logo.write(logomarca_bytes)
            temp_logo.close()
            temp_logo_path = temp_logo.name
            temp_files.append(temp_logo_path)

        if assinatura_bytes:
            temp_ass = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            temp_ass.write(assinatura_bytes)
            temp_ass.close()
            temp_assinatura_path = temp_ass.name
            temp_files.append(temp_assinatura_path)

        dados_pdf = dict(dados or {})
        ultrassom = dados_pdf.get("ultrassonografia_abdominal") or {}
        qualitativa = ultrassom.get("qualitativa") or {}
        observacoes = (
            ultrassom.get("observacoes_gerais")
            or dados_pdf.get("observacoes")
            or ""
        ).strip()

        elements.extend(
            criar_cabecalho(
                dados_pdf,
                temp_logo_path,
                titulo_principal="LAUDO DE ULTRASSONOGRAFIA ABDOMINAL",
                mostrar_linha_ritmo=False,
            )
        )

        elements.append(
            _bloco_sem_quebra(
                criar_titulo_secao("AVALIACAO ULTRASSONOGRAFICA"),
                Spacer(1, 2 * mm),
            )
        )

        linhas = [
            [
                Paragraph("<b>Estrutura avaliada</b>", styles["Normal"]),
                Paragraph("<b>Descricao</b>", styles["Normal"]),
            ]
        ]

        for chave, label in orgaos_ordenados:
            texto = str(qualitativa.get(chave) or "").strip()
            if not texto:
                continue
            linhas.append(
                [
                    Paragraph(f"<b>{_esc(label)}</b>", styles["Normal"]),
                    Paragraph(_esc(texto).replace("\n", "<br/>"), styles["Normal"]),
                ]
            )

        if len(linhas) == 1:
            linhas.append(
                [
                    Paragraph("<b>Descricao</b>", styles["Normal"]),
                    Paragraph("Nenhum achado qualitativo informado.", styles["Normal"]),
                ]
            )

        tabela = Table(linhas, colWidths=[48 * mm, 132 * mm], repeatRows=1)
        tabela.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.7, colors.black),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        elements.append(tabela)

        if observacoes:
            elements.append(Spacer(1, 4 * mm))
            elements.append(criar_titulo_secao("OBSERVACOES GERAIS"))
            elements.append(Spacer(1, 2 * mm))
            elements.append(
                Paragraph(_esc(observacoes).replace("\n", "<br/>"), styles["Conclusao"])
            )

        elements.append(Spacer(1, 4 * mm))
        elements.append(
            Paragraph(
                "<i>Os achados ultrassonograficos devem ser interpretados em conjunto com o quadro clinico, exames laboratoriais e demais exames complementares.</i>",
                styles["Normal"],
            )
        )
        elements.append(Spacer(1, 1 * mm))
        elements.append(
            Paragraph(
                "<i>Este exame descreve as alteracoes identificadas ao metodo ultrassonografico no momento da avaliacao.</i>",
                styles["Normal"],
            )
        )

        vet_nome = nome_veterinario or dados_pdf.get("veterinario_nome") or "Medico Veterinario"
        vet_crmv = crmv or dados_pdf.get("veterinario_crmv") or ""
        elements.extend(criar_secao_assinatura(vet_nome, vet_crmv, temp_assinatura_path))

        imagens = dados_pdf.get("imagens", [])
        if imagens:
            elements.append(PageBreak())
            elements.append(criar_titulo_secao("IMAGENS"))
            elements.append(Spacer(1, 5 * mm))

            img_width_limite = 85 * mm
            img_height_limite = 70 * mm
            espacamento = 3 * mm

            for page_idx in range(0, len(imagens), 6):
                if page_idx > 0:
                    elements.append(PageBreak())
                    elements.append(criar_titulo_secao("IMAGENS"))
                    elements.append(Spacer(1, 5 * mm))

                page_imagens = imagens[page_idx : page_idx + 6]
                table_data = []
                row = []

                for idx, img_bytes in enumerate(page_imagens):
                    try:
                        if not img_bytes:
                            continue

                        temp_img = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                        temp_img.write(img_bytes)
                        temp_img.close()
                        temp_files.append(temp_img.name)

                        try:
                            img_reader = ImageReader(temp_img.name)
                            img_width, img_height = img_reader.getSize()
                            aspect = img_height / float(img_width) if img_width else 1
                            if aspect > (img_height_limite / img_width_limite):
                                draw_height = img_height_limite
                                draw_width = img_height_limite / aspect if aspect else img_width_limite
                            else:
                                draw_width = img_width_limite
                                draw_height = img_width_limite * aspect
                        except Exception:
                            draw_width = img_width_limite
                            draw_height = img_height_limite

                        row.append(Image(temp_img.name, width=draw_width, height=draw_height))
                        if len(row) == 2:
                            table_data.append(row)
                            row = []
                    except Exception as e:
                        print(f"Erro ao adicionar imagem {page_idx + idx}: {e}")

                if row:
                    while len(row) < 2:
                        row.append("")
                    table_data.append(row)

                if table_data:
                    img_table = Table(
                        table_data,
                        colWidths=[img_width_limite + espacamento, img_width_limite + espacamento],
                    )
                    img_table.setStyle(
                        TableStyle(
                            [
                                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                ("LEFTPADDING", (0, 0), (-1, -1), espacamento),
                                ("RIGHTPADDING", (0, 0), (-1, -1), espacamento),
                                ("TOPPADDING", (0, 0), (-1, -1), espacamento),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), espacamento),
                            ]
                        )
                    )
                    elements.append(img_table)
                    elements.append(Spacer(1, 3 * mm))

        rodape_texto = texto_rodape or "Fort Cordis Cardiologia Veterinaria | Fortaleza-CE"

        def add_footer(canvas_obj, doc_obj):
            footer_todas_paginas(canvas_obj, doc_obj, rodape_texto)

        doc.build(elements, onFirstPage=add_footer, onLaterPages=add_footer)
        buffer.seek(0)
        return buffer.getvalue()
    finally:
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
            except Exception as e:
                print(f"Erro ao remover arquivo temporario {temp_file}: {e}")

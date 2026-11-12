"""
Parser XML melhorado para exames de ecocardiograma.
Adiciona mais flexibilidade na busca de parâmetros e melhor logging.
"""
import re
from typing import Dict, Any, Optional
from bs4 import BeautifulSoup
from .xml_parser import buscar_velocidade_por_name
from .xml_outflow import extract_outflow_measurements

def _parse_data_iso(data_str: str) -> str:
    """Converte data do formato brasileiro (DD/MM/YYYY) ou americano (MM/DD/YYYY) para ISO (YYYY-MM-DD)."""
    if not data_str:
        return ""
    
    data_str = data_str.strip()
    
    # Se já está no formato ISO, retorna
    if re.match(r"^\d{4}-\d{2}-\d{2}$", data_str):
        return data_str
    
    # Tenta formato DD/MM/YYYY ou DD-MM-YYYY
    match = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", data_str)
    if match:
        dia, mes, ano = match.groups()
        return f"{ano}-{int(mes):02d}-{int(dia):02d}"
    
    # Tenta formato YYYY/MM/DD ou YYYY-MM-DD
    match = re.match(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$", data_str)
    if match:
        ano, mes, dia = match.groups()
        return f"{ano}-{int(mes):02d}-{int(dia):02d}"
    
    return data_str

def _parse_num(texto: str) -> Optional[float]:
    """Extrai o primeiro número decimal de uma string."""
    if not texto:
        return None
    s = str(texto).strip().lower()
    m = re.search(r"(\d+(?:[.,]\d+)?)", s)
    if not m:
        return None
    num = m.group(1).replace(",", ".")
    try:
        return float(num)
    except (ValueError, TypeError):
        return None


def _normalize_param_name(value: str) -> str:
    """Normaliza nomes de parametros para comparacao robusta."""
    txt = str(value or "").strip().lower()
    txt = (
        txt
        .replace("\u00b4", "'")
        .replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u00c2\u00b4", "'")
        .replace("`", "'")
        .replace("\u00e2\u20ac\u2122", "'")
        .replace("\u00e2\u20ac\u02dc", "'")
    )
    txt = (
        txt
        .replace("\u00e1", "a").replace("\u00e0", "a").replace("\u00e2", "a").replace("\u00e3", "a")
        .replace("\u00e9", "e").replace("\u00ea", "e")
        .replace("\u00ed", "i")
        .replace("\u00f3", "o").replace("\u00f4", "o").replace("\u00f5", "o")
        .replace("\u00fa", "u")
        .replace("\u00e7", "c")
        .replace("\u00c3\u00a1", "a").replace("\u00c3\u00a0", "a").replace("\u00c3\u00a2", "a").replace("\u00c3\u00a3", "a")
        .replace("\u00c3\u00a9", "e").replace("\u00c3\u00aa", "e")
        .replace("\u00c3\u00ad", "i")
        .replace("\u00c3\u00b3", "o").replace("\u00c3\u00b4", "o").replace("\u00c3\u00b5", "o")
        .replace("\u00c3\u00ba", "u")
        .replace("\u00c3\u00a7", "c")
    )
    # Algumas exportacoes trazem apostrofos quebrados como '?' (ex.: a? para a')
    txt = re.sub(r"^a[^0-9a-z]+$", "a'", txt)
    txt = re.sub(r"^e[^0-9a-z]+$", "e'", txt)
    txt = re.sub(r"\s+", " ", txt)
    return txt

def _find_text_ci(soup, tag_names):
    """Retorna o texto do primeiro tag encontrado (case-insensitive)."""
    for nm in tag_names:
        try:
            tag = soup.find(lambda t, nm=nm: getattr(t, 'name', None) and str(t.name).lower() == str(nm).lower())
        except Exception:
            tag = None
        if tag:
            txt = (tag.get_text() or "").strip()
            if txt:
                return txt
    return ""


def _capitalizar_nome(texto: str) -> str:
    """Normaliza nomes para iniciais maiusculas."""
    if not texto:
        return ""

    texto = re.sub(r"\s+", " ", str(texto).strip())

    def _cap_token(token: str) -> str:
        if not token:
            return token
        partes_apostrofo = token.split("'")
        partes_apostrofo = [
            p[:1].upper() + p[1:].lower() if p else p
            for p in partes_apostrofo
        ]
        return "'".join(partes_apostrofo)

    palavras = []
    for palavra in texto.split(" "):
        partes_hifen = palavra.split("-")
        partes_hifen = [_cap_token(parte) for parte in partes_hifen]
        palavras.append("-".join(partes_hifen))

    return " ".join(palavras)

def extrair_peso_kg(soup) -> Optional[float]:
    """Tenta encontrar peso no XML (converte lb->kg se necessário)."""
    candidatos_tags = {"weight", "patientweight", "patient_weight", "bodyweight", "bw"}
    
    tags = soup.find_all(True)
    for t in tags:
        if not getattr(t, "name", None):
            continue
        nome = t.name.lower()
        if nome in candidatos_tags:
            txt = (t.get_text() or "").strip()
            val = _parse_num(txt)
            if val is None:
                continue
            txt_l = txt.lower()
            unit_attr = (t.get("unit") or t.get("Unit") or "").lower()
            if "lb" in txt_l or "lb" in unit_attr:
                val = val / 2.20462
            return val

    candidatos_param = {
        "weight", "patient weight", "patientweight", "body weight", "bodyweight", "bw"
    }
    
    for p in soup.find_all("parameter"):
        name_attr = p.get("NAME") or p.get("Name") or p.get("name") or ""
        name_l = str(name_attr).strip().lower()
        if name_l in candidatos_param:
            node_val = p.find("aver") or p.find("val") or p.find("value")
            txt = (node_val.get_text() if node_val else p.get_text() or "").strip()
            val = _parse_num(txt)
            if val is None:
                continue
            txt_l = txt.lower()
            if "lb" in txt_l:
                val = val / 2.20462
            return val

    return None

def buscar_parametro_por_name(soup, possible_names: list, tipo_valor: str = "aver") -> Optional[float]:
    """Busca parametro por NAME e tambem por <measpar><name>."""
    name_lower = [_normalize_param_name(n) for n in possible_names]

    def _extrair_valor_e_unidade(container) -> tuple[Optional[float], str]:
        if tipo_valor == "aver":
            node_val = container.find("aver") or container.find("val") or container.find("value")
        else:
            node_val = container.find(tipo_valor) or container.find("aver") or container.find("val") or container.find("value")
        txt = (node_val.get_text() if node_val else container.get_text() or "").strip()
        val = _parse_num(txt)
        unit = ""
        unit_node = container.find("unit")
        if unit_node:
            unit = (unit_node.get_text() or "").strip().lower()
        return val, unit

    def _normalizar_unidade_comprimento(val: float, unit: str, matched_name_l: str) -> float:
        is_ratio = "/" in matched_name_l or "ratio" in matched_name_l
        is_comprimento = any(termo in matched_name_l for termo in [
            "div", "siv", "plv", "lvid", "lvpw", "ivs", "ao",
            "ap", "tapse", "mapse", "root", "diam", "atri", "ladmax", "ladmin"
        ]) or bool(re.search(r"(^|[\s/_\.-])(la|ae)([\s/_\.-]|$)", matched_name_l))
        is_comprimento = is_comprimento and not is_ratio

        if unit == "cm" and is_comprimento:
            return val * 10
        if not unit and val < 10 and is_comprimento and val > 0.5:
            return val * 10
        return val

    for p in soup.find_all("parameter"):
        name_attr = p.get("NAME") or p.get("Name") or p.get("name") or ""
        name_l = _normalize_param_name(name_attr)

        for measpar in p.find_all("measpar"):
            meas_name_node = measpar.find("name")
            meas_name = (meas_name_node.get_text() or "").strip() if meas_name_node else ""
            meas_name_l = _normalize_param_name(meas_name)
            if meas_name_l in name_lower:
                val, unit = _extrair_valor_e_unidade(measpar)
                if val is not None:
                    return _normalizar_unidade_comprimento(val, unit, meas_name_l)

        if name_l in name_lower:
            val, unit = _extrair_valor_e_unidade(p)
            if val is not None:
                return _normalizar_unidade_comprimento(val, unit, name_l)

    for measpar in soup.find_all("measpar"):
        meas_name_node = measpar.find("name")
        meas_name = (meas_name_node.get_text() or "").strip() if meas_name_node else ""
        meas_name_l = _normalize_param_name(meas_name)
        if meas_name_l in name_lower:
            val, unit = _extrair_valor_e_unidade(measpar)
            if val is not None:
                return _normalizar_unidade_comprimento(val, unit, meas_name_l)

    return None

def buscar_parametro_flexivel(soup, nomes_possiveis: list, debug: bool = False) -> Optional[float]:
    """
    Busca um parÃ¢metro de forma flexÃ­vel, tentando vÃ¡rias variaÃ§Ãµes de nome.
    TambÃ©m busca em tags <measurement> e <value> alternativos.
    """
    # Primeiro tenta a busca padrÃ£o
    val = buscar_parametro_por_name(soup, nomes_possiveis)
    if val is not None:
        return val
    
    nomes_norm = [_normalize_param_name(n) for n in nomes_possiveis]

    # Se nÃ£o encontrou, tenta buscar por padrÃµes no texto
    for p in soup.find_all("parameter"):
        name_attr = p.get("NAME") or p.get("Name") or p.get("name") or ""
        name_l = _normalize_param_name(name_attr)
        meas_name_node = p.find("name")
        meas_name = (meas_name_node.get_text() or "").strip() if meas_name_node else ""
        meas_name_l = _normalize_param_name(meas_name)
        candidatos_nome = [x for x in [name_l, meas_name_l] if x]
        
        # Verifica se algum dos nomes possÃ­veis estÃ¡ contido no nome do parÃ¢metro
        for nome_busca_l in nomes_norm:
            # Remove prefixos comuns para comparar
            nome_limpo = re.sub(r'^(2d/|mm/|mm_|2d_)', '', nome_busca_l)
            for nome_param in candidatos_nome:
                if nome_limpo in nome_param or nome_param in nome_busca_l:
                    node_val = p.find("aver") or p.find("val") or p.find("value")
                    txt = (node_val.get_text() if node_val else p.get_text() or "").strip()
                    val = _parse_num(txt)
                    if val is not None:
                        if debug:
                            origem = meas_name if meas_name else name_attr
                            print(f"[XML_PARSER] Encontrado '{origem}' = {val}")
                        return val
    
    return None

def _vmax_from_maxpg(maxpg: Optional[float]) -> Optional[float]:
    """
    Converte gradiente maximo (mmHg) para velocidade maxima (m/s)
    usando a equacao simplificada de Bernoulli: deltaP = 4 * v^2.
    """
    if maxpg is None or maxpg <= 0:
        return None
    return (maxpg / 4.0) ** 0.5

def debug_listar_parametros(soup):
    """Lista todos os parâmetros encontrados no XML para debug."""
    print("[XML_PARSER DEBUG] === TODOS OS PARÂMETROS ENCONTRADOS ===")
    count = 0
    parametros_modo_m = []
    
    for p in soup.find_all("parameter"):
        name_attr = p.get("NAME") or p.get("Name") or p.get("name") or ""
        node_val = p.find("aver") or p.find("val") or p.find("value")
        txt = (node_val.get_text() if node_val else p.get_text() or "").strip()
        unit_node = p.find("unit")
        unit = (unit_node.get_text() if unit_node else "").strip()
        
        if name_attr:
            print(f"  NAME='{name_attr}' VALUE='{txt}' UNIT='{unit}'")
            count += 1
            
            # Coletar parâmetros do modo M
            name_l = name_attr.lower()
            if any(x in name_l for x in ['ivsd', 'lvidd', 'lvpwd', 'ivss', 'lvids', 'lvpws', 'mm/', 'mm_']):
                parametros_modo_m.append({
                    'name': name_attr,
                    'value': txt,
                    'unit': unit
                })
    
    print(f"\n[XML_PARSER DEBUG] === PARÂMETROS DO MODO M ({len(parametros_modo_m)} encontrados) ===")
    for p in parametros_modo_m:
        print(f"  {p['name']}: {p['value']} {p['unit']}")
    
    print(f"\n[XML_PARSER DEBUG] === FIM DOS PARÂMETROS ({count} total) ===")


def parse_xml_eco(xml_content: bytes) -> Dict[str, Any]:
    """
    Parse XML de ecocardiograma e retorna dados estruturados.
    Versão melhorada com mais flexibilidade na busca de parâmetros.
    """
    try:
        soup = BeautifulSoup(xml_content, 'xml')
    except Exception:
        try:
            soup = BeautifulSoup(xml_content, 'lxml')
        except Exception:
            soup = BeautifulSoup(xml_content, 'html.parser')
    
    dados = {
        "paciente": {},
        "medidas": {},
        "clinica": "",
        "veterinario_solicitante": "",
    }
    
    # Debug: listar todos os parâmetros do XML
    debug_listar_parametros(soup)
    
    # ============== DADOS DO PACIENTE ==============
    
    # Nome do tutor e paciente (formato Vivid IQ: "SOBRENOME, NOME RACA")
    raw_last = _find_text_ci(soup, ['lastName']) or ""
    raw_first = _find_text_ci(soup, ['firstName']) or ""
    
    tutor = ""
    nome_animal = ""
    raca = ""
    
    if not raw_first and "," in raw_last:
        # Formato: "Sobrenome Tutor, Nome Animal Raca"
        parts = raw_last.split(",", 1)
        tutor = parts[0].strip()
        rest = parts[1].strip()
        if " " in rest:
            # Pega a última palavra como raça, o resto como nome
            words = rest.rsplit(" ", 1)
            nome_animal = words[0].strip()
            raca = words[1].strip() if len(words) > 1 else ""
        else:
            nome_animal = rest
    else:
        tutor = raw_last.strip()
        if " " in raw_first:
            words = raw_first.rsplit(" ", 1)
            nome_animal = words[0].strip()
            raca = words[1].strip() if len(words) > 1 else ""
        else:
            nome_animal = raw_first.strip()
    
    # Espécie
    especie = _find_text_ci(soup, ['Species']) or ""
    if not especie:
        cat = _find_text_ci(soup, ["Category", "category"]) or ""
        cat = cat.strip().upper()
        if cat == "C":
            especie = "Canina"
        elif cat == "F":
            especie = "Felina"
    
    # Normaliza espécie
    if especie:
        especie_lower = especie.lower()
        if "fel" in especie_lower or "gato" in especie_lower or "cat" in especie_lower:
            especie = "Felina"
        elif "can" in especie_lower or "cao" in especie_lower or "cão" in especie_lower or "dog" in especie_lower:
            especie = "Canina"
    
    # Peso
    peso_xml = extrair_peso_kg(soup)
    peso = f"{peso_xml:.2f}".rstrip("0").rstrip(".") if peso_xml else ""
    
    # Data do exame
    data_exame_raw = _find_text_ci(soup, [
        "StudyDate", "ExamDate", "ExamDateTime", "ExamDateTimeUTC", "StudyDateUTC", "date"
    ])
    data_exame = _parse_data_iso(data_exame_raw)
    
    # Idade
    idade = _find_text_ci(soup, ["age", "Age", "PatientAge"])
    
    # Telefone
    telefone = _find_text_ci(soup, ["phone", "Phone", "Telephone"])
    
    # Clínica / Instituição
    clinica = _find_text_ci(soup, ["freeTextAddress", "InstitutionName", "institutionname"])
    
    # Frequência cardíaca
    fc = _find_text_ci(soup, ["HeartRate", "heartRate", "heart_rate"])
    
    # Sexo
    sexo = ""
    tag_sex = soup.find('Sex') or soup.find('sex')
    if tag_sex:
        sexo_text = tag_sex.text.lower() if hasattr(tag_sex, 'text') else str(tag_sex).lower()
        if "f" in sexo_text or "fem" in sexo_text:
            sexo = "Fêmea"
        elif "m" in sexo_text:
            sexo = "Macho"
    
    # Data de nascimento
    nascimento = _find_text_ci(soup, ["birthdate", "BirthDate", "Birthdate", "PatientBirthDate"])
    
    # ============== DADOS DO PACIENTE ==============
    dados["paciente"] = {
        "nome": _capitalizar_nome(nome_animal),
        "tutor": _capitalizar_nome(tutor),
        "raca": _capitalizar_nome(raca),
        "especie": especie or "Canina",
        "peso": peso,
        "idade": idade,
        "sexo": sexo,
        "telefone": telefone,
        "data_exame": data_exame,
        "nascimento": nascimento,
    }
    
    # ============== MEDIDAS ECOCARDIOGRÁFICAS ==============
    
    medidas = {}
    
    # --- Medidas 2D ---
    # Ao Root Diam -> Aorta
    val = buscar_parametro_por_name(soup, ["2D/Ao Root Diam", "Ao Root Diam", "Ao Root", "AO ROOT", "Ao"])
    if val: medidas["Aorta"] = val
    
    # Ao (nível AP) - mesma medida mas pode ter nome diferente
    val = buscar_parametro_por_name(
        soup,
        ["Ao", "Aorta", "AO", "Ao AP", "Ao nivel AP", "Ao no nivel AP", "2D/Ao AP"],
    )
    if val: medidas["Ao_nivel_AP"] = val
    
    # LA (Left Atrium / AE) -> Átrio esquerdo
    val = buscar_parametro_por_name(soup, ["2D/LA", "LA", "Left Atrium", "D. AE", "AE", "Atrium"])
    if val:
        # Fallback defensivo para XMLs onde LA/AE vem em cm e não foi detectado pela regra geral.
        medidas["Atrio_esquerdo"] = val * 10 if 0 < val < 5 else val
    
    # LA/Ao Ratio -> AE/Ao
    val = buscar_parametro_flexivel(soup, ["2D/LA/Ao", "LA/Ao", "LA/AO", "AE/Ao", "AE/AO"])
    if val: medidas["AE_Ao"] = val
    for key, names in (
        ("AE_diametro_max", ["LADmax", "LAD max", "LA Diameter max", "AE Diametro max"]),
        ("AE_diametro_min", ["LADmin", "LAD min", "LA Diameter min", "AE Diametro min"]),
    ):
        val = buscar_parametro_por_name(soup, names)
        if val: medidas[key] = val
    val = buscar_velocidade_por_name(soup, ["LAA Vmax", "LAA peak", "LAapp peak"])
    if val: medidas["Fluxo_auricular"] = val
    val = buscar_parametro_por_name(soup, ["LA FS", "LAFS", "AE FS"])
    if val: medidas["Fracao_encurtamento_AE"] = val
    
    # AP (Artéria pulmonar)
    val = buscar_parametro_flexivel(
        soup,
        [
            "PA",
            "AP",
            "PA Diam",
            "AP Diam",
            "PA Diameter",
            "Pulmonary Artery",
            "Pulmonary Artery Diam",
            "Main PA",
            "MPA",
            "Arteria Pulmonar",
            "2D/PA",
            "2D/AP",
        ],
    )
    if val: medidas["AP"] = val
    
    # AP/Ao
    val = buscar_parametro_flexivel(
        soup,
        [
            "PA/Ao",
            "AP/Ao",
            "PA/AO",
            "AP/AO",
            "PA_Ao",
            "AP_Ao",
            "2D/PA/Ao",
            "2D/AP/Ao",
            "Pulmonary Artery/Aorta",
        ],
    )
    if val: medidas["AP_Ao"] = val
    
    # --- Medidas M-Mode (MM) e 2D ---
    # VERSÃO MELHORADA: Mais variações de nomes para capturar modo M
    
    lv_fields = (
        ("SIVd", "SIVd_2D", ["MM/IVSd", "MM_IVSd", "MM IVSd", "IVSd (MM)", "IVSd MM"], ["2D/IVSd"], ["IVSd", "SIVd", "Septum d", "Septal Wall d"]),
        ("DIVEd", "DIVEd_2D", ["MM/LVIDd", "MM_LVIDd", "MM LVIDd", "LVIDd (MM)", "LVIDd MM"], ["2D/LVIDd"], ["LVIDd", "DIVEd", "LV d", "Left Ventricle d"]),
        ("PLVEd", "PLVEd_2D", ["MM/LVPWd", "MM_LVPWd", "MM LVPWd", "LVPWd (MM)", "LVPWd MM"], ["2D/LVPWd"], ["LVPWd", "PPVEd", "PLVEd", "PW d", "Posterior Wall d"]),
        ("SIVs", "SIVs_2D", ["MM/IVSs", "MM_IVSs", "MM IVSs", "IVSs (MM)", "IVSs MM"], ["2D/IVSs"], ["IVSs", "SIVs", "Septum s", "Septal Wall s"]),
        ("DIVES", "DIVES_2D", ["MM/LVIDs", "MM_LVIDs", "MM LVIDs", "LVIDs (MM)", "LVIDs MM"], ["2D/LVIDs"], ["LVIDs", "DIVEs", "DIVÉs", "LV s", "Left Ventricle s"]),
        ("PLVES", "PLVES_2D", ["MM/LVPWs", "MM_LVPWs", "MM LVPWs", "LVPWs (MM)", "LVPWs MM"], ["2D/LVPWs"], ["LVPWs", "PPVEs", "PLVÉs", "PW s", "Posterior Wall s"]),
    )
    for m_key, two_d_key, m_names, two_d_names, generic_names in lv_fields:
        m_value = buscar_parametro_por_name(soup, m_names)
        two_d_value = buscar_parametro_por_name(soup, two_d_names)
        if m_value is not None:
            medidas[m_key] = m_value
        if two_d_value is not None:
            medidas[two_d_key] = two_d_value
        if m_value is None and two_d_value is None:
            generic_value = buscar_parametro_flexivel(soup, generic_names)
            if generic_value is not None:
                medidas[m_key] = generic_value
    
    # Volumes -> VDF (Teicholz)
    val = buscar_parametro_flexivel(soup, ["2D/EDV(Teich)", "MM/EDV(Teich)", "EDV(Teich)", "VDF(Teich)", "EDV", "VDF"])
    if val: medidas["VDF"] = val
    
    val = buscar_parametro_flexivel(soup, ["2D/ESV(Teich)", "MM/ESV(Teich)", "ESV(Teich)", "VSF(Teich)", "ESV", "VSF"])
    if val: medidas["VSF"] = val
    
    val = buscar_parametro_flexivel(soup, ["2D/SV(Teich)", "MM/SV(Teich)", "SV(Teich)", "SV"])
    if val: medidas["SV"] = val
    
    # Função -> FE (Teicholz)
    val = buscar_parametro_flexivel(soup, ["2D/EF(Teich)", "MM/EF(Teich)", "EF(Teich)", "EF", "FE(Teich)", "FE"])
    if val: medidas["FE_Teicholz"] = val
    
    # %FS -> Delta D / %FS
    val = buscar_parametro_flexivel(soup, ["2D/%FS", "MM/%FS", "%FS", "Delta D", "FS", "Fractional Shortening"])
    if val: medidas["DeltaD_FS"] = val
    
    # RWT
    val = buscar_parametro_flexivel(soup, ["2D/LVPW RWTd", "MM/LVPW RWTd", "RWTd", "RWT"])
    if val: medidas["RWT"] = val
    
    # DIVdN (normalizado) -> DIVEd normalizado
    val = buscar_parametro_por_name(soup, ["2D/LVIDdN"])
    if val: medidas["DIVEd_normalizado_2D"] = val
    val = buscar_parametro_flexivel(soup, ["DIVdN", "LVIDdN", "DIVEdN"])
    if val: medidas["DIVEd_normalizado"] = val
    
    # TAPSE
    val = buscar_parametro_flexivel(soup, ["MM/TAPSE", "2D/TAPSE", "TAPSE"])
    if val: medidas["TAPSE"] = val

    # MAPSE
    val = buscar_parametro_flexivel(soup, ["MM/MAPSE", "2D/MAPSE", "MAPSE"])
    if val: medidas["MAPSE"] = val
    
    # --- Medidas Doppler (PW) ---
    # Mitral Valve -> Diastólica
    val = buscar_parametro_flexivel(soup, ["MV E Velocity", "Veloc. E VM", "MVE", "E Velocity", "Onda E"])
    if val: medidas["Onda_E"] = val
    
    val = buscar_parametro_flexivel(soup, ["MV A Velocity", "Veloc. A VM", "MVA", "A Velocity", "Onda A"])
    if val: medidas["Onda_A"] = val
    
    val = buscar_parametro_flexivel(soup, ["MV E/A Ratio", "E/A VM", "E/A Ratio", "MV_E_A", "E/A"])
    if val: medidas["E_A"] = val

    val = buscar_parametro_flexivel(soup, ["MV E/TRIV Ratio", "E/TRIV", "E/IVRT", "E_TRIV"])
    if val: medidas["E_TRIV"] = val
    
    val = buscar_parametro_flexivel(soup, ["MV Dec Time", "T.Des. VM", "Dec Time", "MV_DT", "TD"])
    if val: medidas["TD"] = val
    
    val = buscar_parametro_flexivel(soup, ["MV Dec Slope", "Rampa Des.VM", "Dec Slope", "MV_Slope"])
    if val: medidas["MV_Slope"] = val
    
    # E' (E prime) -> e' Doppler tecidual
    val = buscar_parametro_flexivel(
        soup,
        ["MV Eprime Velocity", "E'", "Eprime Velocity", "Eprime", "e'", "TDI e", "TDI_e", "MV e'"],
    )
    if val: medidas["e_doppler"] = val
    
    # a' -> a' Doppler tecidual
    val = buscar_parametro_flexivel(
        soup,
        ["a'", "a`", "Aprime Velocity", "Aprime", "TDI a", "TDI_a", "MV a'"],
    )
    if val: medidas["a_doppler"] = val
    
    # E/E' -> E/E'
    val = buscar_parametro_flexivel(soup, ["MV E/Eprime Ratio/Calc", "E/E'", "EEp"])
    if val: medidas["E_E_linha"] = val
    
    # IVRT -> TRIV
    val = buscar_parametro_flexivel(soup, ["IVRT", "TRIV"])
    if val: medidas["TRIV"] = val
    
    # MR dp/dt
    val = buscar_parametro_flexivel(soup, ["MR dp/dt", "Mitral Regurg dp/dt", "MR dpdt"])
    if val: medidas["MR_dp_dt"] = val
    
    # Cada local de aquisicao exige seu proprio rotulo; nao inferir VSVD como pulmonar.
    medidas.update(extract_outflow_measurements(soup))
    
    # --- Medidas de regurgitacao (Continuous Wave) ---
    # Preferir Vmax real. Se nao existir, usar maxPG convertido para Vmax.
    mr_vmax = buscar_parametro_flexivel(
        soup,
        ["MR Vmax", "Mitral Regurg Vmax", "MR Vmax P", "Vmax RM", "IM Vmax"],
    )
    if mr_vmax is None:
        mr_maxpg = buscar_parametro_flexivel(
            soup,
            ["MR maxPG", "Mitral Regurg maxPG", "MR max PG", "maxPG RM", "Gradiente RM"],
        )
        mr_vmax = _vmax_from_maxpg(mr_maxpg)
    if mr_vmax is not None:
        medidas["IM_Vmax"] = mr_vmax
        medidas["IM_Grad"] = round(4 * (mr_vmax ** 2), 2)
    
    # TR (Tricuspid Regurgitation) -> IT (insuficiencia tricuspide) Vmax
    tr_vmax = buscar_parametro_flexivel(
        soup,
        ["TR Vmax", "Tricuspid Regurg Vmax", "TR Vmax P", "Vmax IT", "IT Vmax"],
    )
    if tr_vmax is None:
        tr_maxpg = buscar_parametro_flexivel(
            soup,
            ["TR maxPG", "Tricuspid Regurg maxPG", "TR max PG", "maxPG IT", "Gradiente IT"],
        )
        tr_vmax = _vmax_from_maxpg(tr_maxpg)
    if tr_vmax is not None:
        medidas["IT_Vmax"] = tr_vmax
        medidas["IT_Grad"] = round(4 * (tr_vmax ** 2), 2)
    
    # AR (Aortic Regurgitation) -> IA (insuficiencia aortica) Vmax
    ar_vmax = buscar_parametro_flexivel(
        soup,
        ["AR Vmax", "Aortic Regurg Vmax", "AR Vmax P", "Vmax IA", "IA Vmax"],
    )
    if ar_vmax is None:
        ar_maxpg = buscar_parametro_flexivel(
            soup,
            ["AR maxPG", "Aortic Regurg maxPG", "AR max PG", "maxPG IA", "Gradiente IA"],
        )
        ar_vmax = _vmax_from_maxpg(ar_maxpg)
    if ar_vmax is not None:
        medidas["IA_Vmax"] = ar_vmax
        medidas["IA_Grad"] = round(4 * (ar_vmax ** 2), 2)
    
    # PR (Pulmonic Regurgitation) -> IP (insuficiencia pulmonar) Vmax
    pr_vmax = buscar_parametro_flexivel(
        soup,
        ["PR Vmax", "Pulmonic Regurg Vmax", "PR Vmax P", "Vmax IP", "IP Vmax"],
    )
    if pr_vmax is None:
        pr_maxpg = buscar_parametro_flexivel(
            soup,
            ["PR maxPG", "Pulmonic Regurg maxPG", "PR max PG", "maxPG IP", "Gradiente IP"],
        )
        pr_vmax = _vmax_from_maxpg(pr_maxpg)
    if pr_vmax is not None:
        medidas["IP_Vmax"] = pr_vmax
        medidas["IP_Grad"] = round(4 * (pr_vmax ** 2), 2)
    
    # TDI_e_a ratio -> Doppler tecidual (Relação e'/a')
    if "e_doppler" in medidas and "a_doppler" in medidas and medidas["a_doppler"] > 0:
        medidas["doppler_tecidual_relacao"] = medidas["e_doppler"] / medidas["a_doppler"]
    
    dados["medidas"] = medidas
    dados["clinica"] = clinica.strip()
    dados["veterinario_solicitante"] = ""
    dados["fc"] = fc
    
    # Outros dados do exame
    dados["institution"] = _find_text_ci(soup, ["InstitutionName"])
    dados["operator"] = _find_text_ci(soup, ["operator", "operatorName", "OperatorName"])
    dados["study_id"] = _find_text_ci(soup, ["studyId", "StudyId"])
    dados["accession_number"] = _find_text_ci(soup, ["AccessionNumber"])
    
    # Log das medidas extraídas (apenas para debug)
    print(f"\n[XML_PARSER] Total de medidas extraídas: {len(medidas)}")
    
    # Log específico para medidas do modo M
    medidas_modo_m = {k: v for k, v in medidas.items() if k in ['SIVd', 'DIVEd', 'PLVEd', 'SIVs', 'DIVES', 'PLVES']}
    if medidas_modo_m:
        print(f"[XML_PARSER] Medidas do Modo M: {medidas_modo_m}")
    else:
        print("[XML_PARSER] ⚠️ NENHUMA MEDIDA DO MODO M ENCONTRADA!")
    
    return dados

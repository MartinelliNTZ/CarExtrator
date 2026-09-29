r"""
extrair_car_pdf.py
=============================================================================

Script que processa TODOS os PDFs de "Recibo de Inscrição do Imóvel Rural
no CAR" na pasta deste arquivo e, se BUSCAR_SUBPASTAS = True, nas subpastas.

FUNCIONA COM RECIBOS DE QUALQUER UF (GO, PR, PI, MT, MS, etc.) porque o
recibo nacional do CAR tem o mesmo layout em todos os estados.

O que ele faz, em ordem:
  0. Usa o nome da subpasta como OS, se habilitado, ou pede a OS no terminal;
  1. Descobre sozinho a pasta onde está, via os.path (__file__);
  2. Procura todos os arquivos "*.pdf", incluindo subpastas conforme a constante;
  3. Extrai os dados de cada CAR (imóvel, áreas, proprietário, matrículas,
     datas, coordenadas, protocolo, etc.);
  4. Monta / atualiza o JSON "car_dados.json" usando COMO CHAVE sempre o
     número do registro do CAR:
       - chave NÃO existe -> INSERE o registro;
       - chave JÁ existe  -> ATUALIZA o registro e, antes de sobrescrever,
         gera uma CÓPIA do JSON na pasta de backup criada dentro do TEMP
         do Windows: %TEMP%\car_backup;
  5. Monta / atualiza o CSV "car_dados.csv" (mesma base do JSON: o número
     de linhas do CSV excluindo o cabeçalho é igual ao número de chaves do
     JSON);
  6. No final imprime o resumo com nº de inserções, nº de atualizações e a
     lista numerada de PDFs que deram falha.

DEPENDÊNCIA (instalar uma única vez):
    python -m pip install pypdf

EXECUÇÃO:
    python extrair_car_pdf.py
=============================================================================
"""

import csv
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import warnings
from datetime import datetime
from pathlib import Path

# Suprime o aviso 'fontTools is required...' do pypdf (é só ruído, não é erro)
logging.getLogger("pypdf").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message="fontTools is required")

# Permite imprimir na consola Windows qualquer nome de arquivo (acentos/combinados)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from pypdf import PdfReader                     # leitor recomendado
except Exception:                                          # noqa: E722
    try:
        from PyPDF2 import PdfReader
    except Exception:                                      # noqa: E722
        sys.exit("Faltou a biblioteca pypdf.\nInstale com:  python -m pip install pypdf")


# =====================================================================
# 1) LOCALIZAÇÃO AUTOMÁTICA DA PASTA (os.path) + caminhos dos arquivos
# =====================================================================
BUSCAR_SUBPASTAS = True  # True: inclui subpastas; False: somente a pasta do script.
USAR_NOME_SUBPASTA_COMO_OS = True  # Com busca em subpastas, usa a pasta que contém o PDF.
PASTA_SCRIPT = Path(os.path.dirname(os.path.abspath(__file__)))
JSON_CAMINHO = PASTA_SCRIPT / "car_dados.json"          # JSON gerado / atualizado
CSV_CAMINHO = PASTA_SCRIPT / "car_dados.csv"            # CSV gerado / atualizado
PASTA_BACKUP = Path(tempfile.gettempdir()) / "car_backup"  # backup no TEMP do PC


# =====================================================================
# 2) FUNÇÕES AUXILIARES
# =====================================================================
def agora_iso() -> str:
    """Data/hora atual em formato texto (AAAA-MM-DD HH:MM:SS)."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _limpar_ligaduras(texto: str) -> str:
    """Corrige ligaduras (fi/fl) que o pypdf extrai como caractere NUL ('\\x00').

    Nos Demonstrativos 'gov' (Sicar/car.gov.br, layout 2024) as ligaduras
    tipográficas saem como '\\x00'. Exemplos reais observados:
      'para os \\x00ns'         -> 'para os fins'
      'noti\\x00cação'          -> 'notificação'
      'Reti\\x00cação'          -> 'Retificação'
      'Módulos \\x00scais'      -> 'Módulos Fiscais'
      'Geográ\\x00cas'          -> 'Geográficas'
      'exploração \\x00orestal' -> 'exploração florestal'
    """
    txt = texto.replace("\x00", "fi")
    # A ligadura pode ser 'fl' (caso 'florestal'); a troca genérica acima a tornaria
    # 'fiorestal', portanto corrige o par conhecido.
    txt = txt.replace("fiorestal", "florestal").replace("fioresta", "floresta")
    return txt


def extrair_texto_pdf(caminho: Path) -> str:
    """Extrai o texto de todas as páginas do PDF."""
    with caminho.open("rb") as fh:
        leitor = PdfReader(fh)
        paginas = [pagina.extract_text() or "" for pagina in leitor.pages]
    texto = "\n".join(paginas)
    if not texto.strip():
        raise RuntimeError("PDF sem camada de texto (parece ser imagem escaneada)")
    return _limpar_ligaduras(texto)


def _parece_codigo(token: str) -> bool:
    """True se o token parece código de livro/folha (não parte do município)."""
    if re.fullmatch(r"[\d.,\-/]+", token):
        return True                                   # numérico / "---" / 2-J
    if len(token) <= 3 and token.isupper():
        return True                                   # abreviação tipo "SF"
    return False
def extrair_matriculas(texto: str):
    """Extrai as linhas da tabela 'Matrículas das Propriedades do Imóvel'.

    Robusto diante de:
      - várias matrículas por CAR (GO/PR);
      - cabeçalho quebrado em várias linhas (PI);
      - município partido entre 2 linhas (PI: 'Ribeiro' + 'Gonçalves/PI');
      - número composto ('41; R-51, R-52, R-60');
      - livro/folha nos formatos '2 112', '02 01', 'Ficha 02 ---', '002 SF'.
    """
    m = re.search(
        r"(?:MATRÍCULAS DAS PROPRIEDADES DO IMÓVEL|Número da Matrícula)",
        texto,
        re.IGNORECASE,
    )
    if not m:
        return []
    sec = texto[m.end():]
    sec = re.split(r"\nRECIBO|\nCAR -|\nPágina", sec)[0]

    # Um 'bloco' começa numa linha com data dd/mm/aaaa e pode continuar nas
    # linhas seguintes (ex.: município quebrado). O restante (pedaços do
    # cabeçalho, linhas vazias) é ignorado.
    blocos = []
    buf = ""
    for linha in sec.splitlines():
        linha = linha.strip()
        if not linha:
            continue
        if re.search(r"\d{1,2}/\d{1,2}/\d{4}", linha):
            if buf:
                blocos.append(buf)
            buf = linha
        elif "/" in linha and re.search(r"/[A-Z]{2}", linha):
            buf = f"{buf} {linha}".strip()            # continuação do município
    if buf:
        blocos.append(buf)

    matriculas = []
    for bloco in blocos:
        tokens = bloco.split()
        idx_data = next(
            (i for i, t in enumerate(tokens)
             if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", t)),
            None,
        )
        if idx_data is None:
            continue
        numero = " ".join(tokens[:idx_data])
        data = tokens[idx_data]
        resto = tokens[idx_data + 1:]

        # --- Município = última(s) palavra(s) até achar código (livro/folha) --
        mun_tokens = []
        while resto and not _parece_codigo(resto[-1]):
            mun_tokens.insert(0, resto.pop())
        municipio = " ".join(mun_tokens)

        # --- Folha = último token numérico (ou '---'); Livro = o restante -----
        folha = ""
        if resto and (re.fullmatch(r"[\d.,]+", resto[-1]) or resto[-1] == "---"):
            folha = resto.pop()
        livro = " ".join(resto)

        matriculas.append({
            "numero": numero,
            "data_documento": data,
            "livro": livro,
            "folha": folha,
            "municipio": municipio,
        })
    return matriculas


# CAMPOS DE ÁREA com o padrão de texto no recibo
_CAMPOS_AREA = [
    ("area_consolidada_ha",              r"Área Consolidada\s+([\d.,]+)"),
    ("remanescente_vegetacao_nativa_ha", r"Remanescente de Vegetação Nativa\s+([\d.,]+)"),
    ("area_reserva_legal_ha",            r"Área de Reserva Legal\s+([\d.,]+)"),
    ("area_total_imovel_ha",             r"Área Total do Imóvel\s+([\d.,]+)"),
    ("area_servidao_administrativa_ha",  r"Área de Servidão Administrativa\s+([\d.,]+)"),
    ("area_liquida_imovel_ha",           r"Área Líquida do Imóvel\s+([\d.,]+)"),
    ("area_app_ha",                      r"Área de Preservação Permanente\s+([\d.,]+)"),
    ("area_uso_restrito_ha",             r"Área de Uso Restrito\s+([\d.,]+)"),
]
# =====================================================================
# 3) EXTRAÇÃO DOS DADOS DO CAR A PARTIR DO TEXTO DO PDF
# =====================================================================
# Existen DOS formatos de documento CAR:
#   A) 'RECIBO DE INSCRIÇÃO'      -> recibo nacional (GO/PR/PI/MT/...);
#   B) 'DEMONSTRATIVO' (SICAR)     -> consulta pública, sin nombre de imóvel
#      en el texto (solo en el nombre del archivo).
def es_documento_car(texto: str) -> bool:
    """True se o PDF parece um documento de CAR (Recibo, Demonstrativo ou
    Certificado estadual).

    Falso para certificados de matrícula do cartório, certidões, plantas,
    mapas, etc. que podem estar na mesma pasta.
    """
    if re.search(r"Registro no CAR|Registro de Inscrição no CAR", texto):
        return True
    if "Cobertura do Solo" in texto or "Dados do Imóvel" in texto:
        return True
    if re.search(r"Demonstrativo da Situação das Informações Declaradas", texto):
        return True
    if "Certificado de Inscrição Número" in texto or "CADASTRO AMBIENTAL RURAL DO" in texto:
        return True
    if "ÁREAS DO IMÓVEL" in texto and "RESPONSÁVEIS" in texto.upper():
        return True
    # Recibo de Inscrição CAR estadual (SIMCAR/MT e estados com mesmo layout)
    if "Nº Recibo Federal" in texto or "Recibo de Inscrição CAR" in texto:
        return True
    return False


def _nome_imovel_de_archivo(caminho_pdf: Path) -> str:
    """Deriva el nombre del imóvel del nombre del archivo, si es posible.

    Ejemplos:
      01_FAZENDA ARIZONA.pdf              -> FAZENDA ARIZONA
      02_01_FAZENDA TROPICAL.pdf           -> FAZENDA TROPICAL
      02_02_SEDE TROPICAL.pdf              -> SEDE TROPICAL
      03_02_FAZENDA PONTE DE PEDRA.pdf     -> FAZENDA PONTE DE PEDRA
    Si el archivo sólo contiene un código (ej.: "Demonstrativo_MS-5005806-..."),
    devuelve '' (no se debe usar el código como nombre de imóvel).
    """
    nome = caminho_pdf.stem
    # Quita prefijos numéricos tipo "01_", "02_01-", "3 - "
    nome = re.sub(r"^\s*\d+(?:[._\-]\s*\d+)*\s*[._\-]\s*", "", nome).strip()
    # Quita prefijos genéricos: "Demonstrativo_", "Recibo", "Certificado",
    # "CAR -", "RECIBO-CAR_", "CAR2SIMCAR", etc. Aplicado em laços porque um
    # nome pode combinar vários prefixos (ex.: "RECIBO-CAR_ITAGUASSU.pdf").
    for _ in range(3):
        nome = re.sub(
            r"(?i)^(demonstrativo|recibo|certificado|comprovante|consulta|car|simcar)"
            r"\s*[_\-\s]+\s*",
            "",
            nome,
        ).strip()
    nome = re.sub(r"(?i)\s*[-_]?\s*CAR\s*$", "", nome).strip()
    # Se o resultado parece código (ex.: "MS-5005806-E038..." ou "PI-2208908-...").
    # Detecta antes da normalização códigos "UF-dígitos"; depois da normalização
    # rejeita apenas strings tipo identificador (dígitos/separadores), mantendo
    # nomes alfabéticos válidos (ex.: "CRISTO REI", "ITAGUASSU", "OURO E PRATA").
    if re.search(r"\b[A-Z]{2}[-_]\d{5,}\b", nome):
        return ""
    nombre = re.sub(r"[_\-\s]+", " ", nome).strip()
    if re.fullmatch(r"[A-Z0-9._\-]{8,}", nombre) and re.search(r"[\d._\-]", nombre):
        return ""
    # Fallback adicional: ainda parece código (número com muitos dígitos)
    if re.search(r"\b[A-Z]{2}\s+\d{5,}\b", nombre) or re.search(r"\d{6,}", nombre):
        return ""
    return nombre


def extrair_dados_demonstrativo(
    texto: str, caminho_pdf: Path, numero_os: str = ""
) -> dict:
    """Extrae datos de un PDF tipo 'Demonstrativo del CAR' (consulta SICAR)."""
    dados = {
        "arquivo_pdf": caminho_pdf.name,
        "path_pdf": str(caminho_pdf),
        "numero_os": numero_os,
        "tipo_documento": "Demonstrativo CAR",
    }

    m = re.search(
        r"Registro (?:no|de Inscrição no) CAR:\s*\n?\s*([A-Z]{2}-\d+-[A-Za-z0-9]+)",
        texto,
    )
    if not m:
        raise RuntimeError("não encontrei o número do 'Registro no CAR' no PDF")
    dados["numero_do_car"] = m.group(1)

    dados["nome_imovel"] = _nome_imovel_de_archivo(caminho_pdf)

    # Município/UF: formatos possíveis:
    #   antigo: "Município: Nioaque Unidade da Federação: MS" (mesma linha) ou
    #           "Município: Barra do Bugres" + "Unidade da Federação: MT";
    #   gov   : "Município / UF: Nova Olímpia (MT)"  (Demonstrativo Sicar 2024).
    m = re.search(
        r"Município\s*/\s*UF:\s*([^\n(]+?)\s*\(\s*([A-Z]{2})\s*\)", texto
    )
    if m:
        dados["municipio"] = m.group(1).strip()
        dados["uf"] = m.group(2)
    else:
        m = re.search(r"Município:\s*([^\n]+?)\s+Unidade da Federação:", texto)
        if m:
            dados["municipio"] = m.group(1).strip()
        else:
            m = re.search(r"Município:\s*([^\n]+)", texto)
            dados["municipio"] = m.group(1).strip() if m else ""
    if not dados.get("uf", ""):
        m = re.search(r"Unidade da Federação:\s*([A-Z]{2})", texto)
        dados["uf"] = m.group(1) if m else ""

    # Latitude/Longitude: formatos possíveis:
    #   antigo: "Latitude: ... Longitude: ..." (mesma linha) ou em linhas separadas;
    #   gov   : "Centróide: Lat: 14°43'52,13\" S" + "Long: 57°13'10,89\" O".
    m = re.search(r"Centróide:\s*Lat:\s*([^\n]+?)\s*Long:\s*([^\n]+)", texto)
    if m:
        dados["latitude"] = m.group(1).strip()
        dados["longitude"] = m.group(2).strip()
    else:
        m = re.search(r"Latitude:\s*(.+?)\s+Longitude:\s*([^\n]+)", texto)
        if m:
            dados["latitude"] = m.group(1).strip()
            dados["longitude"] = m.group(2).strip()
        else:
            m = re.search(r"Latitude:\s*([^\n]+)", texto)
            dados["latitude"] = m.group(1).strip() if m else ""
            m = re.search(r"Longitude:\s*([^\n]+)", texto)
            dados["longitude"] = m.group(1).strip() if m else ""

    m = re.search(r"Área do Imóvel(?: Rural)?\s*:?\s*(?:ha\s*)?\s*([\d.,]+)", texto)
    area_imovel = m.group(1) if m else ""
    dados["area_total_imovel_ha"] = area_imovel
    dados["area_total_ha"] = area_imovel                # alias útil

    m = re.search(r"Módulos Fiscais:\s*([\d.,]+)", texto, re.IGNORECASE)
    dados["modulos_fiscais"] = m.group(1) if m else ""

    dados["codigo_protocolo"] = ""

    m = re.search(
        r"(?:Data de Cadastro|Data da Inscrição):\s*\n?\s*(\d{1,2}/\d{1,2}/\d{4}(?:\s+\d{2}:\d{2})?)",
        texto,
    )
    dados["data_cadastro"] = m.group(1) if m else ""
    m = re.search(
        r"Data da [UuúÚ]ltima [Rr]etifica[çc][ãa]o:\s*\n?\s*(\d{1,2}/\d{1,2}/\d{4}(?:\s+\d{2}:\d{2})?)",
        texto,
    )
    dados["data_ultima_retificacao"] = m.group(1) if m else ""

    # Situação do Cadastro. No Demonstrativo "gov" (Sicar 2024) o rótulo
    # "Situação do Cadastro:" vem SEM valor na linha; em seguida aparece o
    # "Registro de Inscrição no CAR: ..." (bug de layout do site car.gov.br).
    # A situação real ("Ativo") fica no topo do documento, logo após
    # "Regularização Ambiental - Cadastro Ambiental Rural".
    sit = _campo_linea(texto, r"Situa[çc][ãa]o(?: do Cadastro)?:\s*([^\n]+)")
    if not sit or sit.startswith("Registro de Inscrição no CAR:"):
        m = re.search(
            r"Regulariza[çc][ãa]o Ambiental\s*-\s*Cadastro Ambiental Rural\s*\n"
            r"\s*([^\n]+?)\s*\n\s*Dados do Imóvel Rural",
            texto,
        )
        if m:
            sit = m.group(1).strip()
    dados["situacao"] = sit
    dados["condicion"] = _campo_linea(texto, r"Condi[çc][ãa]o(?: Externa)?:\s*([^\n]+)")
    dados["data_analise_car"] = _campo_linea(texto, r"Data da an[áa]lise do CAR:\s*([^\n]+)")
    dados["aderiu_pra"] = _campo_linea(
        texto, r"Aderiu ao Programa de Regulariza[çc][ãa]o Ambiental:\s*([^\n]+)"
    )
    dados["condicion_pra"] = _campo_linea(texto, r"Condi[çc][ãa]o do PRA:\s*([^\n]+)")

    # ---- Cobertura do Solo / Reserva Legal / APP / Uso Restrito ----
    # (rótulos variam conforme o estado/ano do documento)
    dados["area_consolidada_ha"] = _valor_tras_label(
        texto,
        "Área total de Uso Consolidado",
        "Área Rural Consolidada",
    )
    dados["remanescente_vegetacao_nativa_ha"] = _valor_tras_label(
        texto,
        "Área total de Remanescentes de Vegetação Nativa",
        "Área de Remanescente de Vegetação Nativa",
    )
    dados["area_reserva_legal_ha"] = _valor_tras_label(
        texto,
        "Total de Reserva Legal Declarada pelo Proprietário/Possuidor",
        "Total de Reserva Legal declarada pelo proprietário/possuidor",
    )
    dados["area_servidao_administrativa_ha"] = _valor_tras_label(
        texto,
        "Área total de Servidão Administrativa",
        "Área de Servidão Administrativa",
    )
    dados["area_app_ha"] = _valor_tras_label(
        texto, "Áreas de Preservação Permanente", "APP"
    )
    dados["area_uso_restrito_ha"] = _valor_tras_label(
        texto,
        "Áreas de Uso Restrito",
        "Área de Uso Restrito",
        "Área de uso restrito",            # layout gov (Sicar 2024)
    )
    dados["area_liquida_imovel_ha"] = area_imovel

    dados["proprietarios"] = []
    dados["cnpj"] = ""
    dados["cpf"] = ""
    dados["nome_proprietario"] = ""

    dados["matriculas"] = []

    dados["informacoes_adicionais"] = ""
    dados["area_documentacao_ha"] = ""
    dados["area_grafica_ha"] = ""
    dados["diferenca_detectada"] = "Não"
    # ---- Campos novos (padrão de nomenclatura MS e de receitas modernas) ----
    # Só são preenchidos quando o rótulo existir no texto do Demonstrativo;
    # nos demais estados/formatos ficam vazios (compatibilidade total).
    dados["area_total_documentada_ha"] = _valor_tras_label(
        texto,
        "Área Total Documentada do Imóvel (ha)",
        "Área Total Documentada do Imóvil (ha)",
    )
    dados["area_reserva_legal_exigida_ha"] = _valor_tras_label(
        texto,
        "Área de Reserva Legal Exigida (ha)",
        "Área de Reserva Legal Exigível (ha)",
    )
    dados["area_reserva_legal_existente_ha"] = _valor_tras_label(
        texto,
        "Área de Reserva Legal Existente (ha)",
        "Área de Reserva Legal Averbada (ha)",
        "Área de Reserva Legal Averbada",    # layout gov (Sicar 2024)
    )
    dados["area_reserva_legal_proposta_ha"] = _valor_tras_label(
        texto,
        "Área Proposta para Reserva Legal (ha)",
        "Área de Reserva Legal Proposta (ha)",
        "Área de Reserva Legal Proposta",    # layout gov (Sicar 2024)
    )
    dados["area_reserva_legal_condominio_ha"] = _valor_tras_label(
        texto,
        "Área de Reserva Legal em Condomínio (ha)",
        "Área de Reserva Legal em Condomínio",
    )
    # Reserva Legal efetiva: prioriza a Existente, depois a Proposta, depois a
    # Exigida — mesma regra usada no Certificado estadual (nomenclatura MS).
    if not dados.get("area_reserva_legal_ha", ""):
        dados["area_reserva_legal_ha"] = (
            dados["area_reserva_legal_existente_ha"]
            if dados["area_reserva_legal_existente_ha"] not in ("", "-")
            else dados["area_reserva_legal_proposta_ha"]
            if dados["area_reserva_legal_proposta_ha"] not in ("", "-")
            else dados["area_reserva_legal_exigida_ha"]
        )
    for campo_novo in (
        "area_total_documentada_ha", "area_reserva_legal_exigida_ha",
        "area_reserva_legal_existente_ha", "area_reserva_legal_proposta_ha",
        "area_reserva_legal_condominio_ha",
    ):
        dados.setdefault(campo_novo, "")
    return _normalizar_campos(dados)


def _separar_propriedade_uf_municipio(bloco: str, numero_car: str):
    """Separa a tabela SIMCAR usando a UF do CAR, em uma ou várias linhas."""
    uf = numero_car[:2].upper()
    ufs = {
        "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA",
        "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN",
        "RS", "RO", "RR", "SC", "SP", "SE", "TO",
    }
    if uf not in ufs:
        return None
    texto = " ".join(bloco.split())
    # A última ocorrência da UF separa as colunas, preservando nomes que
    # contêm DE, DA, IX ou até a própria sigla do estado.
    m = re.fullmatch(r"(.+)\s+(" + re.escape(uf) + r")\s+(.+)", texto)
    return m.groups() if m else None


def extrair_dados_recibo_simcar_mt(
    texto: str, caminho_pdf: Path, numero_os: str = ""
) -> dict:
    """Extrai dados de um 'Recibo de Inscrição CAR – MT' (SIMCAR/SEMA-MT).

    Formato estadual (ex.: MT) com painéis: Proprietários, Dados Gerais
    (Nº CAR Estadual / Nº Recibo Federal), Dados da Propriedade, Dados das
    Áreas dos Imóveis Rurais e Croqui do CAR (ATP/AIR/APP/AVN/AUAS).

    A chave usada é o Nº Recibo Federal (padrão nacional, igual ao dos
    recibos/demonstrativos do JSON), ex.: MT-5104609-7E05220B6A7D4050B7F263C55261086F.
    """
    txt = texto.replace("Âº", "º").replace("–", "-")
    dados = {
        "arquivo_pdf": caminho_pdf.name,
        "path_pdf": str(caminho_pdf),
        "numero_os": numero_os,
        "tipo_documento": "Recibo de Inscrição CAR-estadual (SIMCAR)",
    }

    # ---------- Chave: Nº Recibo Federal. Fallback: Nº CAR Estadual ----------
    m = re.search(
        r"N[º°]\s*Recibo Federal\s*\n?\s*([A-Z]{2}-\d+-[A-Za-z0-9]+)", txt
    )
    if not m:
        m = re.search(r"N[º°]\s*CAR Estadual\s*\n?\s*([A-Z]{2}\d+/\d{4})", txt)
    if not m:
        raise RuntimeError(
            "não encontrei o 'Nº Recibo Federal'/'Nº CAR Estadual' do SIMCAR"
        )
    dados["numero_do_car"] = m.group(1)

    m_uf = re.search(r"Recibo de Inscrição\s+CAR\s*-\s*([A-Z]{2})", txt)
    dados["uf"] = m_uf.group(1) if m_uf else ""

    # ---------- Nome da propriedade (multilinha) / UF / município ------------
    # O bloco termina em "Quadro Geral de Áreas" (recibo 2) OU "Dados das Áreas
    # dos Imóveis Rurais" (recibo 1).
    m = re.search(
        r"Dados da Propriedade\s*\n(.*?)\n\s*"
        r"(?:Quadro Geral de Áreas|Dados das Áreas dos Imóveis Rurais)",
        txt,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        linhas = [l.strip() for l in m.group(1).splitlines() if l.strip()]
        if linhas and re.match(r"(?i)^propriedade\s+uf\s+munic", linhas[0]):
            linhas.pop(0)                       # remove o cabeçalho da tabela
        if linhas:
            propriedade = _separar_propriedade_uf_municipio(
                " ".join(linhas), dados["numero_do_car"]
            )
            if propriedade:
                dados["nome_imovel"], dados["uf"], dados["municipio"] = propriedade
            else:
                dados["nome_imovel"] = " ".join(" ".join(linhas).split())
    else:
        dados["nome_imovel"] = _nome_imovel_de_archivo(caminho_pdf)
    dados.setdefault("nome_imovel", "")
    dados.setdefault("municipio", "")

    # ---------- Dados Gerais: nº estadual, situação, datas -------------------
    dados["numero_car_estadual"] = ""
    dados["data_situacao"] = ""
    dados["situacao"] = ""
    dados["data_cadastro"] = ""
    m = re.search(
        r"\n\s*([A-Z]{2}\d+/\d{4})\s+(.+?)\s+(\d{1,2}/\d{1,2}/\d{4})\s+"
        r"(\d{1,2}/\d{1,2}/\d{4})\s*\n",
        txt,
    )
    if m:
        dados["numero_car_estadual"] = m.group(1)
        dados["situacao"] = m.group(2).strip()
        dados["data_cadastro"] = m.group(3)
        dados["data_situacao"] = m.group(4)
    else:
        m = re.search(r"N[º°]\s*CAR Estadual\s*\n?\s*([A-Z]{2}\d+/\d{4})", txt)
        if m:
            dados["numero_car_estadual"] = m.group(1)

    # ---------- Proprietários (nome/razão social + CPF/CNPJ) -----------------
    proprietarios = []
    m = re.search(
        r"Propriet[áa]rios\s*\n(?:Nome/Raz[ãa]o Social\s+CPF/CNPJ\s*\n)?"
        r"(.*?)\n\s*Dados Gerais",
        txt,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        bloco = m.group(1)
        for mm in re.finditer(
            r"((?:\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})|(?:\d{3}\.\d{3}\.\d{3}-\d{2}))",
            bloco,
        ):
            numero = mm.group(1)
            ini_linha = bloco.rfind("\n", 0, mm.start()) + 1
            fim_linha = bloco.find("\n", mm.end())
            if fim_linha == -1:
                fim_linha = len(bloco)
            nome = bloco[ini_linha:mm.start()].strip()
            if not nome:                       # número em linha própria
                prev = bloco[:ini_linha].rstrip("\n")
                if prev:
                    nome = prev[prev.rfind("\n") + 1:].strip()
            nome = " ".join(nome.split())
            if nome:
                proprietarios.append({
                    "tipo": "CNPJ" if "/" in numero else "CPF",
                    "numero": numero,
                    "nome": nome,
                })
    dados["proprietarios"] = proprietarios
    dados["cnpj"] = "; ".join(p["numero"] for p in proprietarios if p["tipo"] == "CNPJ")
    dados["cpf"] = "; ".join(p["numero"] for p in proprietarios if p["tipo"] == "CPF")
    dados["nome_proprietario"] = " | ".join(p["nome"] for p in proprietarios)

    # ---------- Áreas (legenda do croqui OU quadro geral de áreas) ------------
    # Rótulos usados com OU sem o prefixo da legenda (ex.: "ATP - ", "AIR - ",
    # "APP - ", "AVN - ", "AUAS - "); a busca pelo texto base cobre os dois.
    area_total = (
        _valor_tras_label(txt, "Área do Imóvel Rural (Matrícula/Posse)")
        or _valor_tras_label(txt, "Área Total da Propriedade")
    )
    dados["area_total_imovel_ha"] = area_total
    dados["area_total_ha"] = area_total
    dados["area_total_documentada_ha"] = ""
    dados["remanescente_vegetacao_nativa_ha"] = _valor_tras_label(
        txt, "Área de Vegetação Nativa"
    )
    dados["area_app_ha"] = _valor_tras_label(
        txt, "Área de Preservação Permanente"
    )
    dados["area_consolidada_ha"] = _valor_tras_label(txt, "Área Consolidada")
    dados["area_liquida_imovel_ha"] = area_total
    auas = _valor_tras_label(txt, "Área de Uso Antropizado do Solo")
    area_rl_nativa = _valor_tras_label(txt, "Área de Reserva Legal Nativa")

    for campo in (
        "area_reserva_legal_ha", "area_reserva_legal_exigida_ha",
        "area_reserva_legal_existente_ha", "area_reserva_legal_proposta_ha",
        "area_reserva_legal_condominio_ha", "area_servidao_administrativa_ha",
        "area_uso_restrito_ha", "modulos_fiscais", "codigo_protocolo",
        "condicion", "condicion_pra", "data_analise_car",
        "data_ultima_retificacao", "area_documentacao_ha", "area_grafica_ha",
        "latitude", "longitude", "diferenca_detectada",
    ):
        dados[campo] = ""
    # Reserva Legal Nativa (ARLN no croqui / quadro geral do SIMCAR)
    if area_rl_nativa:
        dados["area_reserva_legal_ha"] = area_rl_nativa

    # ---------- Matrículas (tabela 'Dados das Áreas dos Imóveis Rurais') -----
    matriculas = []
    areas_por_matricula = []
    m = re.search(
        r"Dados das Áreas dos Imóveis Rurais\s*\n"
        r"(?:Identificação\s+Tipo\s+Área \(ha\)\s*\n)?"
        r"(.*?)(?=\n\s*Adesão|\Z)",
        txt,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        for linha in m.group(1).splitlines():
            mm = re.match(
                r"^\s*([\d.\-]+)\s+([A-Za-zÀ-ÿ]+)\s+([\d.,]+)\s*$", linha
            )
            if mm:
                matriculas.append({
                    "numero": mm.group(1),
                    "data_documento": "",
                    "livro": "",
                    "folha": "",
                    "municipio": dados.get("municipio", ""),
                })
                areas_por_matricula.append(
                    f"Matrícula {mm.group(1)}: {mm.group(3)} ha"
                )
    dados["matriculas"] = matriculas

    # ---------- Informações adicionais específicas do SIMCAR -----------------
    extras = []
    if dados.get("numero_car_estadual"):
        extras.append(f"CAR Estadual (SIMCAR): {dados['numero_car_estadual']}")
    if dados.get("data_situacao"):
        extras.append(f"Data da Situação: {dados['data_situacao']}")
    if auas:
        extras.append(f"AUAS - Área de Uso Antropizado do Solo: {auas} ha")
    if areas_por_matricula:
        extras.append("Áreas por matrícula: " + "; ".join(areas_por_matricula))
    dados["informacoes_adicionais"] = " | ".join(extras)

    # O recibo SIMCAR declara formalmente a adesão ao PRA no cabeçalho.
    dados["aderiu_pra"] = "Sim"
    return _normalizar_campos(dados)


def extrair_dados_demonstrativo_simcar_mt(
    texto: str, caminho_pdf: Path, numero_os: str = ""
) -> dict:
    """Lê o Demonstrativo de Informações no CAR da SEMA-MT."""
    dados = extrair_dados_recibo_simcar_mt(texto, caminho_pdf, numero_os)
    txt = texto.replace("–", "-").replace("—", "-")
    dados["tipo_documento"] = "Demonstrativo CAR-estadual (SIMCAR)"
    # O demonstrativo não declara adesão ao PRA como o recibo.
    dados["aderiu_pra"] = ""
    propriedade = re.search(
        r"Propriedade\s+UF\s+Município\s*\n(.*?)\n\s*Proprietários",
        txt, re.DOTALL,
    )
    if propriedade:
        campos = _separar_propriedade_uf_municipio(
            propriedade.group(1), dados["numero_do_car"]
        )
        if campos:
            dados["nome_imovel"], dados["uf"], dados["municipio"] = campos
    m = re.search(r"\n([A-Z]{2}\d+/\d{4})\s+([^\n]+)", txt)
    if m:
        dados["numero_car_estadual"] = m.group(1)
        dados["situacao"] = m.group(2).rsplit(" ", 1)[0]
    m = re.search(
        r"Data de Cadastro\s+Data da Situação\s*\n"
        r"(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})", txt,
    )
    if m:
        dados["data_cadastro"], dados["data_situacao"] = m.groups()
    m = re.search(r"Proprietários\s*\nNome\s*\n(.*?)\nÁreas da Propriedade",
                  txt, re.DOTALL)
    if m:
        nomes = [nome.strip() for nome in m.group(1).splitlines() if nome.strip()]
        dados["proprietarios"] = [
            {"nome": nome, "tipo": "", "numero": ""} for nome in nomes
        ]
        dados["nome_proprietario"] = " | ".join(nomes)
    area_total = _valor_tras_label(txt, "Área do Imóvel Rural - AIR")
    if not area_total:
        area_total = _valor_tras_label(txt, "Área Total da Propriedade - ATP")
    for campo in ("area_total_ha", "area_total_imovel_ha", "area_liquida_imovel_ha"):
        dados[campo] = area_total
    dados["area_consolidada_ha"] = _valor_tras_label(txt, "Área de Uso Consolidado")
    dados["remanescente_vegetacao_nativa_ha"] = _valor_tras_label(
        txt, "Área de Vegetação Nativa Preservada - AVNP")
    dados["area_app_ha"] = _valor_tras_label(
        txt, "Área de Preservação Permamente - APP",
        "Área de Preservação Permanente - APP")
    dados["area_reserva_legal_ha"] = _valor_tras_label(
        txt, "Área de Reserva Legal Preservada - ARLP")
    dados["area_reserva_legal_existente_ha"] = dados["area_reserva_legal_ha"]
    return _normalizar_campos(dados)


def _campo_linea(texto: str, padrao: str) -> str:
    m = re.search(padrao, texto)
    return m.group(1).strip() if m else ""


def _valor_tras_label(texto: str, *labels) -> str:
    """Captura o valor associado a um rótulo de tabela (SICAR/Certificado).

    O valor pode vir na MESMA linha ("APP 67.4895") ou na linha seguinte
    ("Área total de Uso Consolidado\\n828,1250"), com ou sem o sufixo "ha".
    Vários rótulos alternativos podem ser passados (variações por estado).

    ATENÇÃO: não usa \\b no final do rótulo, pois rótulos terminados em ")",
    como "...(ha)", quebrariam o boundary. O rótulo é procurado como texto
    literal (re.escape) seguido do valor. O valor capturado deve conter ao
    menos um DÍGITO (evita casar vírgulas/pontos soltos de frases).
    """
    for label in labels:
        m = re.search(
            re.escape(label)
            + r"\s*:?\s*(?:ha\s*)?(\d[\d.,\-]*|[\d.,\-]*\d)",
            texto,
            re.IGNORECASE,
        )
        if m:
            return m.group(1)
    return ""


def _normalizar_campos(dados: dict) -> dict:
    """Converte todos os campos de área (xx_ha) e módulos fiscais ao formato
    pt-BR consistente (coma decimal + ponto de milhar).

    Os recibos nacionais usam "3.566,6698" (coma decimal); os Demonstrativos
    MS/estatales modernos usan "2734.3871" ou "67.4895" (punto decimal). Isso
    garante que Excel (locale pt-BR) lea todos igual, sin convertir puntos en
    millares (""27.343.871"" erróneo).
    """
    def _num_pt(valor: str) -> str:
        if not valor:
            return ""
        s = str(valor).strip().replace("ha", "").replace(" ", "")
        if s in ("", "-", "--"):
            return ""
        # Detecta si usa coma (pt) o punto (en) como separador decimal
        try:
            if "," in s:
                numero = float(s.replace(".", "").replace(",", "."))
            else:
                numero = float(s)
        except ValueError:
            return str(valor).strip()
        # Formato pt-BR: 1234567.8912 -> 1.234.567,8912
        entero, decimal = f"{numero:.4f}".split(".")
        entero = re.sub(r"\B(?=(\d{3})+(?!\d))", ".", entero)
        return f"{entero},{decimal}"

    for chave in list(dados.keys()):
        if chave.endswith("_ha") or chave == "modulos_fiscais":
            dados[chave] = _num_pt(dados[chave])
    return dados


def _dms_a_decimal(valor: str):
    """Convierte una coordenada DMS ('21°08'04,79\" S', '-21º 8' 4,79\"') a
    grados decimales (float). Devuelve None si no se reconoce."""
    if not valor:
        return None
    s = str(valor).strip().replace("Â", "")
    m = re.match(
        r"([-+]?\d{1,3})[°º]\s*(\d{1,2})['’´]?\s*([\d.,]+)?\s*\"?\s*([NSEWO])?",
        s,
        re.IGNORECASE,
    )
    if not m:
        return None
    grados = float(m.group(1))
    minutos = float(m.group(2) or 0) / 60.0
    segs_txt = (m.group(3) or "0").replace(",", ".").replace("º", "")
    try:
        segundos = float(segs_txt) / 3600.0
    except ValueError:
        segundos = 0.0
    hemi = (m.group(4) or "").upper()
    if hemi in ("S", "W", "O") or m.group(1).startswith("-"):
        return -(abs(grados) + minutos + segundos)
    return grados + minutos + segundos


def _enriquecer_area_mesmo_imovel(base: dict) -> dict:
    """Para registros do tipo 'Demonstrativo CAR', preenche as áreas a partir de
    um registro irmão do MESMO imóvel (mesmo centróide lat/long), normalmente um
    'Certificado de Inscrição' estadual (MS) com os dados reais do cadastro.

    Contexto: o Demonstrativo do SICAR federal traz as áreas declaradas que, para
    imóveis ainda não analisados, costumam vir zeradas ou incompletas (ex.: "0.0"
    em Remanescente, APP, RL), enquanto o Certificado estadual traz os valores
    efetivos (nomenclatura '... (ha)' do IMASUL). Copiar os campos quando o irmão
    tiver valor informado mantém o registro do Demonstrativo consistente com o
    Certificado, sem afetar recibos de outros estados (que não são Demonstrativos)
    nem Demonstrativos sem um Certificado irmão (ficam inalterados).
    """
    _CAMPOS_IRMAO = (
        "area_total_documentada_ha", "area_total_imovel_ha", "area_total_ha",
        "remanescente_vegetacao_nativa_ha", "area_app_ha",
        "area_reserva_legal_exigida_ha", "area_reserva_legal_existente_ha",
        "area_reserva_legal_proposta_ha", "area_reserva_legal_condominio_ha",
        "area_reserva_legal_ha",
    )
    claves = list(base.keys())
    for k in claves:
        v = base[k]
        if v.get("tipo_documento") != "Demonstrativo CAR":
            continue
        lat = _dms_a_decimal(v.get("latitude", ""))
        lon = _dms_a_decimal(v.get("longitude", ""))
        if lat is None or lon is None:
            continue
        irmao = None
        for k2 in claves:
            if k2 == k:
                continue
            v2 = base[k2]
            if v2.get("tipo_documento") == "Demonstrativo CAR":
                continue
            lat2 = _dms_a_decimal(v2.get("latitude", ""))
            lon2 = _dms_a_decimal(v2.get("longitude", ""))
            if lat2 is None or lon2 is None:
                continue
            if abs(lat - lat2) < 0.001 and abs(lon - lon2) < 0.001:
                irmao = v2
                break
        if irmao is None:
            continue
        for campo in _CAMPOS_IRMAO:
            valor_irmao = irmao.get(campo, "")
            if valor_irmao and valor_irmao not in ("0,0000", "0.0000", "0"):
                v[campo] = valor_irmao
    return base


def _enriquecer_nombres(base: dict) -> dict:
    """Preenche o nome_imovel de registros que não o têm (ex.: Demonstrativo
    SICAR, que não leva nome) usando outro registro do MEMSO imóvel detectado
    pelo centróide (mesmo par lat/long).
    """
    claves = list(base.keys())
    for k in claves:
        v = base[k]
        if v.get("nome_imovel"):
            continue
        lat = _dms_a_decimal(v.get("latitude", ""))
        lon = _dms_a_decimal(v.get("longitude", ""))
        if lat is None or lon is None:
            continue
        for k2 in claves:
            if k2 == k:
                continue
            v2 = base[k2]
            if not v2.get("nome_imovel"):
                continue
            lat2 = _dms_a_decimal(v2.get("latitude", ""))
            lon2 = _dms_a_decimal(v2.get("longitude", ""))
            if lat2 is None or lon2 is None:
                continue
            if abs(lat - lat2) < 0.001 and abs(lon - lon2) < 0.001:
                v["nome_imovel"] = v2["nome_imovel"]
                break
    return base


def extrair_dados_certificado_ms(
    texto: str, caminho_pdf: Path, numero_os: str = ""
) -> dict:
    """Extrai dados de um 'Certificado de Inscrição' do CAR estadual (ex.: MS).

    Formato: 'Certificado de Inscrição Número: CARMS0005308' / 'CADASTRO
    AMBIENTAL RURAL DO MATO GROSSO DO SUL', com painéis DADOS GERAIS,
    ÁREAS DO IMÓVEL, RESPONSÁVEIS e CADASTRANTE.
    """
    txt = texto.replace("Âº", "º")      # normaliza graus mal extraídos
    dados = {
        "arquivo_pdf": caminho_pdf.name,
        "path_pdf": str(caminho_pdf),
        "numero_os": numero_os,
        "tipo_documento": "Certificado de Inscrição CAR-estadual",
    }

    m = re.search(r"Certificado de Inscrição N[uú]mero:\s*([A-Z0-9]+)", txt)
    if not m:
        raise RuntimeError("não encontrei o número do certificado de inscrição")
    dados["numero_do_car"] = m.group(1)
    m_uf = re.search(r"CAR([A-Z]{2})\d", dados["numero_do_car"])
    dados["uf"] = m_uf.group(1) if m_uf else ""

    # DADOS GERAIS: nome / centróide / municípios vêm logo após o cabeçalho
    m = re.search(r"DADOS GERAIS\s*\n([^\n]+)", txt, re.IGNORECASE)
    dados["nome_imovel"] = m.group(1).strip() if m else _nome_imovel_de_archivo(
        caminho_pdf
    )

    dados["municipio"] = ""
    m = re.search(r"DADOS GERAIS\s*\n[^\n]+\n[^\n]+\n([^\n]+)", txt, re.IGNORECASE)
    if m:
        dados["municipio"] = m.group(1).strip()

    dados["latitude"] = ""
    dados["longitude"] = ""
    # Formato do certificado MS: "-21º 8' 4,79\", -56º 11' 21,44\""
    coords = re.findall(r"-?\d{1,2}[°º]\s*\d{1,2}'\s*[\d.,]+\"?", txt)
    if len(coords) >= 2:
        dados["latitude"] = coords[0].strip()
        dados["longitude"] = coords[1].strip()
    else:
        # fallback: linha com "Latitude:/Longitude:" (recibo nacional)
        m = re.search(r"Latitude:\s*([^\n]+?)\s+Longitude:\s*([^\n]+)", txt)
        if m:
            dados["latitude"] = m.group(1).strip()
            dados["longitude"] = m.group(2).strip()

    m = re.search(r"Data de Inscri[çc][ãa]o[\s\S]{0,120}?(\d{1,2}/\d{1,2}/\d{4})", txt)
    dados["data_cadastro"] = m.group(1) if m else ""

    # ---- ÁREAS DO IMÓVEL (rótulo e valor na mesma linha) ----
    dados["area_total_imovel_ha"] = _valor_tras_label(
        txt, "Área Total Calculada do Imóvel (ha)"
    )
    dados["area_total_ha"] = dados["area_total_imovel_ha"]
    dados["area_total_documentada_ha"] = _valor_tras_label(
        txt,
        "Área Total Documentada do Imóvel (ha)",
        "Área Total Documentada do Imóvil (ha)",  # variante espanhola (recibos)
    )
    dados["remanescente_vegetacao_nativa_ha"] = _valor_tras_label(
        txt, "Remanescente de Vegetação Nativa (ha)"
    )
    dados["area_app_ha"] = _valor_tras_label(
        txt, "Área de Preservação Permanente (ha)"
    )
    dados["area_uso_restrito_ha"] = _valor_tras_label(
        txt, "Área de Uso Restrito (ha)"
    )
    # Campos de Reserva Legal do certificado (mayor detalle que el recibo)
    dados["area_reserva_legal_exigida_ha"] = _valor_tras_label(
        txt, "Área de Reserva Legal Exigida (ha)"
    )
    dados["area_reserva_legal_existente_ha"] = _valor_tras_label(
        txt, "Área de Reserva Legal Existente (ha)"
    )
    dados["area_reserva_legal_proposta_ha"] = _valor_tras_label(
        txt, "Área Proposta para Reserva Legal (ha)"
    )
    dados["area_reserva_legal_condominio_ha"] = _valor_tras_label(
        txt, "Área de Reserva Legal em Condomínio (ha)"
    )
    # Campo de reserva legal do JSON: prioriza existente, depois proposta/exigida
    dados["area_reserva_legal_ha"] = (
        dados["area_reserva_legal_existente_ha"]
        if dados["area_reserva_legal_existente_ha"] not in ("", "-")
        else dados["area_reserva_legal_proposta_ha"]
        if dados["area_reserva_legal_proposta_ha"] not in ("", "-")
        else dados["area_reserva_legal_exigida_ha"]
    )

    dados["area_consolidada_ha"] = ""
    dados["area_servidao_administrativa_ha"] = ""
    dados["area_liquida_imovel_ha"] = dados["area_total_imovel_ha"]
    dados["modulos_fiscais"] = ""
    dados["codigo_protocolo"] = ""

    # ---- RESPONSÁVEIS (CNPJ/CPF), exceto o CADASTRANTE ----
    proprietarios = []
    seg = txt
    m = re.search(r"RESPONS[ÁA]VEIS\s*\n(.*?)\nCADASTRANTE", txt, re.DOTALL)
    if m:
        seg = m.group(1)
    for m in re.finditer(
        r"((?:\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})|(?:\d{3}\.\d{3}\.\d{3}-\d{2}))\s*-\s*([^\n]+)",
        seg,
    ):
        num = m.group(1)
        proprietarios.append({
            "tipo": "CNPJ" if "/" in num else "CPF",
            "numero": num,
            "nome": m.group(2).strip(),
        })
    dados["proprietarios"] = proprietarios
    dados["cnpj"] = "; ".join(p["numero"] for p in proprietarios if p["tipo"] == "CNPJ")
    dados["cpf"] = "; ".join(p["numero"] for p in proprietarios if p["tipo"] == "CPF")
    dados["nome_proprietario"] = " | ".join(p["nome"] for p in proprietarios)

    dados["matriculas"] = []

    dados["informacoes_adicionais"] = ""
    dados["area_grafica_ha"] = ""
    dados["diferenca_detectada"] = ""
    dados["situacao"] = ""
    dados["condicion"] = ""
    dados["aderiu_pra"] = ""
    dados["condicion_pra"] = ""
    dados["data_analise_car"] = ""
    dados["data_ultima_retificacao"] = ""
    return _normalizar_campos(dados)


def extrair_dados_car(texto: str, caminho_pdf: Path, numero_os: str = "") -> dict:
    """Retorna un dicionario 'completo' con todos los datos do CAR.

    Detecta automáticamente el formato del documento:
      - RECIBO DE INSCRIPCIÓN -> extrair_dados_recibo (formato nacional);
      - DEMONSTRATIVO SICAR   -> extrair_dados_demonstrativo;
      - CERTIFICADO ESTADUAL  -> extrair_dados_certificado_ms.
    """
    if ("Certificado de Inscrição Número" in texto
            or ("CADASTRO AMBIENTAL RURAL DO" in texto and "ÁREAS DO IMÓVEL" in texto)):
        return extrair_dados_certificado_ms(texto, caminho_pdf, numero_os)

    if "Demonstrativo de Informações no CAR" in texto:
        return extrair_dados_demonstrativo_simcar_mt(texto, caminho_pdf, numero_os)

    # Recibo de Inscrição CAR estadual (SIMCAR/MT e estados com mesmo layout)
    if ("Nº Recibo Federal" in texto
            or re.search(r"Recibo de Inscrição\s+CAR\s*[–\-]\s*[A-Z]{2}", texto)):
        return extrair_dados_recibo_simcar_mt(texto, caminho_pdf, numero_os)

    es_demonstrativo = ("Cobertura do Solo" in texto) or ("Dados do Imóvel" in texto)
    if es_demonstrativo and "Nome do Imóvil Rural" not in texto:
        return extrair_dados_demonstrativo(texto, caminho_pdf, numero_os)

    # ------------------- FORMATO A: RECIBO (nacional) ------------------
    dados = {
        "arquivo_pdf": caminho_pdf.name,
        "path_pdf": str(caminho_pdf),          # caminho absoluto do PDF
        "numero_os": numero_os,                # OS da subpasta ou informada na console
    }

    # ---------- Chave: número do Registro no CAR (GO-/PR-/PI-/etc.) ----------
    m = re.search(r"Registro no CAR:\s*([A-Z0-9][A-Z0-9.\-]+)", texto)
    if not m:
        raise RuntimeError("não encontrei o número do 'Registro no CAR' no PDF")
    dados["numero_do_car"] = m.group(1)

    m = re.search(
        r"Data de Cadastro:\s*(\d{1,2}/\d{1,2}/\d{4}\s+\d{2}:\d{2}:\d{2})", texto
    )
    dados["data_cadastro"] = m.group(1) if m else ""

    # Nome do imóvel pode ocupar várias linhas -> captura até "Município:"
    m = re.search(r"Nome do Imóvel Rural:\s*(.*?)\n\s*Município:", texto, re.DOTALL)
    dados["nome_imovel"] = " ".join(m.group(1).split()) if m else ""

    m = re.search(r"Município:\s*([^\n]+?)\s+UF:\s*([^\n]+)", texto)
    dados["municipio"] = m.group(1).strip() if m else ""
    dados["uf"] = m.group(2).strip() if m else ""

    m = re.search(r"Latitude:\s*([^\n]+?)\s+Longitude:\s*([^\n]+)", texto)
    dados["latitude"] = m.group(1).strip() if m else ""
    dados["longitude"] = m.group(2).strip() if m else ""

    m = re.search(
        r"Área Total \(ha\) do Imóvel Rural:\s*([\d.,]+)\s*Módulos Fiscais:\s*([\d.,]+)",
        texto,
        re.IGNORECASE,
    )
    dados["area_total_ha"] = m.group(1) if m else ""
    dados["modulos_fiscais"] = m.group(2) if m else ""

    m = re.search(r"Código do Protocolo:\s*([A-Z0-9.\-]+)", texto)
    dados["codigo_protocolo"] = m.group(1) if m else ""

    # ---------- Áreas declaradas (em hectares) ----------
    for campo, padrao in _CAMPOS_AREA:
        m = re.search(padrao, texto)
        dados[campo] = m.group(1) if m else ""

    # ---------- Proprietário / possuidor (pode ter CNPJ e/ou CPF) ----------
    proprietarios = []
    for m in re.finditer(r"\b(CNPJ|CPF):\s*([A-Z0-9./\-]+)\s+Nome:\s*([^\n]+)", texto):
        proprietarios.append({
            "tipo": m.group(1),
            "numero": m.group(2),
            "nome": m.group(3).strip(),
        })
    dados["proprietarios"] = proprietarios
    dados["cnpj"] = "; ".join(p["numero"] for p in proprietarios if p["tipo"] == "CNPJ")
    dados["cpf"] = "; ".join(p["numero"] for p in proprietarios if p["tipo"] == "CPF")
    dados["nome_proprietario"] = " | ".join(p["nome"] for p in proprietarios)

    # ---------- Matrículas das propriedades ----------
    dados["matriculas"] = extrair_matriculas(texto)

    # ---------- Informações adicionais / divergência de área ----------
    dados["informacoes_adicionais"] = ""
    ini = texto.find("INFORMAÇÕES ADICIONAIS")
    fim = texto.find("REPRESENTAÇÃO GRÁFICA", ini) if ini != -1 else -1
    if ini != -1 and fim != -1:
        bloco = texto[ini + len("INFORMAÇÕES ADICIONAIS"):fim]
        dados["informacoes_adicionais"] = " ".join(bloco.split())

    dif = re.findall(r"\[([\d.,]+)\s*hectares\]", texto)
    dados["area_documentacao_ha"] = dif[0] if len(dif) > 0 else ""
    dados["area_grafica_ha"] = dif[1] if len(dif) > 1 else ""
    dados["diferenca_detectada"] = (
        "Sim" if "Foi detectada" in dados["informacoes_adicionais"] else "Não"
    )

    # Campos exclusivos do formato 'Demonstrativo' — vazios no recibo
    dados.setdefault("tipo_documento", "Recibo de Inscrição")
    for campo_novo in (
        "situacao", "condicion", "aderiu_pra", "condicion_pra",
        "data_analise_car", "data_ultima_retificacao",
        "area_total_documentada_ha", "area_reserva_legal_exigida_ha",
        "area_reserva_legal_existente_ha", "area_reserva_legal_proposta_ha",
        "area_reserva_legal_condominio_ha",
    ):
        dados.setdefault(campo_novo, "")
    return _normalizar_campos(dados)
# =====================================================================
# 4) JSON: CARREGAR / SALVAR / BACKUP
# =====================================================================
def carregar_json() -> dict:
    """Lê o JSON existente (pasta do script). Se não existe -> {}."""
    if JSON_CAMINHO.exists():
        try:
            with JSON_CAMINHO.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}                                   # corrompido -> recomeçar
    return {}


def salvar_json(base: dict) -> None:
    """Grava o JSON completo (pasta do script)."""
    with JSON_CAMINHO.open("w", encoding="utf-8") as fh:
        json.dump(base, fh, ensure_ascii=False, indent=2)


def gerar_backup(chave: str) -> Path:
    """Copia o JSON inteiro (estado antigo) na pasta de backup do TEMP do PC."""
    PASTA_BACKUP.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = PASTA_BACKUP / f"{chave}_{timestamp}.json"
    shutil.copy2(JSON_CAMINHO, destino)
    return destino


# =====================================================================
# 5) CSV: COLUNAS + GRAVAÇÃO
# =====================================================================
COLUNAS_CSV = [
    "numero_do_car", "numero_os", "nome_imovel", "municipio", "uf",
    "latitude", "longitude", "area_total_ha", "modulos_fiscais",
    "codigo_protocolo", "data_cadastro",
    "area_consolidada_ha", "remanescente_vegetacao_nativa_ha",
    "area_reserva_legal_ha", "area_total_imovel_ha",
    "area_total_documentada_ha",
    "area_reserva_legal_exigida_ha", "area_reserva_legal_existente_ha",
    "area_reserva_legal_proposta_ha", "area_reserva_legal_condominio_ha",
    "area_servidao_administrativa_ha", "area_liquida_imovel_ha",
    "area_app_ha", "area_uso_restrito_ha",
    "cnpj", "cpf", "nome_proprietario",
    "numero_matricula", "data_documento_matricula",
    "livro_matricula", "folha_matricula", "municipio_cartorio",
    "diferenca_detectada", "area_documentacao_ha", "area_grafica_ha",
    "tipo_documento", "situacao", "condicion", "aderiu_pra", "condicion_pra",
    "data_analise_car", "data_ultima_retificacao",
    "arquivo_pdf", "path_pdf", "criado_em", "atualizado_em",
]


def _matriculas_para_celulas(matriculas) -> dict:
    """Separa cada campo da matrícula em sua própria coluna (unindo com ' | ')."""
    campos = {
        "numero_matricula": [],
        "data_documento_matricula": [],
        "livro_matricula": [],
        "folha_matricula": [],
        "municipio_cartorio": [],
    }
    for m in matriculas:
        campos["numero_matricula"].append(m.get("numero", ""))
        campos["data_documento_matricula"].append(m.get("data_documento", ""))
        campos["livro_matricula"].append(m.get("livro", ""))
        campos["folha_matricula"].append(m.get("folha", ""))
        campos["municipio_cartorio"].append(m.get("municipio", ""))
    return {k: " | ".join(v) for k, v in campos.items()}


def salvar_csv(base: dict) -> int:
    """Gera o CSV (somente dados úteis); devolve nº de linhas sem cabeçalho."""
    with CSV_CAMINHO.open("w", encoding="utf-8-sig", newline="") as fh:
        escritor = csv.DictWriter(fh, fieldnames=COLUNAS_CSV, delimiter=";")
        escritor.writeheader()
        for chave in sorted(base):
            dados = dict(base[chave])
            dados.update(_matriculas_para_celulas(dados.get("matriculas", [])))
            escritor.writerow({col: dados.get(col, "") for col in COLUNAS_CSV})
    with CSV_CAMINHO.open("r", encoding="utf-8-sig") as fh:
        n_filas = sum(1 for _ in csv.DictReader(fh, delimiter=";"))
    return n_filas
# =====================================================================
# 6) MAIN
# =====================================================================
def solicitar_numero_os() -> str:
    """Pergunta na console o número de OS; sugere o número da pasta (OS_059)."""
    sugerido = ""
    m = re.search(r"[\\/]OS[_\-\s]*(\d+)", str(PASTA_SCRIPT), re.IGNORECASE)
    if m:
        sugerido = m.group(1)

    if sugerido:
        resposta = input(f"Digite o número da OS [padrão: {sugerido}]: ").strip()
        return resposta if resposta else sugerido

    while True:
        resposta = input("Digite o número da OS: ").strip()
        if resposta:
            return resposta
        print("O número da OS não pode ficar vazio. Tente de novo.")


def main() -> None:
    print("=" * 72)
    print(f"PASTA DO SCRIPT..........: {PASTA_SCRIPT}")
    print(f"Procurando *.pdf.........: {PASTA_SCRIPT}")
    print(f"Buscar em subpastas......: {'Sim' if BUSCAR_SUBPASTAS else 'Não'}")
    print("=" * 72)

    padrao = "**/*.pdf" if BUSCAR_SUBPASTAS else "*.pdf"
    pdfs = sorted(pdf for pdf in PASTA_SCRIPT.glob(padrao) if pdf.is_file())
    if not pdfs:
        print("\nNenhum arquivo .pdf encontrado na busca. Nada a fazer.\n")
        return

    usar_os_subpasta = BUSCAR_SUBPASTAS and USAR_NOME_SUBPASTA_COMO_OS
    numero_os = ""
    if not usar_os_subpasta or any(pdf.parent == PASTA_SCRIPT for pdf in pdfs):
        numero_os = solicitar_numero_os()
    if usar_os_subpasta:
        print("OS dos PDFs em subpastas: nome da pasta que contém cada PDF.")
        if numero_os:
            print(f"OS dos PDFs na pasta do script: {numero_os}")
    else:
        print(f"Número de OS registrado em todos os PDFs: {numero_os}")
    print("=" * 72)

    base = carregar_json()
    inseridos: list = []
    atualizados: list = []
    falhas: list = []
    omitidos: list = []                       # PDFs que não são documentos CAR
    pdfs_com_area_total = 0
    pdfs_com_area_consolidada = 0

    for pdf in pdfs:
        nome_pdf = str(pdf.relative_to(PASTA_SCRIPT))
        numero_os_pdf = (
            pdf.parent.name
            if usar_os_subpasta and pdf.parent != PASTA_SCRIPT
            else numero_os
        )
        try:
            texto = extrair_texto_pdf(pdf)
            if not es_documento_car(texto):
                omitidos.append(nome_pdf)
                print(f"[OMITIDO ] {nome_pdf}  (não parece um documento CAR)")
                continue
            novo = extrair_dados_car(texto, pdf, numero_os_pdf)
            # Conta por PDF, mesmo quando vários documentos têm o mesmo CAR.
            # Zero é uma área informada; vazio/None/hífen indicam ausência.
            pdfs_com_area_total += any(
                novo.get(campo) not in (None, "", "-")
                for campo in ("area_total_ha", "area_total_imovel_ha")
            )
            pdfs_com_area_consolidada += (
                novo.get("area_consolidada_ha") not in (None, "", "-")
            )
            chave = novo["numero_do_car"]
            agora = agora_iso()

            if chave in base:                                   # ATUALIZAÇÃO
                novo["criado_em"] = base[chave].get("criado_em") or agora
                backup = gerar_backup(chave)
                atualizados.append(chave)
                print(f"[ATUALIZA] {chave}  (backup -> {backup})")
            else:                                              # INSERÇÃO
                novo["criado_em"] = agora
                inseridos.append(chave)
                print(f"[INSERIDO] {chave}")

            novo["atualizado_em"] = agora
            base[chave] = novo                                  # upsert
        except Exception as erro:
            falhas.append((nome_pdf, str(erro)))
            print(f"[FALHA   ] {nome_pdf}  ->  {erro}")

    base = _enriquecer_nombres(base)
    base = _enriquecer_area_mesmo_imovel(base)
    # Garante que os campos novos (nomenclatura MS/Certificado) existam em TODOS
    # os registros da base — vazios onde o documento-fonte não os fornece. Isso
    # mantém o schema do JSON/CSV idêntico entre estados e versões de documento.
    _CAMPOS_COMPATIVEIS = (
        "area_total_documentada_ha",
        "area_reserva_legal_exigida_ha",
        "area_reserva_legal_existente_ha",
        "area_reserva_legal_proposta_ha",
        "area_reserva_legal_condominio_ha",
    )
    for reg in base.values():
        for campo_novo in _CAMPOS_COMPATIVEIS:
            reg.setdefault(campo_novo, "")
    salvar_json(base)
    try:
        n_filas = salvar_csv(base)
        csv_ok = True
    except PermissionError:
        csv_ok = False
        n_filas = None

    # ------------------------------------------------------------------
    # 7) RESUMO FINAL
    # ------------------------------------------------------------------
    print("\n" + "=" * 72)
    print("RESUMO FINAL DA EXECUÇÃO")
    print("=" * 72)
    print(f"  PDFs encontrados na busca : {len(pdfs)}")
    print(f"  Registros inseridos       : {len(inseridos)}")
    print(f"  Registros atualizados     : {len(atualizados)}")
    print(f"  Documentos não-CAR omítidos : {len(omitidos)}")
    print(f"  PDFs com falha            : {len(falhas)}")
    print(f"  PDFs com área total       : {pdfs_com_area_total} de {len(pdfs)}")
    print(f"  PDFs com área consolidada : {pdfs_com_area_consolidada} de {len(pdfs)}")

    if inseridos:
        print("\n  INSERIDOS:")
        for n, ch in enumerate(inseridos, 1):
            print(f"    {n}. {ch}")
    if atualizados:
        print("\n  ATUALIZAÇÕES:")
        for n, ch in enumerate(atualizados, 1):
            print(f"    {n}. {ch}")
    if omitidos:
        print("\n  OMITIDOS (não são documentos CAR):")
        for n, arq in enumerate(omitidos, 1):
            print(f"    {n}. {arq}")
    if falhas:
        print("\n  FALHAS:")
        for n, (arq, motivo) in enumerate(falhas, 1):
            print(f"    {n}. {arq}  ->  {motivo}")

    print(f"\n  Arquivos gerados:")
    if usar_os_subpasta:
        print("    Nº de OS registrado    : nome da subpasta de cada PDF")
        if numero_os:
            print(f"    OS dos PDFs na raiz    : {numero_os}")
    else:
        print(f"    Nº de OS registrado    : {numero_os}")
    print(f"    JSON : {JSON_CAMINHO}")
    if csv_ok:
        print(f"    CSV  : {CSV_CAMINHO}")
    else:
        print(f"    CSV  : {CSV_CAMINHO}  <<<<< NÃO PUDO GRAVAR: arquivo está ABERTO (bloqueado)")
        print("           -> Feche o CSV (Excel) e execute o script novamente.")
    print(f"  Backup (TEMP do PC)      : {PASTA_BACKUP}")
    print(f"  Chaves no JSON           : {len(base)}")
    if csv_ok:
        print(f"  Linhas no CSV (sem cabeça) : {n_filas}")
        if len(base) != n_filas:
            print("  !!! ATENÇÃO: nº de chaves diverge do nº de filas do CSV !!!")
    else:
        print(f"  Linhas no CSV (sem cabeça) : -- (CSV bloqueado)")
    print("=" * 72)
    try:
        input("Fim (pressione Enter): ")
    except EOFError:
        pass                        # terminal automático: não esperar Enter
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

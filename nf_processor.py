# Nome do arquivo: nf_processor.py (Versão Final Corrigida)

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from sqlalchemy import create_engine, text, exc
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import plotly.express as px
from pathlib import Path
import tempfile
from dotenv import load_dotenv
import google.generativeai as genai
from decimal import Decimal, InvalidOperation
import re
import unicodedata
import io
import zipfile
from security_utils import (
    XMLSecurityValidator, 
    DataSanitizer, 
    SecurityAuditor,
    SecurityConfig
)
from auth_streamlit import auth

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- CLASSES DE LÓGICA DE NEGÓCIO ---

import io
import pdfplumber

class PDFExtractor:
    @staticmethod
    def extrair_dados_pdf(pdf_bytes):
        try:
            def extrair_valor(pattern, texto, default=None):
                match = re.search(pattern, texto, re.IGNORECASE)
                if (match != None): 
                    if (match.group(1) != None): 
                        return match.group(1)
                    else: 
                        return default
                else: 
                    return default
            # Lê o PDF diretamente da memória
            pdf_stream = io.BytesIO(pdf_bytes)
            
            texto_completo = ""
            with pdfplumber.open(pdf_stream) as pdf:
                texto_completo = "\n".join(page.extract_text() or "" for page in pdf.pages)

            # Remove espaços duplos e normaliza
            texto_completo = re.sub(r"\s+", " ", texto_completo)

            # --- Expressões Regulares para DANFE ---
            cnpj_emitente = extrair_valor(r"CNPJ\s*[:\s]*([\d\.\-/]{14,18})", texto_completo,"CNPJ 00.111.111/0001-11")
            numero_nf = extrair_valor(r"N[º°]\s*(\d{1,9})", texto_completo, "Nº: 0")
            data_emissao_str = extrair_valor(r"(?:Data\s+(?:de\s+)?Emiss[aã]o|Emiss[aã]o)\s*:?[\s]*(\d{2}/\d{2}/\d{4})", texto_completo, None)
            
            # Processar data_emissao corretamente
            if data_emissao_str:
                try:
                    data_emissao = datetime.strptime(data_emissao_str, '%d/%m/%Y')
                except ValueError:
                    logger.warning(f"Formato de data inválido no PDF: {data_emissao_str}. Usando data atual.")
                    data_emissao = datetime.now()
            else:
                data_emissao = datetime.now()
            
            serie=extrair_valor(r"S[ée]rie\s*:?[\s]*([0-9]{1,3})", texto_completo,"SÉRIE 0")
            nome_emitente=extrair_valor(r"(?:Emitente\s*:?[\s]*(.+)|recebemos\s+de\s+(.+?)\s+os\s+produtos)", texto_completo, "EMITENTE NÃO ENCONTRADO")
            valor_total=extrair_valor(r"Valor\s+Total\s+(?:da\s+(?:Nota|nf-?e)|Nota)\s*(?:R\$)?\s*([\d\.,]+)", texto_completo, 0)
            chave_acesso=extrair_valor(r"((?:\d{4}\s*){11})", texto_completo, "0000 0000 0000 0000 0000 0000 0000 0000 0000 0000 0000")
            natureza_operacao=extrair_valor(r"^natureza\s+(?:da|de\s+)?opera[cç][aã]o$", texto_completo, "SEM NATUREZA")

            # Cria o objeto NotaFiscal

            nota = NotaFiscal(
                numero=numero_nf,
                cnpj_emitente=cnpj_emitente,
                data_emissao=data_emissao,
                serie=serie,
                nome_emitente=nome_emitente,
                valor_total=valor_total,
                chave_acesso=chave_acesso,
                natureza_operacao=natureza_operacao
            )

            return nota

        except Exception as e:
            print(f"ROBÔ: Erro ao processar PDF: {e}")
            return None


class XMLExtractor:
    """Extrator seguro de dados XML com validação e sanitização"""
    
    @staticmethod
    def extrair_dados_xml(xml_content: bytes, filename: str = "unknown") -> Optional['NotaFiscal']:
        """
        Extrai dados de XML de forma segura usando defusedxml
        
        Args:
            xml_content: Conteúdo do arquivo XML em bytes
            filename: Nome do arquivo para auditoria
            
        Returns:
            NotaFiscal ou None se houver erro
        """
        try:
            # Log do início do processamento
            SecurityAuditor.log_file_processing(
                filename, len(xml_content), "XML", False
            )
            
            # Parse seguro do XML
            root = XMLSecurityValidator.parse_xml_safely(xml_content)
            if root is None:
                logger.error(f"Falha na validação de segurança do XML: {filename}")
                return None
            
            # Extrair dados com sanitização
            nota_fiscal = XMLExtractor._extrair_dados_seguros(root, xml_content)
            
            if nota_fiscal:
                # Log de sucesso
                SecurityAuditor.log_file_processing(
                    filename, len(xml_content), "XML", True
                )
                logger.info(f"XML processado com sucesso: {filename}")
            
            return nota_fiscal
            
        except Exception as e:
            logger.error(f"Erro crítico ao processar XML {filename}: {e}")
            SecurityAuditor.log_security_event(
                "XML_PROCESSING_ERROR",
                {"filename": filename, "error": str(e)},
                "ERROR"
            )
            return None
    
    @staticmethod
    def _extrair_dados_seguros(root, xml_content: bytes) -> Optional['NotaFiscal']:
        """Extrai dados do XML com sanitização completa"""
        try:
            # Definir namespaces
            ns = {'nfe': 'http://www.portalfiscal.inf.br/nfe'}
            
            # Buscar elemento principal
            inf_nfe = root.find('.//nfe:infNFe', ns)
            if inf_nfe is None:
                inf_nfe = root.find('.//infNFe')
                ns = {}
            
            if inf_nfe is None:
                logger.warning("Elemento infNFe não encontrado no XML")
                return None
            
            # Extrair elementos principais
            ide = inf_nfe.find('.//ide' if not ns else './/nfe:ide', ns)
            emit = inf_nfe.find('.//emit' if not ns else './/nfe:emit', ns)
            dest = inf_nfe.find('.//dest' if not ns else './/nfe:dest', ns)
            total = inf_nfe.find('.//total' if not ns else './/nfe:total', ns)
            
            if not all([ide, emit, total]):
                logger.warning("Elementos obrigatórios não encontrados no XML")
                return None
            
            icms_tot = total.find('.//ICMSTot' if not ns else './/nfe:ICMSTot', ns)
            if icms_tot is None:
                logger.warning("Elemento ICMSTot não encontrado")
                return None
            
            # Extrair e sanitizar dados
            numero = DataSanitizer.sanitize_string(XMLExtractor._get_text_safe(ide, 'nNF', ns))
            serie = DataSanitizer.sanitize_string(XMLExtractor._get_text_safe(ide, 'serie', ns))
            data_emissao = XMLExtractor._parse_date_safe(XMLExtractor._get_text_safe(ide, 'dhEmi', ns))
            
            # CNPJ com validação específica
            cnpj_emitente = DataSanitizer.sanitize_cnpj(XMLExtractor._get_text_safe(emit, 'CNPJ', ns))
            cnpj_destinatario = DataSanitizer.sanitize_cnpj(XMLExtractor._get_text_safe(dest, 'CNPJ', ns)) if dest is not None else None
            
            # Nomes sanitizados
            nome_emitente = DataSanitizer.sanitize_string(XMLExtractor._get_text_safe(emit, 'xNome', ns))
            nome_destinatario = DataSanitizer.sanitize_string(XMLExtractor._get_text_safe(dest, 'xNome', ns)) if dest is not None else None
            
            # Valores numéricos sanitizados
            valor_total = DataSanitizer.sanitize_numeric_value(XMLExtractor._get_text_safe(icms_tot, 'vNF', ns))
            valor_icms = DataSanitizer.sanitize_numeric_value(XMLExtractor._get_text_safe(icms_tot, 'vICMS', ns))
            valor_ipi = DataSanitizer.sanitize_numeric_value(XMLExtractor._get_text_safe(icms_tot, 'vIPI', ns))
            valor_pis = DataSanitizer.sanitize_numeric_value(XMLExtractor._get_text_safe(icms_tot, 'vPIS', ns))
            valor_cofins = DataSanitizer.sanitize_numeric_value(XMLExtractor._get_text_safe(icms_tot, 'vCOFINS', ns))
            
            # Chave de acesso com validação
            chave_acesso_raw = inf_nfe.get('Id', '').replace('NFe', '')
            chave_acesso = DataSanitizer.sanitize_chave_acesso(chave_acesso_raw)
            
            # Natureza da operação
            natureza_operacao = DataSanitizer.sanitize_string(XMLExtractor._get_text_safe(ide, 'natOp', ns))
            
            # Extrair itens com limite de segurança
            itens = XMLExtractor._extrair_itens_seguros(inf_nfe, ns)
            
            # XML original sanitizado (apenas para auditoria, limitado)
            xml_string = xml_content.decode('utf-8', errors='replace')[:10000]  # Limitar tamanho
            
            return NotaFiscal(
                numero=numero,
                serie=serie,
                data_emissao=data_emissao,
                cnpj_emitente=cnpj_emitente,
                nome_emitente=nome_emitente,
                cnpj_destinatario=cnpj_destinatario,
                nome_destinatario=nome_destinatario,
                valor_total=valor_total,
                valor_icms=valor_icms,
                valor_ipi=valor_ipi,
                valor_pis=valor_pis,
                valor_cofins=valor_cofins,
                chave_acesso=chave_acesso,
                natureza_operacao=natureza_operacao,
                itens=itens,
                xml_original=xml_string
            )
            
        except Exception as e:
            logger.error(f"Erro na extração segura de dados: {e}")
            return None
    
    @staticmethod
    def _get_text_safe(element, tag: str, ns: dict) -> str:
        """Extrai texto de elemento XML de forma segura"""
        if element is None:
            return ""
        
        try:
            node = element.find(f".//nfe:{tag}", ns) if ns else element.find(f".//{tag}")
            return node.text if node is not None and node.text else ""
        except Exception:
            return ""
    
    @staticmethod
    def _parse_date_safe(date_str: str) -> Optional[datetime]:
        """Parse seguro de data"""
        if not date_str:
            return None
        
        try:
            # Sanitizar string de data
            date_clean = DataSanitizer.sanitize_string(date_str)
            return datetime.fromisoformat(date_clean.split('T')[0])
        except Exception:
            logger.warning(f"Data inválida: {date_str}")
            return None
    
    @staticmethod
    def _extrair_itens_seguros(inf_nfe, ns: dict) -> List[Dict[str, Any]]:
        """Extrai itens da NF com limite de segurança"""
        itens = []
        
        try:
            det_elements = inf_nfe.findall('.//nfe:det', ns) if ns else inf_nfe.findall('.//det')
            
            # Limitar número de itens por segurança
            if len(det_elements) > SecurityConfig.MAX_ITEMS_PER_NF:
                logger.warning(f"NF com muitos itens ({len(det_elements)}), limitando a {SecurityConfig.MAX_ITEMS_PER_NF}")
                det_elements = det_elements[:SecurityConfig.MAX_ITEMS_PER_NF]
            
            for det in det_elements:
                prod = det.find('.//nfe:prod', ns) if ns else det.find('.//prod')
                if prod is not None:
                    item = {
                        'codigo': DataSanitizer.sanitize_string(XMLExtractor._get_text_safe(prod, 'cProd', ns)),
                        'descricao': DataSanitizer.sanitize_string(XMLExtractor._get_text_safe(prod, 'xProd', ns)),
                        'ncm': DataSanitizer.sanitize_string(XMLExtractor._get_text_safe(prod, 'NCM', ns)),
                        'quantidade': DataSanitizer.sanitize_numeric_value(XMLExtractor._get_text_safe(prod, 'qCom', ns)),
                        'valor_unitario': DataSanitizer.sanitize_numeric_value(XMLExtractor._get_text_safe(prod, 'vUnCom', ns)),
                        'valor_total': DataSanitizer.sanitize_numeric_value(XMLExtractor._get_text_safe(prod, 'vProd', ns))
                    }
                    itens.append(item)
            
            return itens
            
        except Exception as e:
            logger.error(f"Erro ao extrair itens: {e}")
            return []

class ValidadorNF:
    """Validador seguro de Notas Fiscais com verificações rigorosas"""
    
    @staticmethod
    def validar_nota_fiscal(nota: 'NotaFiscal') -> bool:
        """
        Valida uma nota fiscal com verificações de segurança
        
        Args:
            nota: Instância de NotaFiscal para validar
            
        Returns:
            bool: True se válida, False caso contrário
        """
        if not nota:
            logger.warning("Validação falhou: nota fiscal é None")
            return False
        
        try:
            # Validar campos obrigatórios básicos
            if not ValidadorNF._validar_campos_obrigatorios(nota):
                return False
            
            # Validar CNPJ
            if not ValidadorNF._validar_cnpj(nota.cnpj_emitente):
                logger.warning(f"Validação falhou: CNPJ emitente inválido na NF {nota.numero}")
                return False
            
            # Validar chave de acesso
            if not ValidadorNF._validar_chave_acesso(nota.chave_acesso):
                logger.warning(f"Validação falhou: chave de acesso inválida na NF {nota.numero}")
                return False
            
            # Validar valores numéricos
            if not ValidadorNF._validar_valores(nota):
                return False
            
            # Validar data
            if not ValidadorNF._validar_data(nota.data_emissao):
                logger.warning(f"Validação falhou: data inválida na NF {nota.numero}")
                return False
            
            # Validar itens se existirem
            if nota.itens and not ValidadorNF._validar_itens(nota.itens):
                logger.warning(f"Validação falhou: itens inválidos na NF {nota.numero}")
                return False
            
            # Log de validação bem-sucedida
            SecurityAuditor.log_security_event(
                "NF_VALIDATION_SUCCESS",
                {
                    "nf_numero": nota.numero,
                    "cnpj_emitente": nota.cnpj_emitente,
                    "valor_total": nota.valor_total
                },
                "INFO"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Erro durante validação da NF {nota.numero or 'S/N'}: {e}")
            SecurityAuditor.log_security_event(
                "NF_VALIDATION_ERROR",
                {"nf_numero": nota.numero or "S/N", "error": str(e)},
                "ERROR"
            )
            return False
    
    @staticmethod
    def _validar_campos_obrigatorios(nota: 'NotaFiscal') -> bool:
        """Valida campos obrigatórios básicos"""
        campos_obrigatorios = [
            (nota.numero, "número"),
            (nota.serie, "série"),
            (nota.cnpj_emitente, "CNPJ emitente"),
            (nota.chave_acesso, "chave de acesso"),
            (nota.nome_emitente, "nome emitente"),
            (nota.natureza_operacao, "natureza da operação")
        ]
        
        for valor, nome_campo in campos_obrigatorios:
            if not valor or (isinstance(valor, str) and not valor.strip()):
                logger.warning(f"Validação falhou: campo '{nome_campo}' ausente na NF {nota.numero or 'S/N'}")
                return False
        
        return True
    
    @staticmethod
    def _validar_cnpj(cnpj: str) -> bool:
        """Valida formato do CNPJ"""
        if not cnpj:
            return False
        
        # Remover formatação
        cnpj_numeros = re.sub(r'[^\d]', '', cnpj)
        
        # Verificar tamanho
        if len(cnpj_numeros) != 14:
            return False
        
        # Verificar se não são todos números iguais
        if cnpj_numeros == cnpj_numeros[0] * 14:
            return False
        
        # Validação básica de dígitos verificadores
        return ValidadorNF._calcular_digito_cnpj(cnpj_numeros)
    
    @staticmethod
    def _calcular_digito_cnpj(cnpj: str) -> bool:
        """Calcula e valida dígitos verificadores do CNPJ"""
        try:
            # Primeiro dígito
            soma = 0
            peso = 5
            for i in range(12):
                soma += int(cnpj[i]) * peso
                peso -= 1
                if peso < 2:
                    peso = 9
            
            resto = soma % 11
            digito1 = 0 if resto < 2 else 11 - resto
            
            if int(cnpj[12]) != digito1:
                return False
            
            # Segundo dígito
            soma = 0
            peso = 6
            for i in range(13):
                soma += int(cnpj[i]) * peso
                peso -= 1
                if peso < 2:
                    peso = 9
            
            resto = soma % 11
            digito2 = 0 if resto < 2 else 11 - resto
            
            return int(cnpj[13]) == digito2
            
        except (ValueError, IndexError):
            return False
    
    @staticmethod
    def _validar_chave_acesso(chave: str) -> bool:
        """Valida formato da chave de acesso"""
        if not chave:
            return False
        
        # Remover prefixos e caracteres não numéricos
        chave_limpa = re.sub(r'[^\d]', '', chave.replace('NFe', ''))
        
        # Verificar tamanho
        if len(chave_limpa) != 44:
            return False
        
        # Verificar se não são todos zeros
        if chave_limpa == '0' * 44:
            return False
        
        return True
    
    @staticmethod
    def _validar_valores(nota: 'NotaFiscal') -> bool:
        """Valida valores numéricos da nota fiscal"""
        try:
            # Converter valor total se for string
            if isinstance(nota.valor_total, str):
                nota.valor_total = float(nota.valor_total.replace(",", "."))
            
            # Validar valor total
            if not isinstance(nota.valor_total, (int, float)) or nota.valor_total <= 0:
                logger.warning(f"Validação falhou: valor total inválido ({nota.valor_total}) na NF {nota.numero}")
                return False
            
            # Validar limite máximo (proteção contra valores absurdos)
            if nota.valor_total > 999999999.99:  # 999 milhões
                logger.warning(f"Validação falhou: valor total muito alto ({nota.valor_total}) na NF {nota.numero}")
                return False
            
            # Validar outros valores se existirem
            valores_opcionais = [
                (nota.valor_icms, "ICMS"),
                (nota.valor_ipi, "IPI"),
                (nota.valor_pis, "PIS"),
                (nota.valor_cofins, "COFINS")
            ]
            
            for valor, nome in valores_opcionais:
                if valor is not None and (not isinstance(valor, (int, float)) or valor < 0):
                    logger.warning(f"Validação falhou: valor {nome} inválido ({valor}) na NF {nota.numero}")
                    return False
            
            return True
            
        except (ValueError, TypeError) as e:
            logger.warning(f"Validação falhou: erro na conversão de valores na NF {nota.numero}: {e}")
            return False
    
    @staticmethod
    def _validar_data(data: datetime) -> bool:
        """Valida data de emissão"""
        if not data:
            return False
        
        # Verificar se a data não é muito antiga (mais de 10 anos)
        data_limite_passado = datetime.now() - timedelta(days=3650)
        if data < data_limite_passado:
            return False
        
        # Verificar se a data não é futura (mais de 1 dia)
        data_limite_futuro = datetime.now() + timedelta(days=1)
        if data > data_limite_futuro:
            return False
        
        return True
    
    @staticmethod
    def _validar_itens(itens: List[Dict[str, Any]]) -> bool:
        """Valida itens da nota fiscal"""
        if not itens:
            return True  # Itens são opcionais
        
        # Limitar número de itens
        if len(itens) > SecurityConfig.MAX_ITEMS_PER_NF:
            logger.warning(f"Muitos itens na NF: {len(itens)}")
            return False
        
        for i, item in enumerate(itens):
            if not isinstance(item, dict):
                logger.warning(f"Item {i} não é um dicionário válido")
                return False
            
            # Validar campos obrigatórios do item
            if not item.get('descricao') or not item.get('codigo'):
                logger.warning(f"Item {i} sem descrição ou código")
                return False
            
            # Validar valores numéricos do item
            try:
                quantidade = float(item.get('quantidade', 0))
                valor_unitario = float(item.get('valor_unitario', 0))
                valor_total = float(item.get('valor_total', 0))
                
                if quantidade < 0 or valor_unitario < 0 or valor_total < 0:
                    logger.warning(f"Item {i} com valores negativos")
                    return False
                    
            except (ValueError, TypeError):
                logger.warning(f"Item {i} com valores numéricos inválidos")
                return False
        
        return True

# --- CLASSES DE DADOS E CONFIGURAÇÃO ---

# Configuração movida para secure_config.py para melhor segurança
from secure_config import get_secure_config, SecureConfigError

@dataclass
class NotaFiscal:
    numero: str
    serie: str
    data_emissao: datetime
    cnpj_emitente: str
    nome_emitente: str
    valor_total: float
    chave_acesso: str
    natureza_operacao: str
    situacao: str = 'Pendente'
    data_vencimento: Optional[datetime] = None
    cnpj_destinatario: Optional[str] = None
    nome_destinatario: Optional[str] = None
    valor_icms: float = 0.0
    valor_ipi: float = 0.0
    valor_pis: float = 0.0
    valor_cofins: float = 0.0
    itens: List[Dict[str, Any]] = None
    xml_original: Optional[str] = None
    processado_em: datetime = None

    def __post_init__(self):
        if self.processado_em is None:
            self.processado_em = datetime.now()
        if self.itens is None:
            self.itens = []

# --- MÓDULO DE BANCO DE DADOS ---

class DatabaseManager:
    def __init__(self, secure_config=None):
        try:
            if secure_config is None:
                secure_config = get_secure_config()
            
            if not secure_config.DATABASE_URL:
                raise ValueError("A URL do banco de dados (DATABASE_URL) não foi configurada.")
            
            # Configurar parâmetros de conexão baseado no tipo de banco
            if secure_config.DATABASE_URL.startswith('sqlite'):
                # SQLite não suporta connect_timeout, usar check_same_thread=False
                connect_args = {'check_same_thread': False}
                self.engine = create_engine(
                    secure_config.DATABASE_URL,
                    connect_args=connect_args,
                    json_serializer=json.dumps
                )
            else:
                # PostgreSQL e outros bancos suportam connect_timeout
                connect_args = {'connect_timeout': 10}
                self.engine = create_engine(
                    secure_config.DATABASE_URL,
                    connect_args=connect_args,
                    json_serializer=json.dumps,
                    pool_pre_ping=True,  # Verifica conexões antes de usar
                    pool_recycle=3600,   # Recicla conexões a cada hora
                    max_overflow=0,      # Limita conexões extras
                    pool_size=5          # Pool de conexões limitado
                )
            
            # Teste de conexão seguro
            with self.engine.connect() as connection:
                logger.info("Conexão com o banco de dados estabelecida com sucesso.")
                
                # Log de auditoria
                SecurityAuditor.log_security_event(
                    "DATABASE_CONNECTION_SUCCESS",
                    {"database_type": "PostgreSQL"},
                    "INFO"
                )
                
        except SecureConfigError as e:
            logger.error(f"Erro de configuração segura: {e}")
            SecurityAuditor.log_security_event(
                "DATABASE_CONFIG_ERROR",
                {"error": str(e)},
                "ERROR"
            )
            raise
        except Exception as e:
            logger.error(f"Falha CRÍTICA ao conectar ao banco de dados: {e}")
            SecurityAuditor.log_security_event(
                "DATABASE_CONNECTION_FAILED",
                {"error": str(e)},
                "CRITICAL"
            )
            raise

    def log_processamento(self, tipo: str, arquivo: str, status: str, mensagem: str = ""):
        query = text("INSERT INTO logs_processamento (tipo_operacao, arquivo_processado, status, mensagem_erro, timestamp) VALUES (:tipo, :arquivo, :status, :msg, CURRENT_TIMESTAMP)")
        try:
            with self.engine.connect() as connection:
                trans = connection.begin()
                connection.execute(query, {"tipo": tipo, "arquivo": arquivo, "status": status, "msg": mensagem})
                trans.commit()
        except Exception as e:
            logger.error(f"Falha GRAVE ao registrar log no banco de dados: {e}")

    def salvar_nota_fiscal(self, nota: NotaFiscal) -> bool:
        logger.info(f"🔍 INICIANDO SALVAMENTO DA NOTA: {nota.numero}")
        logger.info(f"📋 DADOS RECEBIDOS: numero={nota.numero}, serie={getattr(nota, 'serie', 'N/A')}, cnpj_emitente={nota.cnpj_emitente}, chave_acesso={getattr(nota, 'chave_acesso', 'N/A')}")
        
        # Garantir que campos obrigatórios tenham valores válidos
        numero = nota.numero or f"NF-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        serie = getattr(nota, 'serie', None) or '1'
        cnpj_emitente = nota.cnpj_emitente or '00000000000000'
        chave_acesso = getattr(nota, 'chave_acesso', None) or f"CHAVE{datetime.now().strftime('%Y%m%d%H%M%S')}{numero}"
        
        # Garantir que a chave de acesso tenha o tamanho correto (máximo 60 caracteres)
        if len(chave_acesso) > 60:
            chave_acesso = chave_acesso[:60]
        
        logger.info(f"✅ CAMPOS VALIDADOS: numero={numero}, serie={serie}, cnpj_emitente={cnpj_emitente}, chave_acesso={chave_acesso}")
        
        check_query = text("SELECT id FROM notas_fiscais WHERE chave_acesso = :chave")
        try:
            with self.engine.connect() as connection:
                if connection.execute(check_query, {"chave": chave_acesso}).fetchone():
                    logger.warning(f"Nota fiscal {numero} (Chave: {chave_acesso}) já existe. Pulando.")
                    return False
        except Exception as e:
             logger.error(f"Erro ao verificar duplicidade da NF {numero}: {e}")
             return False

        # Preparar dados da nota fiscal com valores padrão para campos opcionais
        # CORREÇÃO: Converter Decimal para float para compatibilidade com SQLite
        nf_data = {
            'numero': numero,
            'serie': serie,
            'data_emissao': nota.data_emissao or datetime.now(),
            'cnpj_emitente': cnpj_emitente,
            'nome_emitente': nota.nome_emitente or 'Emitente não informado',
            'valor_total': float(nota.valor_total or 0.0),
            'chave_acesso': chave_acesso,
            'natureza_operacao': getattr(nota, 'natureza_operacao', None) or 'Operação não informada',
            'situacao': getattr(nota, 'situacao', 'Pendente'),
            'data_vencimento': getattr(nota, 'data_vencimento', None),
            'cnpj_destinatario': getattr(nota, 'cnpj_destinatario', None),
            'nome_destinatario': getattr(nota, 'nome_destinatario', None),
            'valor_icms': float(getattr(nota, 'valor_icms', 0.0)),
            'valor_ipi': float(getattr(nota, 'valor_ipi', 0.0)),
            'valor_pis': float(getattr(nota, 'valor_pis', 0.0)),
            'valor_cofins': float(getattr(nota, 'valor_cofins', 0.0)),
            'xml_original': getattr(nota, 'xml_original', None),
            'processado_em': getattr(nota, 'processado_em', datetime.now()),
            'origem': getattr(nota, 'origem', 'upload')
        }
        
        logger.info(f"📊 DADOS PREPARADOS PARA INSERÇÃO: {nf_data}")
        
        # Obter itens se existirem
        itens = getattr(nota, 'itens', []) or []

        insert_nf_query = text("""
            INSERT INTO notas_fiscais (
                numero, serie, data_emissao, cnpj_emitente, nome_emitente, 
                valor_total, chave_acesso, natureza_operacao, situacao, 
                data_vencimento, cnpj_destinatario, nome_destinatario, 
                valor_icms, valor_ipi, valor_pis, valor_cofins, 
                xml_original, processado_em, origem
            ) VALUES (
                :numero, :serie, :data_emissao, :cnpj_emitente, :nome_emitente,
                :valor_total, :chave_acesso, :natureza_operacao, :situacao,
                :data_vencimento, :cnpj_destinatario, :nome_destinatario,
                :valor_icms, :valor_ipi, :valor_pis, :valor_cofins,
                :xml_original, :processado_em, :origem
            ) RETURNING id
        """)
        
        insert_item_query = text("""
            INSERT INTO itens_nota_fiscal (
                nota_fiscal_id, codigo, descricao, ncm, 
                quantidade, valor_unitario, valor_total
            ) VALUES (
                :nota_id, :codigo, :descricao, :ncm, 
                :quantidade, :valor_unitario, :valor_total
            )
        """)

        try:
            with self.engine.begin() as connection:
                # Inserir nota fiscal
                result = connection.execute(insert_nf_query, nf_data)
                nf_id = result.fetchone()[0]
                
                # Inserir itens se existirem
                if itens and nf_id:
                    for item in itens:
                        item_data = {
                            'nota_id': nf_id,
                            'codigo': item.get('codigo', ''),
                            'descricao': item.get('descricao', ''),
                            'ncm': item.get('ncm', ''),
                            'quantidade': Decimal(str(item.get('quantidade', 0))),
                            'valor_unitario': Decimal(str(item.get('valor_unitario', 0))),
                            'valor_total': Decimal(str(item.get('valor_total', 0)))
                        }
                        connection.execute(insert_item_query, item_data)
                
            logger.info(f"✅ SUCESSO! Nota fiscal {nota.numero} salva no banco de dados com ID {nf_id}.")
            return True
            
        except (exc.SQLAlchemyError, InvalidOperation, TypeError) as e:
            logger.error(f"❌ ERRO AO SALVAR NF {nota.numero}: {e}")
            logger.error(f"📋 DADOS DA NF: {nf_data}")
            self.log_processamento("Salvar NF", f"NF {nota.numero}", "Erro de Gravação", str(e))
            return False

    def buscar_dados(self, table_name: str, filtros: Dict = None) -> List[Dict]:
        base_query = f"SELECT * FROM {table_name}"
        where_clauses, params = [], {}
        if filtros:
            for col, val in filtros.items():
                if col.endswith('_inicio'): 
                    # Para filtros de data, usar DATE() para comparar apenas a parte da data
                    col_name = col.replace('_inicio', '')
                    if 'data' in col_name.lower():
                        where_clauses.append(f"DATE({col_name}) >= :{col}")
                    else:
                        where_clauses.append(f"{col_name} >= :{col}")
                    params[col] = val
                elif col.endswith('_fim'): 
                    # Para filtros de data, usar DATE() para comparar apenas a parte da data
                    col_name = col.replace('_fim', '')
                    if 'data' in col_name.lower():
                        where_clauses.append(f"DATE({col_name}) <= :{col}")
                    else:
                        where_clauses.append(f"{col_name} <= :{col}")
                    params[col] = val
                else: 
                    where_clauses.append(f"{col} = :{col}")
                    params[col] = val
        if where_clauses: base_query += " WHERE " + " AND ".join(where_clauses)
        base_query += " ORDER BY id DESC"
        try:
            with self.engine.connect() as connection:
                # LINHA CORRIGIDA ABAIXO
                return connection.execute(text(base_query), params).mappings().all()
        except Exception as e:
            logger.error(f"Erro ao buscar dados da tabela {table_name}: {e}")
            st.error(f"Erro de Banco de Dados: Não foi possível buscar os dados da tabela '{table_name}'.")
            return []

    def buscar_nota_fiscal_por_numero(self, numero):
        """Busca uma nota fiscal pelo número e retorna seu ID"""
        try:
            with self.engine.connect() as connection:
                query = text("SELECT id FROM notas_fiscais WHERE numero = :numero")
                result = connection.execute(query, {"numero": numero}).fetchone()
                return result[0] if result else None
        except Exception as e:
            logger.error(f"Erro ao buscar nota fiscal por número {numero}: {e}")
            return None

    def salvar_item_nota_fiscal(self, item_data):
        """Salva um item de nota fiscal no banco de dados"""
        try:
            with self.engine.begin() as connection:
                query = text("""
                    INSERT INTO itens_nota_fiscal 
                    (nota_fiscal_id, codigo, descricao, ncm, quantidade, valor_unitario, valor_total)
                    VALUES (:nota_fiscal_id, :codigo, :descricao, :ncm, :quantidade, :valor_unitario, :valor_total)
                """)
                connection.execute(query, item_data)
                return True
        except Exception as e:
            logger.error(f"Erro ao salvar item da nota fiscal: {e}")
            return False

# --- MÓDULOS DE IA E DASHBOARD ---

class GeminiChat:
    def __init__(self, config):
        if not config.GEMINI_API_KEY or "AIza" not in config.GEMINI_API_KEY:
            raise ValueError("A chave da API do Gemini não foi configurada.")
        genai.configure(api_key=config.GEMINI_API_KEY)
        self.model = genai.GenerativeModel('gemini-1.5-flash')
    def responder_pergunta(self, pergunta: str, df_notas: pd.DataFrame):
        if df_notas.empty:
            return "Não há dados de notas fiscais para analisar. Por favor, ajuste os filtros."
        try:
            dados_para_analise = df_notas.head(100).to_csv(index=False, sep=';')
            prompt = f"Você é um assistente fiscal. Responda à pergunta do usuário com base nos dados em CSV abaixo.\n\nDados:\n{dados_para_analise}\n\nPergunta:\n{pergunta}"
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            logger.error(f"Erro ao chamar a API do Gemini: {e}")
            return f"Ocorreu um erro ao processar sua pergunta: {e}"

class Dashboard:
    def __init__(self):
        try:
            # Configurar página antes de qualquer coisa
            st.set_page_config(
                page_title="Gestor Fiscal AI", 
                layout="wide", 
                initial_sidebar_state="expanded",
                page_icon="🤖"
            )
            
            # Criar usuário admin se necessário
            auth.create_admin_if_needed()
            
            # Verificar autenticação
            if not auth.is_authenticated():
                auth.show_login_page()
                st.stop()
            
            # Inicializar configurações após autenticação
            self.config = get_secure_config()
            self.db_manager = DatabaseManager(self.config)
            
        except SecureConfigError as e:
            st.error(f"Erro de configuração: {e}")
            st.stop()
        except Exception as e:
            st.error(f"Erro ao inicializar dashboard: {e}")
            st.stop()

    def run(self):
        st_autorefresh(interval=600000, key="datarefresher") # Atualiza a cada 10 minutos
        
        # Sidebar com informações do usuário
        st.sidebar.title("Gestor Fiscal AI 🤖")
        auth.show_user_info()
        
        st.sidebar.header("Filtros de Período")
        self.data_inicio = st.sidebar.date_input("Data Início", datetime.now() - timedelta(days=30))
        self.data_fim = st.sidebar.date_input("Data Fim", datetime.now())
        
        self.carregar_dados()
        
        # Verificar se usuário é admin para mostrar todas as abas
        user_data = auth.get_current_user()
        is_admin = user_data.get('admin', False)
        
        if is_admin:
            tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
                "📊 Visão Geral", 
                "📄 Análise Detalhada", 
                "💬 Chat Fiscal (Gemini)", 
                "📋 Logs", 
                "📤 Upload de Notas",
                "👥 Gerenciar Usuários"
            ])
            with tab6: self.render_gerenciar_usuarios()
        else:
            tab1, tab2, tab3, tab4, tab5 = st.tabs([
                "📊 Visão Geral", 
                "📄 Análise Detalhada", 
                "💬 Chat Fiscal (Gemini)", 
                "📋 Logs", 
                "📤 Upload de Notas"
            ])
        
        with tab1: self.render_visao_geral()
        with tab2: self.render_analise_detalhada()
        with tab3: self.render_chat_fiscal()
        with tab4: self.render_logs()
        with tab5: self.render_upload_notas()

    def carregar_dados(self):
        filtros = {'data_emissao_inicio': self.data_inicio.isoformat(), 'data_emissao_fim': self.data_fim.isoformat()}
        notas_data = self.db_manager.buscar_dados('notas_fiscais', filtros)
        self.df_notas = pd.DataFrame(notas_data) if notas_data else pd.DataFrame()

    def render_visao_geral(self):
        st.header("Visão Geral do Período")
        if self.df_notas.empty: st.warning("Nenhuma nota fiscal encontrada para o período selecionado."); return
        self.df_notas['valor_total'] = pd.to_numeric(self.df_notas['valor_total'], errors='coerce').fillna(0)
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total de Notas", f"{self.df_notas.shape[0]:,}")
        col2.metric("Valor Total", f"R$ {self.df_notas['valor_total'].sum():,.2f}")
        col3.metric("Ticket Médio", f"R$ {self.df_notas['valor_total'].mean():,.2f}")
        col4.metric("Fornecedores Únicos", f"{self.df_notas['cnpj_emitente'].nunique():,}")
        st.markdown("---")
        col1, col2 = st.columns([1, 1])
        with col1:
            st.subheader("Valor por Fornecedor (Top 10)")
            valor_por_fornecedor = self.df_notas.groupby('nome_emitente')['valor_total'].sum().nlargest(10).sort_values()
            fig = px.bar(valor_por_fornecedor, x='valor_total', y=valor_por_fornecedor.index, orientation='h', text_auto='.2s')
            st.plotly_chart(fig, use_container_width=True)
        with col2:
            st.subheader("Evolução Diária de Notas")
            self.df_notas['data_emissao_dt'] = pd.to_datetime(self.df_notas['data_emissao'])
            notas_por_dia = self.df_notas.groupby(self.df_notas['data_emissao_dt'].dt.date)['valor_total'].sum()
            fig = px.line(notas_por_dia, x=notas_por_dia.index, y='valor_total', markers=True)
            st.plotly_chart(fig, use_container_width=True)

    def render_analise_detalhada(self):
        st.header("Análise Detalhada das Notas Fiscais")
        if self.df_notas.empty: st.warning("Nenhuma nota fiscal para exibir."); return
        st.dataframe(self.df_notas, use_container_width=True, hide_index=True)
        st.subheader("Exportar Dados")
        col1, col2 = st.columns(2)
        if col1.button("Exportar para Excel"):
            with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
                self.df_notas.to_excel(tmp.name, index=False)
                st.download_button("Clique para baixar o Excel", data=Path(tmp.name).read_bytes(), file_name="notas_fiscais.xlsx")
        if col2.button("Exportar para CSV"):
             st.download_button("Clique para baixar o CSV", data=self.df_notas.to_csv(index=False, sep=';').encode('utf-8'), file_name="notas_fiscais.csv", mime='text/csv')

    def render_chat_fiscal(self):
        st.header("Converse com seus Dados Fiscais")
        if not self.config.GEMINI_API_KEY or "AIza" not in self.config.GEMINI_API_KEY:
            st.error("A chave da API do Gemini não foi configurada."); return
        try: gemini_chat = GeminiChat(self.config)
        except ValueError as e: st.error(str(e)); return
        if "messages" not in st.session_state: st.session_state.messages = []
        for message in st.session_state.messages:
            with st.chat_message(message["role"]): st.markdown(message["content"])
        if prompt := st.chat_input("Qual o fornecedor com maior valor?"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"): st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner("Analisando..."):
                    response = gemini_chat.responder_pergunta(prompt, self.df_notas)
                    st.markdown(response)
            st.session_state.messages.append({"role": "assistant", "content": response})

    def render_logs(self):
        st.header("Logs de Processamento")
        logs_data = self.db_manager.buscar_dados('logs_processamento')
        if not logs_data: st.info("Nenhum log de processamento encontrado."); return
        df_logs = pd.DataFrame(logs_data)
        st.dataframe(df_logs, use_container_width=True, hide_index=True)

    def render_upload_notas(self):
        st.header("📤 Upload de Notas Fiscais")
        st.markdown("Faça upload de suas notas fiscais em formato PDF, XML, CSV ou ZIP para análise automática.")
        
        # Seção de upload
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.subheader("Selecionar Arquivos")
            uploaded_files = st.file_uploader(
                "Escolha os arquivos de notas fiscais",
                type=['pdf', 'xml', 'csv', 'zip'],
                accept_multiple_files=True,
                help="Formatos aceitos: PDF (DANFE), XML (NFe), CSV (dados estruturados), ZIP (múltiplos arquivos)"
            )
            
        with col2:
            st.subheader("Informações")
            st.info("**Formatos Suportados:**\n\n"
                   "📄 **PDF**: DANFE (Documento Auxiliar da Nota Fiscal Eletrônica)\n\n"
                   "📋 **XML**: Arquivo XML da NFe\n\n"
                   "📊 **CSV**: Dados estruturados com colunas específicas\n\n"
                   "📦 **ZIP**: Múltiplos arquivos compactados (PDF/XML/CSV)")
        
        if uploaded_files:
            st.markdown("---")
            st.subheader(f"📁 Arquivos Selecionados ({len(uploaded_files)})")
            
            # Mostrar lista de arquivos
            for i, file in enumerate(uploaded_files):
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.write(f"📄 {file.name}")
                with col2:
                    st.write(f"{file.size / 1024:.1f} KB")
                with col3:
                    st.write(file.type.split('/')[-1].upper())
            
            st.markdown("---")
            
            # Botão de processamento
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                if st.button("🚀 Processar Arquivos", type="primary", use_container_width=True):
                    self.processar_arquivos_upload(uploaded_files)
        else:
            st.markdown("---")
            st.info("👆 Selecione um ou mais arquivos para começar o processamento.")
            
            # Exemplo de formato CSV
            st.subheader("📋 Formato CSV Esperado")
            st.markdown("Se você optar por upload de CSV, use o seguinte formato:")
            
            exemplo_csv = pd.DataFrame({
                'numero': ['123456', '123457'],
                'serie': ['1', '1'],
                'cnpj_emitente': ['12.345.678/0001-90', '98.765.432/0001-10'],
                'nome_emitente': ['Empresa A Ltda', 'Empresa B S.A.'],
                'data_emissao': ['2024-01-15', '2024-01-16'],
                'valor_total': ['1500.00', '2300.50'],
                'chave_acesso': ['12345678901234567890123456789012345678901234', '98765432109876543210987654321098765432109876'],
                'natureza_operacao': ['Venda', 'Prestação de Serviços']
            })
            
            st.dataframe(exemplo_csv, use_container_width=True, hide_index=True)
            
            # Download do template
            csv_template = exemplo_csv.to_csv(index=False, sep=';')
            st.download_button(
                "📥 Baixar Template CSV",
                data=csv_template.encode('utf-8'),
                file_name="template_notas_fiscais.csv",
                mime="text/csv"
            )

    def processar_arquivos_upload(self, uploaded_files):
        """Processa os arquivos enviados pelo usuário"""
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        resultados = {
            'processados': 0,
            'erros': 0,
            'detalhes': []
        }
        
        total_files = len(uploaded_files)
        
        for i, uploaded_file in enumerate(uploaded_files):
            try:
                # Atualizar progresso
                progress = (i + 1) / total_files
                progress_bar.progress(progress)
                status_text.text(f"Processando: {uploaded_file.name} ({i+1}/{total_files})")
                
                # Ler conteúdo do arquivo
                file_content = uploaded_file.read()
                file_extension = uploaded_file.name.lower().split('.')[-1]
                
                nota_fiscal = None
                
                # Processar baseado no tipo de arquivo
                if file_extension == 'pdf':
                    nota_fiscal = self.processar_pdf_upload(file_content, uploaded_file.name)
                elif file_extension == 'xml':
                    nota_fiscal = self.processar_xml_upload(file_content, uploaded_file.name)
                elif file_extension == 'csv':
                    notas_csv = self.processar_csv_upload(file_content, uploaded_file.name)
                    if notas_csv:
                        for nota in notas_csv:
                            if self.salvar_nota_fiscal(nota):
                                resultados['processados'] += 1
                            else:
                                resultados['erros'] += 1
                        continue
                elif file_extension == 'zip':
                    # Processar arquivo ZIP
                    resultado_zip = self.processar_zip_upload(file_content, uploaded_file.name)
                    resultados['processados'] += resultado_zip['processados']
                    resultados['erros'] += resultado_zip['erros']
                    resultados['detalhes'].extend(resultado_zip['detalhes'])
                    continue
                
                # Salvar nota fiscal individual (PDF/XML)
                if nota_fiscal:
                    if self.salvar_nota_fiscal(nota_fiscal):
                        resultados['processados'] += 1
                        resultados['detalhes'].append(f"✅ {uploaded_file.name}: Processado com sucesso")
                    else:
                        resultados['erros'] += 1
                        resultados['detalhes'].append(f"❌ {uploaded_file.name}: Erro ao salvar no banco")
                else:
                    resultados['erros'] += 1
                    resultados['detalhes'].append(f"❌ {uploaded_file.name}: Erro no processamento")
                    
            except Exception as e:
                resultados['erros'] += 1
                resultados['detalhes'].append(f"❌ {uploaded_file.name}: {str(e)}")
                logger.error(f"Erro ao processar {uploaded_file.name}: {e}")
        
        # Finalizar progresso
        progress_bar.progress(1.0)
        status_text.text("Processamento concluído!")
        
        # Mostrar resultados
        self.mostrar_resultados_processamento(resultados)
        
        # Recarregar dados
        self.carregar_dados()

    def processar_pdf_upload(self, file_content, filename):
        """Processa arquivo PDF usando a classe PDFExtractor existente"""
        try:
            return PDFExtractor.extrair_dados_pdf(file_content)
        except Exception as e:
            logger.error(f"Erro ao processar PDF {filename}: {e}")
            return None

    def processar_xml_upload(self, file_content, filename):
        """Processa arquivo XML usando a classe XMLExtractor existente"""
        try:
            return XMLExtractor.extrair_dados_xml(file_content, filename)
        except Exception as e:
            logger.error(f"Erro ao processar XML {filename}: {e}")
            return None

    def processar_csv_upload(self, file_content, filename):
        """Processa arquivo CSV e retorna lista de notas fiscais"""
        try:
            # Decodificar conteúdo
            try:
                csv_text = file_content.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    csv_text = file_content.decode('latin-1')
                except UnicodeDecodeError:
                    csv_text = file_content.decode('cp1252')
            
            # Tentar diferentes delimitadores
            delimitadores = [';', ',', '\t', '|']
            df = None
            
            for delim in delimitadores:
                try:
                    df = pd.read_csv(io.StringIO(csv_text), sep=delim, on_bad_lines='skip', encoding_errors='ignore')
                    # Verificar se temos pelo menos algumas colunas
                    if len(df.columns) > 1:
                        break
                except Exception as e:
                    logger.warning(f"Erro ao tentar delimitador '{delim}': {e}")
                    continue
            
            if df is None or df.empty:
                st.error(f"Não foi possível processar o arquivo CSV: {filename}")
                return None
            
            # Verificar se é um arquivo de cabeçalho ou itens baseado no nome
            filename_lower = filename.lower()
            
            if 'cabecalho' in filename_lower or 'header' in filename_lower:
                st.info(f"📋 Processando arquivo de CABEÇALHO: {filename}")
                return self._processar_csv_cabecalho(df, filename)
            elif 'itens' in filename_lower or 'items' in filename_lower:
                # VERIFICAÇÃO CRÍTICA: Bloquear processamento de itens se não há notas fiscais
                try:
                    with self.db_manager.engine.connect() as connection:
                        count_query = text("SELECT COUNT(*) FROM notas_fiscais")
                        total_notas = connection.execute(count_query).fetchone()[0]
                        
                        if total_notas == 0:
                            st.error(f"🚫 BLOQUEADO: Arquivo de itens '{filename}' não pode ser processado!")
                            st.error("📋 MOTIVO: Nenhuma nota fiscal encontrada no banco de dados.")
                            st.error("✅ SOLUÇÃO: Processe primeiro o arquivo de cabeçalho.")
                            return []
                        else:
                            st.success(f"✅ Pré-validação OK: {total_notas} notas fiscais encontradas no banco")
                            st.info(f"📦 Processando arquivo de ITENS: {filename}")
                except Exception as e:
                    st.error(f"Erro ao verificar banco de dados: {e}")
                    return []
                
                return self._processar_csv_itens(df, filename)
            else:
                # Processar como CSV tradicional (todas as informações em uma linha)
                st.info(f"📄 Processando arquivo CSV tradicional: {filename}")
                return self._processar_csv_tradicional(df, filename)
            
        except Exception as e:
            logger.error(f"Erro ao processar CSV {filename}: {e}")
            st.error(f"Erro ao processar CSV: {e}")
            return None

    def _processar_csv_cabecalho(self, df, filename):
        """Processa arquivo CSV de cabeçalho de notas fiscais"""
        try:
            logger.info(f"Iniciando processamento de CSV de cabeçalho: {filename}")
            logger.info(f"Colunas disponíveis no CSV: {list(df.columns)}")
            logger.info(f"Número de linhas no CSV: {len(df)}")
            
            # Mapear colunas comuns para cabeçalho (incluindo variações com acentos)
            mapeamento_colunas = {
                'numero': ['numero', 'NÚMERO', 'nf_numero', 'numero_nf', 'num_nf', 'NF_NUMERO'],
                'serie': ['serie', 'SÉRIE', 'serie_nf', 'nf_serie', 'SERIE_NF'],
                'cnpj_emitente': ['cnpj_emitente', 'CNPJ_EMITENTE', 'cnpj_emit', 'emitente_cnpj', 'CPF/CNPJ Emitente'],
                'nome_emitente': ['nome_emitente', 'NOME_EMITENTE', 'razao_emitente', 'emitente_nome', 'NOME EMITENTE', 'RAZÃO SOCIAL EMITENTE'],
                'data_emissao': ['data_emissao', 'DATA_EMISSAO', 'dt_emissao', 'data_emiss', 'DATA EMISSÃO'],
                'valor_total': ['valor_total', 'VALOR_TOTAL', 'vl_total', 'total_nf', 'VALOR NOTA FISCAL'],
                'chave_acesso': ['chave_acesso', 'CHAVE_ACESSO', 'chave_nfe', 'chave', 'CHAVE DE ACESSO'],
                'natureza_operacao': ['natureza_operacao', 'NATUREZA_OPERACAO', 'nat_operacao', 'cfop', 'NATUREZA DA OPERAÇÃO']
            }
            
            # Encontrar colunas correspondentes
            colunas_encontradas = {}
            for campo, possiveis_nomes in mapeamento_colunas.items():
                for nome in possiveis_nomes:
                    if nome in df.columns:
                        colunas_encontradas[campo] = nome
                        logger.info(f"Campo '{campo}' mapeado para coluna '{nome}'")
                        break
            
            logger.info(f"Colunas encontradas: {colunas_encontradas}")
            
            # Verificar se temos pelo menos as colunas essenciais
            essenciais = ['numero', 'cnpj_emitente', 'nome_emitente']
            faltantes = [campo for campo in essenciais if campo not in colunas_encontradas]
            
            if faltantes:
                logger.error(f"Campos essenciais não encontrados: {faltantes}")
                st.warning(f"Arquivo CSV {filename}: Campos essenciais não encontrados: {', '.join(faltantes)}")
                st.info(f"Colunas disponíveis: {', '.join(df.columns.tolist())}")
                return []
            
            # Converter para lista de NotaFiscal
            notas = []
            for _, row in df.iterrows():
                try:
                    # Processar data_emissao
                    data_emissao = datetime.now()
                    if 'data_emissao' in colunas_encontradas:
                        data_emissao_str = str(row.get(colunas_encontradas['data_emissao'], ''))
                        try:
                            if '/' in data_emissao_str:
                                data_emissao = datetime.strptime(data_emissao_str, '%d/%m/%Y')
                            elif '-' in data_emissao_str:
                                data_emissao = datetime.strptime(data_emissao_str, '%Y-%m-%d')
                        except ValueError:
                            logger.warning(f"Formato de data inválido: {data_emissao_str}")
                    
                    # Processar valor total
                    valor_total = 0.0
                    if 'valor_total' in colunas_encontradas:
                        try:
                            valor_str = str(row.get(colunas_encontradas['valor_total'], '0')).replace(',', '.')
                            valor_total = float(valor_str)
                        except (ValueError, TypeError):
                            valor_total = 0.0
                    
                    nota = NotaFiscal(
                        numero=str(row.get(colunas_encontradas['numero'], '')),
                        serie=str(row.get(colunas_encontradas.get('serie', 'serie'), '1')),
                        cnpj_emitente=str(row.get(colunas_encontradas['cnpj_emitente'], '')),
                        nome_emitente=str(row.get(colunas_encontradas['nome_emitente'], '')),
                        data_emissao=data_emissao,
                        valor_total=valor_total,
                        chave_acesso=str(row.get(colunas_encontradas.get('chave_acesso', 'chave_acesso'), '')),
                        natureza_operacao=str(row.get(colunas_encontradas.get('natureza_operacao', 'natureza_operacao'), ''))
                    )
                    notas.append(nota)
                    logger.info(f"Nota fiscal processada: {nota.numero}")
                except Exception as e:
                    logger.warning(f"Erro ao processar linha do CSV de cabeçalho: {e}")
                    continue
            
            logger.info(f"Processamento concluído. Total de notas processadas: {len(notas)}")
            return notas
            
        except Exception as e:
            logger.error(f"Erro ao processar CSV de cabeçalho {filename}: {e}")
            import traceback
            logger.error(f"Traceback completo: {traceback.format_exc()}")
            return []

    def _processar_csv_itens(self, df, filename):
        """Processa arquivo CSV de itens de notas fiscais com validação robusta e mapeamento tolerante a acentos/espaços"""
        try:
            logger.info(f"Iniciando processamento de CSV de itens: {filename}")
            logger.info(f"Colunas disponíveis no CSV de itens: {list(df.columns)}")
            logger.info(f"Número de linhas no CSV de itens: {len(df)}")
            
            # Função para normalizar nomes de colunas (remove acentos, espaços e pontuação)
            def normalizar_nome_coluna(nome: str) -> str:
                try:
                    if not isinstance(nome, str):
                        nome = str(nome)
                    # Remover acentos
                    nome_sem_acentos = ''.join(
                        c for c in unicodedata.normalize('NFKD', nome)
                        if not unicodedata.combining(c)
                    )
                    # Lowercase e substituir separadores por underscore
                    nome_sem_acentos = nome_sem_acentos.lower()
                    nome_sem_acentos = nome_sem_acentos.replace('/', ' ').replace('-', ' ').replace('.', ' ').replace(':', ' ')
                    nome_sem_acentos = re.sub(r'\s+', ' ', nome_sem_acentos).strip()
                    nome_sem_acentos = nome_sem_acentos.replace(' ', '_')
                    return nome_sem_acentos
                except Exception:
                    return str(nome).lower()

            # Criar mapa normalizado das colunas do DataFrame
            mapa_colunas_normalizadas = {normalizar_nome_coluna(c): c for c in df.columns}
            logger.debug(f"Mapa de colunas normalizadas: {mapa_colunas_normalizadas}")

            # Definir sinônimos normalizados para os campos necessários
            sinonimos = {
                'numero_nf': [
                    'numero_nf', 'numero', 'nf_numero', 'numero_nota_fiscal', 'num_nf', 'numero_da_nota_fiscal'
                ],
                'codigo_produto': [
                    'codigo_produto', 'codigo', 'cod_produto', 'cprod', 'numero_produto', 'num_produto',
                    'codigo_item', 'codigo_do_produto', 'numero_do_produto'
                ],
                'descricao': [
                    'descricao', 'descricao_produto', 'xprod', 'produto', 'descricao_do_produto',
                    'descricao_do_item', 'descricao_item', 'item_descricao', 'descricao_prod',
                    'descricao_do_produto_servico', 'descricao_produto_servico', 'produto_servico'
                ],
                'ncm': [
                    'ncm', 'codigo_ncm', 'codigo_ncm_sh', 'codigo_ncmsh', 'ncm_sh', 'ncmsh', 'codigo_ncm_sh'
                ],
                'quantidade': [
                    'quantidade', 'qtd', 'qtde', 'qcom', 'quantidade_item'
                ],
                'valor_unitario': [
                    'valor_unitario', 'vl_unitario', 'preco_unitario', 'vuncom', 'valor_unitario_item', 'preco_unitario_item'
                ],
                'valor_total': [
                    'valor_total', 'vl_total', 'total_item', 'vprod', 'valor_total_item'
                ]
            }

            # Encontrar colunas correspondentes usando normalização
            colunas_encontradas = {}
            for campo, aliases in sinonimos.items():
                for alias in aliases:
                    if alias in mapa_colunas_normalizadas:
                        colunas_encontradas[campo] = mapa_colunas_normalizadas[alias]
                        logger.info(f"Campo '{campo}' mapeado para coluna '{mapa_colunas_normalizadas[alias]}' (alias: {alias})")
                        break
            
            logger.info(f"Colunas encontradas para itens: {colunas_encontradas}")
            
            # Verificar se temos pelo menos as colunas essenciais
            essenciais = ['numero_nf', 'codigo_produto', 'descricao']
            faltantes = [campo for campo in essenciais if campo not in colunas_encontradas]
            
            if faltantes:
                logger.error(f"Campos essenciais não encontrados no arquivo de itens: {faltantes}")
                st.warning(f"Arquivo CSV de itens {filename}: Campos essenciais não encontrados: {', '.join(faltantes)}")
                st.info(f"Colunas disponíveis: {', '.join(df.columns.tolist())}")
                return []
            
            # Verificar quantas notas fiscais existem no banco
            try:
                with self.db_manager.engine.connect() as connection:
                    count_query = text("SELECT COUNT(*) FROM notas_fiscais")
                    total_notas = connection.execute(count_query).fetchone()[0]
                    logger.info(f"Total de notas fiscais no banco: {total_notas}")
                    st.info(f"🔍 Verificação: {total_notas} notas fiscais encontradas no banco de dados")
                    
                    if total_notas == 0:
                        st.error("❌ ERRO: Nenhuma nota fiscal encontrada no banco de dados!")
                        st.error("📋 SOLUÇÃO: O arquivo de cabeçalho deve ser processado ANTES do arquivo de itens.")
                        st.info("💡 Dica: Verifique se o arquivo de cabeçalho foi incluído no ZIP e se foi processado com sucesso.")
                        return []
            except Exception as e:
                logger.error(f"Erro ao contar notas fiscais: {e}")
            
            # Processar itens e associar às notas fiscais
            itens_processados = 0
            erros_processamento = 0
            
            for index, row in df.iterrows():
                try:
                    # Validar número da NF
                    numero_nf_raw = row.get(colunas_encontradas['numero_nf'], '')
                    if pd.isna(numero_nf_raw) or numero_nf_raw == '':
                        logger.debug(f"Linha {index + 1}: Número da NF vazio, pulando")
                        continue
                    
                    numero_nf = str(numero_nf_raw).strip()
                    if not numero_nf:
                        logger.debug(f"Linha {index + 1}: Número da NF vazio após limpeza, pulando")
                        continue
                    
                    # Buscar a nota fiscal correspondente no banco
                    nota_fiscal_id = self.db_manager.buscar_nota_fiscal_por_numero(numero_nf)
                    if not nota_fiscal_id:
                        logger.warning(f"Nota fiscal {numero_nf} não encontrada para o item na linha {index + 1}")
                        erros_processamento += 1
                        continue
                    
                    # Função auxiliar para conversão segura de valores numéricos
                    def converter_valor_numerico(valor, nome_campo, linha):
                        """Converte valor para float de forma segura"""
                        if pd.isna(valor) or valor == '' or valor is None:
                            return 0.0
                        
                        try:
                            # Converter para string e limpar
                            valor_str = str(valor).strip()
                            if not valor_str:
                                return 0.0
                            
                            # Remover caracteres não numéricos exceto vírgula e ponto
                            valor_limpo = re.sub(r'[^\d,.-]', '', valor_str)
                            
                            # Tratar vírgula como separador decimal
                            if ',' in valor_limpo and '.' in valor_limpo:
                                # Se tem ambos, assumir que vírgula é separador decimal
                                valor_limpo = valor_limpo.replace('.', '').replace(',', '.')
                            elif ',' in valor_limpo:
                                valor_limpo = valor_limpo.replace(',', '.')
                            
                            return float(valor_limpo)
                        except (ValueError, TypeError) as e:
                            logger.warning(f"Erro ao converter {nome_campo} na linha {linha}: {valor} -> {e}")
                            return 0.0
                    
                    # Extrair e validar dados do item
                    quantidade = converter_valor_numerico(
                        row.get(colunas_encontradas.get('quantidade', 'quantidade'), 0), 
                        'quantidade', 
                        index + 1
                    )
                    
                    valor_unitario = converter_valor_numerico(
                        row.get(colunas_encontradas.get('valor_unitario', 'valor_unitario'), 0), 
                        'valor_unitario', 
                        index + 1
                    )
                    
                    valor_total = converter_valor_numerico(
                        row.get(colunas_encontradas.get('valor_total', 'valor_total'), 0), 
                        'valor_total', 
                        index + 1
                    )
                    
                    # Se valor_total não estiver preenchido, calcular
                    if valor_total == 0 and quantidade > 0 and valor_unitario > 0:
                        valor_total = quantidade * valor_unitario
                    
                    # Validar dados essenciais
                    codigo_produto = str(row.get(colunas_encontradas['codigo_produto'], '')).strip()
                    descricao = str(row.get(colunas_encontradas['descricao'], '')).strip()
                    
                    if not codigo_produto and not descricao:
                        logger.warning(f"Linha {index + 1}: Código e descrição do produto vazios, pulando")
                        erros_processamento += 1
                        continue
                    
                    # Preparar dados do item
                    item_data = {
                        'nota_fiscal_id': nota_fiscal_id,
                        'codigo': codigo_produto[:100] if codigo_produto else '',  # Limitar tamanho
                        'descricao': descricao[:1000] if descricao else '',  # Limitar tamanho
                        'ncm': str(row.get(colunas_encontradas.get('ncm', 'ncm'), ''))[:20],  # Limitar tamanho
                        'quantidade': quantidade,
                        'valor_unitario': valor_unitario,
                        'valor_total': valor_total
                    }
                    
                    # Salvar item no banco
                    if self.db_manager.salvar_item_nota_fiscal(item_data):
                        itens_processados += 1
                        logger.debug(f"Item da linha {index + 1} processado com sucesso")
                    else:
                        erros_processamento += 1
                        logger.warning(f"Falha ao salvar item da linha {index + 1}")
                    
                except Exception as e:
                    erros_processamento += 1
                    logger.warning(f"Erro ao processar item na linha {index + 1}: {e}")
                    import traceback
                    logger.debug(f"Traceback do erro na linha {index + 1}: {traceback.format_exc()}")
                    continue
            
            # Relatório final
            total_linhas = len(df)
            logger.info(f"Processamento de itens concluído. Total de linhas: {total_linhas}, Itens processados: {itens_processados}, Erros: {erros_processamento}")
            
            if itens_processados > 0:
                st.success(f"📋 Arquivo de itens {filename}: {itens_processados} itens processados com sucesso")
            
            if erros_processamento > 0:
                st.warning(f"⚠️ Arquivo de itens {filename}: {erros_processamento} itens com erro no processamento")
            
            # Retornar lista vazia pois itens não geram notas fiscais diretamente
            return []
            
        except Exception as e:
            logger.error(f"Erro crítico ao processar CSV de itens {filename}: {e}")
            import traceback
            logger.error(f"Traceback completo: {traceback.format_exc()}")
            st.error(f"❌ Erro crítico ao processar arquivo de itens {filename}: {e}")
            return None

    def _processar_csv_tradicional(self, df, filename):
        """Processa arquivo CSV tradicional (todas as informações em uma linha)"""
        try:
            # Validar colunas obrigatórias
            colunas_obrigatorias = ['numero', 'cnpj_emitente', 'nome_emitente', 'data_emissao', 'valor_total']
            colunas_faltantes = [col for col in colunas_obrigatorias if col not in df.columns]
            
            if colunas_faltantes:
                st.warning(f"Arquivo CSV {filename}: Colunas obrigatórias faltantes: {', '.join(colunas_faltantes)}")
                st.info(f"Colunas disponíveis: {', '.join(df.columns.tolist())}")
                return []
            
            # Converter para lista de NotaFiscal
            notas = []
            for _, row in df.iterrows():
                try:
                    # Processar data_emissao corretamente
                    data_emissao_str = str(row.get('data_emissao', datetime.now().date()))
                    try:
                        # Tentar diferentes formatos de data
                        if '/' in data_emissao_str:
                            data_emissao = datetime.strptime(data_emissao_str, '%d/%m/%Y')
                        elif '-' in data_emissao_str:
                            data_emissao = datetime.strptime(data_emissao_str, '%Y-%m-%d')
                        else:
                            data_emissao = datetime.now()
                    except ValueError:
                        logger.warning(f"Formato de data inválido: {data_emissao_str}. Usando data atual.")
                        data_emissao = datetime.now()
                    
                    nota = NotaFiscal(
                        numero=str(row.get('numero', '')),
                        serie=str(row.get('serie', '1')),
                        cnpj_emitente=str(row.get('cnpj_emitente', '')),
                        nome_emitente=str(row.get('nome_emitente', '')),
                        data_emissao=data_emissao,
                        valor_total=float(row.get('valor_total', 0)),
                        chave_acesso=str(row.get('chave_acesso', '')),
                        natureza_operacao=str(row.get('natureza_operacao', ''))
                    )
                    notas.append(nota)
                except Exception as e:
                    logger.warning(f"Erro ao processar linha do CSV: {e}")
                    continue
            
            return notas
            
        except Exception as e:
            logger.error(f"Erro ao processar CSV tradicional {filename}: {e}")
            return []

    def processar_zip_upload(self, file_content, filename):
        """Processa arquivo ZIP e extrai todos os arquivos suportados"""
        resultados = {
            'processados': 0,
            'erros': 0,
            'detalhes': []
        }
        
        try:
            # Criar um objeto BytesIO para o conteúdo do ZIP
            zip_buffer = io.BytesIO(file_content)
            
            with zipfile.ZipFile(zip_buffer, 'r') as zip_ref:
                # Listar arquivos no ZIP
                file_list = zip_ref.namelist()
                st.info(f"📦 Arquivo ZIP '{filename}' contém {len(file_list)} arquivo(s)")
                
                # Separar arquivos por tipo e prioridade
                arquivos_cabecalho = []
                arquivos_itens = []
                outros_arquivos = []
                
                st.info("🔍 **ANÁLISE DOS ARQUIVOS NO ZIP:**")
                
                for file_name in file_list:
                    if file_name.endswith('/'):
                        continue
                    
                    file_lower = file_name.lower()
                    if any(keyword in file_lower for keyword in ['cabecalho', 'header']):
                        arquivos_cabecalho.append(file_name)
                        st.success(f"📋 CABEÇALHO identificado: {file_name}")
                    elif any(keyword in file_lower for keyword in ['itens', 'items']):
                        arquivos_itens.append(file_name)
                        st.info(f"📦 ITENS identificado: {file_name}")
                    else:
                        outros_arquivos.append(file_name)
                        st.info(f"📄 OUTRO arquivo: {file_name}")
                
                # Processar na ordem correta: cabeçalho primeiro, depois outros, depois itens
                arquivos_ordenados = arquivos_cabecalho + outros_arquivos + arquivos_itens
                
                st.success(f"✅ **ORDEM DE PROCESSAMENTO DEFINIDA:**")
                st.success(f"1º → {len(arquivos_cabecalho)} arquivo(s) de cabeçalho")
                st.success(f"2º → {len(outros_arquivos)} outro(s) arquivo(s)")
                st.success(f"3º → {len(arquivos_itens)} arquivo(s) de itens")
                
                # Processar cada arquivo na ordem correta
                for file_name in arquivos_ordenados:
                    try:
                        # Pular diretórios
                        if file_name.endswith('/'):
                            continue
                            
                        # Extrair extensão do arquivo
                        file_extension = file_name.lower().split('.')[-1]
                        
                        # Verificar se é um tipo de arquivo suportado
                        if file_extension not in ['pdf', 'xml', 'csv']:
                            resultados['detalhes'].append(f"⚠️ {file_name}: Tipo de arquivo não suportado")
                            continue
                        
                        # Ler conteúdo do arquivo
                        with zip_ref.open(file_name) as extracted_file:
                            extracted_content = extracted_file.read()
                        
                        # Processar baseado no tipo
                        nota_fiscal = None
                        if file_extension == 'pdf':
                            nota_fiscal = self.processar_pdf_upload(extracted_content, file_name)
                        elif file_extension == 'xml':
                            nota_fiscal = self.processar_xml_upload(extracted_content, file_name)
                        elif file_extension == 'csv':
                            notas_csv = self.processar_csv_upload(extracted_content, file_name)
                            
                            # Verificar se é um arquivo de itens (retorna lista vazia por design)
                            filename_lower = file_name.lower()
                            is_items_file = 'itens' in filename_lower or 'items' in filename_lower
                            
                            if notas_csv is not None:  # Processamento bem-sucedido
                                if notas_csv:  # Arquivo de cabeçalho com notas
                                    for nota in notas_csv:
                                        if self.salvar_nota_fiscal(nota):
                                            resultados['processados'] += 1
                                        else:
                                            resultados['erros'] += 1
                                    resultados['detalhes'].append(f"✅ {file_name}: {len(notas_csv)} nota(s) processada(s)")
                                elif is_items_file:  # Arquivo de itens (lista vazia é esperada)
                                    resultados['processados'] += 1
                                    resultados['detalhes'].append(f"✅ {file_name}: Itens processados com sucesso")
                                else:  # Arquivo CSV vazio ou sem dados válidos
                                    resultados['erros'] += 1
                                    resultados['detalhes'].append(f"❌ {file_name}: Nenhum dado válido encontrado")
                                continue
                            else:  # Erro no processamento (retornou None)
                                resultados['erros'] += 1
                                resultados['detalhes'].append(f"❌ {file_name}: Erro no processamento")
                                continue
                        
                        # Salvar nota fiscal individual (PDF/XML)
                        if nota_fiscal:
                            if self.salvar_nota_fiscal(nota_fiscal):
                                resultados['processados'] += 1
                                resultados['detalhes'].append(f"✅ {file_name}: Processado com sucesso")
                            else:
                                resultados['erros'] += 1
                                resultados['detalhes'].append(f"❌ {file_name}: Erro ao salvar no banco")
                        else:
                            resultados['erros'] += 1
                            resultados['detalhes'].append(f"❌ {file_name}: Erro no processamento")
                            
                    except Exception as e:
                        resultados['erros'] += 1
                        resultados['detalhes'].append(f"❌ {file_name}: {str(e)}")
                        logger.error(f"Erro ao processar arquivo {file_name} do ZIP: {e}")
                        
        except zipfile.BadZipFile:
            resultados['erros'] += 1
            resultados['detalhes'].append(f"❌ {filename}: Arquivo ZIP corrompido ou inválido")
            st.error(f"Arquivo ZIP '{filename}' está corrompido ou não é um arquivo ZIP válido")
        except Exception as e:
            resultados['erros'] += 1
            resultados['detalhes'].append(f"❌ {filename}: {str(e)}")
            logger.error(f"Erro ao processar ZIP {filename}: {e}")
            st.error(f"Erro ao processar ZIP: {e}")
        
        return resultados

    def salvar_nota_fiscal(self, nota_fiscal):
        """Salva nota fiscal no banco de dados"""
        try:
            return self.db_manager.salvar_nota_fiscal(nota_fiscal)
        except Exception as e:
            logger.error(f"Erro ao salvar nota fiscal: {e}")
            return False

    def mostrar_resultados_processamento(self, resultados):
        """Mostra os resultados do processamento"""
        st.markdown("---")
        st.subheader("📊 Resultados do Processamento")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("✅ Processados", resultados['processados'])
        with col2:
            st.metric("❌ Erros", resultados['erros'])
        with col3:
            st.metric("📁 Total", resultados['processados'] + resultados['erros'])
        
        if resultados['detalhes']:
            st.subheader("📋 Detalhes")
            for detalhe in resultados['detalhes']:
                if "✅" in detalhe:
                    st.success(detalhe)
                else:
                    st.error(detalhe)
    
    def render_gerenciar_usuarios(self):
        """Renderiza interface de gerenciamento de usuários (apenas para admins)"""
        st.header("👥 Gerenciamento de Usuários")
        
        # Verificar se é admin
        if not auth.is_admin():
            st.error("❌ Acesso negado. Apenas administradores podem acessar esta seção.")
            return
        
        # Abas para diferentes ações
        tab_listar, tab_criar, tab_gerenciar = st.tabs(["📋 Listar Usuários", "➕ Criar Usuário", "⚙️ Gerenciar"])
        
        with tab_listar:
            st.subheader("📋 Lista de Usuários")
            usuarios = auth.user_manager.list_users()
            
            if usuarios:
                df_usuarios = pd.DataFrame(usuarios)
                
                # Formatar dados para exibição
                df_display = df_usuarios.copy()
                df_display['ativo'] = df_display['ativo'].map({True: '✅ Ativo', False: '❌ Inativo'})
                df_display['admin'] = df_display['admin'].map({True: '👑 Admin', False: '👤 Usuário'})
                
                # Formatar datas
                if 'data_criacao' in df_display.columns:
                    df_display['data_criacao'] = pd.to_datetime(df_display['data_criacao']).dt.strftime('%d/%m/%Y %H:%M')
                if 'ultimo_login' in df_display.columns:
                    df_display['ultimo_login'] = pd.to_datetime(df_display['ultimo_login'], errors='coerce').dt.strftime('%d/%m/%Y %H:%M')
                    df_display['ultimo_login'] = df_display['ultimo_login'].fillna('Nunca')
                
                # Renomear colunas
                df_display = df_display.rename(columns={
                    'id': 'ID',
                    'username': 'Usuário',
                    'email': 'Email',
                    'nome_completo': 'Nome Completo',
                    'ativo': 'Status',
                    'admin': 'Tipo',
                    'data_criacao': 'Criado em',
                    'ultimo_login': 'Último Login'
                })
                
                st.dataframe(df_display, use_container_width=True)
                
                # Estatísticas
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("👥 Total de Usuários", len(usuarios))
                with col2:
                    ativos = sum(1 for u in usuarios if u['ativo'])
                    st.metric("✅ Usuários Ativos", ativos)
                with col3:
                    admins = sum(1 for u in usuarios if u['admin'])
                    st.metric("👑 Administradores", admins)
                with col4:
                    inativos = len(usuarios) - ativos
                    st.metric("❌ Usuários Inativos", inativos)
            else:
                st.info("Nenhum usuário encontrado.")
        
        with tab_criar:
            st.subheader("➕ Criar Novo Usuário")
            
            with st.form("criar_usuario_admin"):
                col1, col2 = st.columns(2)
                
                with col1:
                    username = st.text_input("Nome de Usuário*", placeholder="usuario123")
                    email = st.text_input("Email*", placeholder="usuario@empresa.com")
                    nome_completo = st.text_input("Nome Completo", placeholder="João da Silva")
                
                with col2:
                    password = st.text_input("Senha*", type="password", placeholder="Senha segura")
                    password_confirm = st.text_input("Confirmar Senha*", type="password")
                    admin = st.checkbox("Usuário Administrador")
                
                # Critérios de senha
                with st.expander("📋 Critérios de Senha"):
                    st.markdown("""
                    - Mínimo 8 caracteres
                    - Pelo menos 1 letra maiúscula
                    - Pelo menos 1 letra minúscula  
                    - Pelo menos 1 número
                    - Pelo menos 1 caractere especial
                    """)
                
                criar_btn = st.form_submit_button("➕ Criar Usuário", use_container_width=True)
                
                if criar_btn:
                    if not all([username, email, password, password_confirm]):
                        st.error("❌ Preencha todos os campos obrigatórios")
                    elif password != password_confirm:
                        st.error("❌ As senhas não coincidem")
                    else:
                        success, message = auth.user_manager.create_user(
                            username=username,
                            email=email,
                            password=password,
                            nome_completo=nome_completo,
                            admin=admin
                        )
                        
                        if success:
                            st.success(f"✅ {message}")
                            st.rerun()
                        else:
                            st.error(f"❌ {message}")
        
        with tab_gerenciar:
            st.subheader("⚙️ Gerenciar Usuários")
            
            usuarios = auth.user_manager.list_users()
            if usuarios:
                # Selecionar usuário
                user_options = {f"{u['username']} ({u['email']})": u['id'] for u in usuarios}
                selected_user_display = st.selectbox("Selecionar Usuário", list(user_options.keys()))
                
                if selected_user_display:
                    selected_user_id = user_options[selected_user_display]
                    selected_user = next(u for u in usuarios if u['id'] == selected_user_id)
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown("**Informações do Usuário:**")
                        st.write(f"**ID:** {selected_user['id']}")
                        st.write(f"**Usuário:** {selected_user['username']}")
                        st.write(f"**Email:** {selected_user['email']}")
                        st.write(f"**Nome:** {selected_user.get('nome_completo', 'N/A')}")
                        st.write(f"**Status:** {'✅ Ativo' if selected_user['ativo'] else '❌ Inativo'}")
                        st.write(f"**Tipo:** {'👑 Admin' if selected_user['admin'] else '👤 Usuário'}")
                    
                    with col2:
                        st.markdown("**Ações:**")
                        
                        # Não permitir desativar o próprio usuário
                        current_user = auth.get_current_user()
                        is_self = current_user['id'] == selected_user['id']
                        
                        if selected_user['ativo'] and not is_self:
                            if st.button("❌ Desativar Usuário", key=f"deactivate_{selected_user_id}"):
                                success, message = auth.user_manager.deactivate_user(selected_user_id)
                                if success:
                                    st.success(f"✅ {message}")
                                    st.rerun()
                                else:
                                    st.error(f"❌ {message}")
                        
                        if is_self:
                            st.info("ℹ️ Você não pode desativar sua própria conta")
                        
                        # Resetar senha
                        with st.expander("🔑 Resetar Senha"):
                            with st.form(f"reset_password_{selected_user_id}"):
                                new_password = st.text_input("Nova Senha", type="password")
                                new_password_confirm = st.text_input("Confirmar Nova Senha", type="password")
                                
                                reset_btn = st.form_submit_button("🔑 Resetar Senha")
                                
                                if reset_btn:
                                    if not new_password or not new_password_confirm:
                                        st.error("❌ Preencha ambos os campos de senha")
                                    elif new_password != new_password_confirm:
                                        st.error("❌ As senhas não coincidem")
                                    else:
                                        success, message = auth.user_manager.update_user_password(
                                            selected_user_id, new_password
                                        )
                                        if success:
                                            st.success(f"✅ {message}")
                                        else:
                                            st.error(f"❌ {message}")
            else:
                st.info("Nenhum usuário encontrado para gerenciar.")

if __name__ == "__main__":
    try:
        dashboard = Dashboard()
        dashboard.run()
    except Exception as e:
        logger.critical(f"A aplicação principal falhou: {e}")
        st.error(f"Ocorreu um erro crítico na aplicação. Verifique os logs.")
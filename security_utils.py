# security_utils.py
# Módulo centralizado para funções de segurança e validação

import re
import logging
import hashlib
from typing import Optional, Dict, Any, List
from datetime import datetime
import bleach
import validators
from defusedxml import ElementTree as ET
from defusedxml.ElementTree import ParseError
from xml.etree.ElementTree import Element  # Para type hints

logger = logging.getLogger(__name__)

class SecurityConfig:
    """Configurações de segurança centralizadas"""
    
    # Tamanhos máximos de arquivo (em bytes)
    MAX_XML_SIZE = 10 * 1024 * 1024  # 10MB
    MAX_PDF_SIZE = 50 * 1024 * 1024  # 50MB
    
    # Limites de processamento
    MAX_ITEMS_PER_NF = 1000
    MAX_STRING_LENGTH = 1000
    
    # Padrões de validação
    CNPJ_PATTERN = re.compile(r'^\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}$|^\d{14}$')
    CHAVE_ACESSO_PATTERN = re.compile(r'^\d{44}$')
    
    # Tags XML permitidas para sanitização
    ALLOWED_XML_TAGS = [
        'infNFe', 'ide', 'emit', 'dest', 'det', 'prod', 'total', 'ICMSTot',
        'nNF', 'serie', 'dhEmi', 'CNPJ', 'xNome', 'cProd', 'xProd', 'NCM',
        'qCom', 'vUnCom', 'vProd', 'vNF', 'vICMS', 'vIPI', 'vPIS', 'vCOFINS', 'natOp'
    ]

class XMLSecurityValidator:
    """Validador seguro para processamento de XML"""
    
    @staticmethod
    def validate_xml_size(xml_content: bytes) -> bool:
        """Valida o tamanho do arquivo XML"""
        if len(xml_content) > SecurityConfig.MAX_XML_SIZE:
            logger.warning(f"XML rejeitado: tamanho {len(xml_content)} excede limite de {SecurityConfig.MAX_XML_SIZE}")
            return False
        return True
    
    @staticmethod
    def parse_xml_safely(xml_content: bytes) -> Optional[Element]:
        """Parse seguro de XML usando defusedxml"""
        try:
            # Validar tamanho primeiro
            if not XMLSecurityValidator.validate_xml_size(xml_content):
                return None
            
            # Decodificar com tratamento de erro
            try:
                xml_string = xml_content.decode('utf-8', errors='strict')
            except UnicodeDecodeError:
                logger.warning("XML rejeitado: encoding inválido")
                return None
            
            # Parse seguro com defusedxml
            root = ET.fromstring(xml_string)
            
            # Validar estrutura básica
            if not XMLSecurityValidator._validate_xml_structure(root):
                return None
                
            logger.info("XML processado com segurança")
            return root
            
        except ParseError as e:
            logger.error(f"Erro de parsing XML: {e}")
            return None
        except Exception as e:
            logger.error(f"Erro inesperado no processamento XML: {e}")
            return None
    
    @staticmethod
    def _validate_xml_structure(root: Element) -> bool:
        """Valida a estrutura básica do XML da NF-e"""
        # Verificar se é um XML de NF-e válido (considerando namespace)
        valid_tags = ['nfeProc', 'NFe']
        root_tag_local = root.tag.split('}')[-1] if '}' in root.tag else root.tag
        
        if root_tag_local not in valid_tags:
            logger.warning(f"XML rejeitado: não é uma estrutura de NF-e válida (tag: {root.tag})")
            return False
        
        # Verificar presença de elementos obrigatórios
        ns = {'nfe': 'http://www.portalfiscal.inf.br/nfe'}
        inf_nfe = root.find('.//nfe:infNFe', ns)
        if inf_nfe is None:
            inf_nfe = root.find('.//infNFe')
        
        if inf_nfe is None:
            logger.warning("XML rejeitado: elemento infNFe não encontrado")
            return False
        
        return True

class DataSanitizer:
    """Sanitizador de dados de entrada"""
    
    @staticmethod
    def sanitize_string(value: str, max_length: int = SecurityConfig.MAX_STRING_LENGTH) -> str:
        """Sanitiza strings removendo caracteres perigosos"""
        if not value:
            return ""
        
        # Limitar tamanho
        value = value[:max_length]
        
        # Remover caracteres de controle
        value = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', value)
        
        # Sanitizar HTML/XML
        value = bleach.clean(value, tags=[], strip=True)
        
        # Normalizar espaços
        value = re.sub(r'\s+', ' ', value).strip()
        
        return value
    
    @staticmethod
    def sanitize_cnpj(cnpj: str) -> Optional[str]:
        """Sanitiza e valida CNPJ"""
        if not cnpj:
            return None
        
        # Remover caracteres não numéricos
        cnpj_clean = re.sub(r'[^\d]', '', cnpj)
        
        # Validar formato
        if len(cnpj_clean) != 14:
            logger.warning(f"CNPJ inválido: {cnpj}")
            return None
        
        # Formatar
        return f"{cnpj_clean[:2]}.{cnpj_clean[2:5]}.{cnpj_clean[5:8]}/{cnpj_clean[8:12]}-{cnpj_clean[12:14]}"
    
    @staticmethod
    def sanitize_chave_acesso(chave: str) -> Optional[str]:
        """Sanitiza e valida chave de acesso"""
        if not chave:
            return None
        
        # Remover caracteres não numéricos e prefixos
        chave_clean = re.sub(r'[^\d]', '', chave.replace('NFe', ''))
        
        # Validar formato
        if len(chave_clean) != 44:
            logger.warning(f"Chave de acesso inválida: {chave}")
            return None
        
        return chave_clean
    
    @staticmethod
    def sanitize_numeric_value(value: Any) -> float:
        """Sanitiza valores numéricos"""
        if value is None:
            return 0.0
        
        try:
            if isinstance(value, str):
                # Remover caracteres não numéricos exceto ponto e vírgula
                value_clean = re.sub(r'[^\d.,\-]', '', value)
                # Substituir vírgula por ponto
                value_clean = value_clean.replace(',', '.')
                return float(value_clean)
            return float(value)
        except (ValueError, TypeError):
            logger.warning(f"Valor numérico inválido: {value}")
            return 0.0

class SecurityAuditor:
    """Auditor de segurança para logging de eventos"""
    
    @staticmethod
    def log_security_event(event_type: str, details: Dict[str, Any], severity: str = "INFO"):
        """Registra eventos de segurança"""
        timestamp = datetime.now().isoformat()
        event_hash = hashlib.sha256(str(details).encode()).hexdigest()[:8]
        
        log_entry = {
            "timestamp": timestamp,
            "event_type": event_type,
            "severity": severity,
            "event_id": event_hash,
            "details": details
        }
        
        if severity == "WARNING":
            logger.warning(f"SECURITY_EVENT: {log_entry}")
        elif severity == "ERROR":
            logger.error(f"SECURITY_EVENT: {log_entry}")
        else:
            logger.info(f"SECURITY_EVENT: {log_entry}")
    
    @staticmethod
    def log_file_processing(filename: str, file_size: int, file_type: str, success: bool):
        """Registra processamento de arquivos"""
        SecurityAuditor.log_security_event(
            "FILE_PROCESSING",
            {
                "filename": filename,
                "file_size": file_size,
                "file_type": file_type,
                "success": success
            },
            "INFO" if success else "WARNING"
        )

class RateLimiter:
    """Limitador de taxa para prevenir abuso"""
    
    def __init__(self):
        self._requests = {}
    
    def is_allowed(self, identifier: str, max_requests: int = 100, window_minutes: int = 60) -> bool:
        """Verifica se a requisição está dentro do limite"""
        now = datetime.now()
        window_start = now.timestamp() - (window_minutes * 60)
        
        # Limpar requisições antigas
        if identifier in self._requests:
            self._requests[identifier] = [
                req_time for req_time in self._requests[identifier] 
                if req_time > window_start
            ]
        else:
            self._requests[identifier] = []
        
        # Verificar limite
        if len(self._requests[identifier]) >= max_requests:
            SecurityAuditor.log_security_event(
                "RATE_LIMIT_EXCEEDED",
                {"identifier": identifier, "requests": len(self._requests[identifier])},
                "WARNING"
            )
            return False
        
        # Adicionar requisição atual
        self._requests[identifier].append(now.timestamp())
        return True

# Instância global do rate limiter
rate_limiter = RateLimiter()
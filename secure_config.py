"""
Módulo de configuração segura para o Agente Fiscal com IA
Gerencia credenciais e configurações sensíveis de forma segura
"""

import os
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any
from pathlib import Path
import hashlib
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

class SecureConfigError(Exception):
    """Exceção para erros de configuração segura"""
    pass

class CredentialManager:
    """Gerenciador seguro de credenciais"""
    
    def __init__(self):
        self._encryption_key = None
        self._initialize_encryption()
    
    def _initialize_encryption(self):
        """Inicializa a chave de criptografia"""
        try:
            # Tenta carregar chave existente ou cria uma nova
            key_file = Path(".encryption_key")
            if key_file.exists():
                with open(key_file, "rb") as f:
                    self._encryption_key = f.read()
            else:
                # Gera nova chave baseada em informações do sistema
                system_info = f"{os.getenv('COMPUTERNAME', 'default')}{os.getenv('USERNAME', 'user')}"
                password = system_info.encode()
                salt = b'agente_fiscal_salt_2024'
                
                kdf = PBKDF2HMAC(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=salt,
                    iterations=100000,
                )
                self._encryption_key = base64.urlsafe_b64encode(kdf.derive(password))
                
                # Salva a chave (em produção, usar um cofre de chaves)
                with open(key_file, "wb") as f:
                    f.write(self._encryption_key)
                
                # Torna o arquivo oculto no Windows
                if os.name == 'nt':
                    os.system(f'attrib +h "{key_file}"')
                    
        except Exception as e:
            logger.error(f"Erro ao inicializar criptografia: {e}")
            raise SecureConfigError("Falha na inicialização da criptografia")
    
    def encrypt_credential(self, credential: str) -> str:
        """Criptografa uma credencial"""
        try:
            fernet = Fernet(self._encryption_key)
            encrypted = fernet.encrypt(credential.encode())
            return base64.urlsafe_b64encode(encrypted).decode()
        except Exception as e:
            logger.error(f"Erro ao criptografar credencial: {e}")
            raise SecureConfigError("Falha na criptografia")
    
    def decrypt_credential(self, encrypted_credential: str) -> str:
        """Descriptografa uma credencial"""
        try:
            fernet = Fernet(self._encryption_key)
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_credential.encode())
            decrypted = fernet.decrypt(encrypted_bytes)
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Erro ao descriptografar credencial: {e}")
            raise SecureConfigError("Falha na descriptografia")

@dataclass
class SecureConfig:
    """Configuração segura do sistema"""
    
    # Configurações de Email
    IMAP_SERVER: str
    IMAP_PORT: int
    EMAIL_USER: str
    EMAIL_PASSWORD: str
    
    # Configurações de Banco de Dados
    DATABASE_URL: str
    
    # Configurações de API
    GEMINI_API_KEY: str
    
    # Configurações de Segurança
    MAX_LOGIN_ATTEMPTS: int = 3
    SESSION_TIMEOUT_MINUTES: int = 30
    ENABLE_AUDIT_LOG: bool = True
    REQUIRE_STRONG_PASSWORDS: bool = True
    
    # Configurações de Rate Limiting
    MAX_EMAILS_PER_HOUR: int = 100
    MAX_FILES_PER_REQUEST: int = 10
    MAX_FILE_SIZE_MB: int = 50
    
    def __post_init__(self):
        """Validação pós-inicialização"""
        self._validate_configuration()
        self._mask_sensitive_data()
    
    def _validate_configuration(self):
        """Valida as configurações obrigatórias"""
        required_configs = {
            'EMAIL_USER': self.EMAIL_USER,
            'EMAIL_PASSWORD': self.EMAIL_PASSWORD,
            'DATABASE_URL': self.DATABASE_URL
        }
        
        missing_configs = [key for key, value in required_configs.items() if not value]
        
        if missing_configs:
            raise SecureConfigError(
                f"Configurações obrigatórias ausentes: {', '.join(missing_configs)}"
            )
        
        # Validar formato do email
        if '@' not in self.EMAIL_USER:
            raise SecureConfigError("EMAIL_USER deve ser um endereço de email válido")
        
        # Validar URL do banco
        if not self.DATABASE_URL.startswith(('postgresql://', 'mysql://', 'sqlite://')):
            raise SecureConfigError("DATABASE_URL deve ser uma URL de banco válida")
    
    def _mask_sensitive_data(self):
        """Mascara dados sensíveis para logs"""
        self._masked_password = self._mask_string(self.EMAIL_PASSWORD)
        self._masked_db_url = self._mask_database_url(self.DATABASE_URL)
        self._masked_api_key = self._mask_string(self.GEMINI_API_KEY)
    
    def _mask_string(self, value: str, show_chars: int = 3) -> str:
        """Mascara uma string mostrando apenas alguns caracteres"""
        if not value:
            return "***VAZIO***"
        if len(value) <= show_chars * 2:
            return "*" * len(value)
        return f"{value[:show_chars]}{'*' * (len(value) - show_chars * 2)}{value[-show_chars:]}"
    
    def _mask_database_url(self, url: str) -> str:
        """Mascara a URL do banco preservando informações não sensíveis"""
        if not url:
            return "***VAZIO***"
        
        # Exemplo: postgresql://user:pass@host:port/db -> postgresql://user:***@host:port/db
        parts = url.split('@')
        if len(parts) == 2:
            auth_part = parts[0]
            host_part = parts[1]
            
            if ':' in auth_part:
                protocol_user = auth_part.rsplit(':', 1)[0]
                return f"{protocol_user}:***@{host_part}"
        
        return self._mask_string(url)
    
    def get_safe_config_summary(self) -> Dict[str, Any]:
        """Retorna um resumo seguro das configurações para logs"""
        return {
            'IMAP_SERVER': self.IMAP_SERVER,
            'IMAP_PORT': self.IMAP_PORT,
            'EMAIL_USER': self.EMAIL_USER,
            'EMAIL_PASSWORD': self._masked_password,
            'DATABASE_URL': self._masked_db_url,
            'GEMINI_API_KEY': self._masked_api_key,
            'MAX_LOGIN_ATTEMPTS': self.MAX_LOGIN_ATTEMPTS,
            'SESSION_TIMEOUT_MINUTES': self.SESSION_TIMEOUT_MINUTES,
            'ENABLE_AUDIT_LOG': self.ENABLE_AUDIT_LOG,
            'MAX_EMAILS_PER_HOUR': self.MAX_EMAILS_PER_HOUR,
            'MAX_FILES_PER_REQUEST': self.MAX_FILES_PER_REQUEST,
            'MAX_FILE_SIZE_MB': self.MAX_FILE_SIZE_MB
        }

class ConfigurationLoader:
    """Carregador seguro de configurações"""
    
    def __init__(self):
        self.credential_manager = CredentialManager()
        self._load_environment()
    
    def _load_environment(self):
        """Carrega variáveis de ambiente"""
        env_file = Path('.env')
        if env_file.exists():
            try:
                with open(env_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, value = line.split('=', 1)
                            os.environ[key.strip()] = value.strip().strip('"\'')
            except Exception as e:
                logger.warning(f"Erro ao carregar arquivo .env: {e}")
    
    def load_config(self) -> SecureConfig:
        """Carrega a configuração segura"""
        try:
            config = SecureConfig(
                IMAP_SERVER=os.getenv("IMAP_SERVER", "imap.gmail.com"),
                IMAP_PORT=int(os.getenv("IMAP_PORT", "993")),
                EMAIL_USER=os.getenv("EMAIL_USER", ""),
                EMAIL_PASSWORD=os.getenv("EMAIL_PASSWORD", ""),
                DATABASE_URL=os.getenv("DATABASE_URL", ""),
                GEMINI_API_KEY=os.getenv("GEMINI_API_KEY", ""),
                MAX_LOGIN_ATTEMPTS=int(os.getenv("MAX_LOGIN_ATTEMPTS", "3")),
                SESSION_TIMEOUT_MINUTES=int(os.getenv("SESSION_TIMEOUT_MINUTES", "30")),
                ENABLE_AUDIT_LOG=os.getenv("ENABLE_AUDIT_LOG", "true").lower() == "true",
                REQUIRE_STRONG_PASSWORDS=os.getenv("REQUIRE_STRONG_PASSWORDS", "true").lower() == "true",
                MAX_EMAILS_PER_HOUR=int(os.getenv("MAX_EMAILS_PER_HOUR", "100")),
                MAX_FILES_PER_REQUEST=int(os.getenv("MAX_FILES_PER_REQUEST", "10")),
                MAX_FILE_SIZE_MB=int(os.getenv("MAX_FILE_SIZE_MB", "50"))
            )
            
            logger.info("Configuração carregada com sucesso")
            logger.debug(f"Resumo da configuração: {config.get_safe_config_summary()}")
            
            return config
            
        except Exception as e:
            logger.error(f"Erro ao carregar configuração: {e}")
            raise SecureConfigError(f"Falha no carregamento da configuração: {e}")
    
    def validate_environment(self) -> bool:
        """Valida se o ambiente está configurado corretamente"""
        try:
            config = self.load_config()
            logger.info("✅ Ambiente configurado corretamente")
            return True
        except SecureConfigError as e:
            logger.error(f"❌ Erro na configuração do ambiente: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Erro inesperado na validação: {e}")
            return False

# Instância global do carregador de configuração
config_loader = ConfigurationLoader()

def get_secure_config() -> SecureConfig:
    """Função utilitária para obter a configuração segura"""
    return config_loader.load_config()

def validate_environment() -> bool:
    """Função utilitária para validar o ambiente"""
    return config_loader.validate_environment()
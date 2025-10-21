"""
Sistema de Gerenciamento de Usuários e Autenticação
Responsável por criar, autenticar e gerenciar usuários do sistema.
"""

import hashlib
import secrets
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
import sqlite3
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from security_utils import SecurityConfig
from secure_config import CredentialManager, get_secure_config

# Carregar variáveis de ambiente
load_dotenv()

class UserManager:
    """Gerenciador de usuários e autenticação"""
    
    def __init__(self):
        self.database_url = os.getenv('DATABASE_URL', 'sqlite:///notas_fiscais.db')
        self.engine = create_engine(self.database_url)
        self.security_config = get_secure_config()
        self.credential_manager = CredentialManager()
        self._create_users_table_if_not_exists()
        
    def _create_users_table_if_not_exists(self):
        """Cria a tabela de usuários se ela não existir"""
        try:
            with self.engine.connect() as conn:
                # Detectar tipo de banco de dados
                if 'postgresql' in self.database_url:
                    # Sintaxe PostgreSQL
                    conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS usuarios (
                        id SERIAL PRIMARY KEY,
                        username VARCHAR(50) UNIQUE NOT NULL,
                        email VARCHAR(100) UNIQUE NOT NULL,
                        password_hash VARCHAR(255) NOT NULL,
                        nome_completo VARCHAR(255),
                        ativo BOOLEAN DEFAULT TRUE,
                        admin BOOLEAN DEFAULT FALSE,
                        data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        ultimo_login TIMESTAMP,
                        tentativas_login INTEGER DEFAULT 0,
                        bloqueado_ate TIMESTAMP
                    )
                    """))
                else:
                    # Sintaxe SQLite
                    conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS usuarios (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username VARCHAR(50) UNIQUE NOT NULL,
                        email VARCHAR(100) UNIQUE NOT NULL,
                        password_hash VARCHAR(255) NOT NULL,
                        nome_completo VARCHAR(255),
                        ativo BOOLEAN DEFAULT 1,
                        admin BOOLEAN DEFAULT 0,
                        data_criacao DATETIME DEFAULT CURRENT_TIMESTAMP,
                        ultimo_login DATETIME,
                        tentativas_login INTEGER DEFAULT 0,
                        bloqueado_ate DATETIME
                    )
                    """))
                conn.commit()
        except Exception as e:
            print(f"Erro ao criar tabela de usuários: {e}")
        
    def _hash_password(self, password: str, salt: str = None) -> Tuple[str, str]:
        """Gera hash seguro da senha com salt"""
        if salt is None:
            salt = secrets.token_hex(32)
        
        # Usar PBKDF2 com SHA-256 para hash da senha
        password_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000  # 100,000 iterações
        )
        
        return password_hash.hex(), salt
    
    def _verify_password(self, password: str, stored_hash: str, salt: str) -> bool:
        """Verifica se a senha está correta"""
        password_hash, _ = self._hash_password(password, salt)
        return secrets.compare_digest(password_hash, stored_hash)
    
    def _validate_password_strength(self, password: str) -> Tuple[bool, str]:
        """Valida se a senha atende aos critérios de segurança"""
        if len(password) < 8:
            return False, "A senha deve ter pelo menos 8 caracteres"
        
        if not re.search(r'[A-Z]', password):
            return False, "A senha deve conter pelo menos uma letra maiúscula"
        
        if not re.search(r'[a-z]', password):
            return False, "A senha deve conter pelo menos uma letra minúscula"
        
        if not re.search(r'\d', password):
            return False, "A senha deve conter pelo menos um número"
        
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            return False, "A senha deve conter pelo menos um caractere especial"
        
        return True, "Senha válida"
    
    def _validate_email(self, email: str) -> bool:
        """Valida formato do email"""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None
    
    def _is_user_blocked(self, user_data: Dict) -> bool:
        """Verifica se o usuário está bloqueado"""
        if user_data.get('bloqueado_ate'):
            bloqueado_ate = datetime.fromisoformat(user_data['bloqueado_ate'])
            return datetime.now() < bloqueado_ate
        return False
    
    def create_user(self, username: str, email: str, password: str, 
                   nome_completo: str = None, admin: bool = False) -> Tuple[bool, str]:
        """Cria um novo usuário"""
        try:
            # Validações
            if not username or len(username) < 3:
                return False, "Nome de usuário deve ter pelo menos 3 caracteres"
            
            if not self._validate_email(email):
                return False, "Email inválido"
            
            is_valid, message = self._validate_password_strength(password)
            if not is_valid:
                return False, message
            
            # Verificar se usuário já existe
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT id FROM usuarios WHERE username = :username OR email = :email"),
                    {"username": username, "email": email}
                )
                if result.fetchone():
                    return False, "Usuário ou email já existe"
                
                # Criar hash da senha
                password_hash, salt = self._hash_password(password)
                combined_hash = f"{password_hash}:{salt}"
                
                # Inserir usuário
                conn.execute(
                    text("""
                    INSERT INTO usuarios (username, email, password_hash, nome_completo, admin)
                    VALUES (:username, :email, :password_hash, :nome_completo, :admin)
                    """),
                    {
                        "username": username,
                        "email": email,
                        "password_hash": combined_hash,
                        "nome_completo": nome_completo,
                        "admin": admin
                    }
                )
                conn.commit()
                
                return True, "Usuário criado com sucesso"
                
        except Exception as e:
            return False, f"Erro ao criar usuário: {str(e)}"
    
    def authenticate_user(self, username: str, password: str) -> Tuple[bool, str, Dict]:
        """Autentica um usuário"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                    SELECT id, username, email, password_hash, nome_completo, ativo, admin,
                           tentativas_login, bloqueado_ate
                    FROM usuarios 
                    WHERE username = :username OR email = :username
                    """),
                    {"username": username}
                )
                
                user_data = result.fetchone()
                if not user_data:
                    return False, "Usuário não encontrado", {}
                
                user_dict = dict(user_data._mapping)
                
                # Verificar se usuário está ativo
                if not user_dict['ativo']:
                    return False, "Usuário desativado", {}
                
                # Verificar se usuário está bloqueado
                if self._is_user_blocked(user_dict):
                    return False, "Usuário temporariamente bloqueado", {}
                
                # Verificar senha
                stored_hash = user_dict['password_hash']
                if ':' in stored_hash:
                    password_hash, salt = stored_hash.split(':', 1)
                else:
                    return False, "Erro na autenticação", {}
                
                if self._verify_password(password, password_hash, salt):
                    # Resetar tentativas de login e atualizar último login
                    conn.execute(
                        text("""
                        UPDATE usuarios 
                        SET tentativas_login = 0, ultimo_login = :now
                        WHERE id = :user_id
                        """),
                        {"now": datetime.now(), "user_id": user_dict['id']}
                    )
                    conn.commit()
                    
                    # Remover informações sensíveis
                    user_dict.pop('password_hash', None)
                    user_dict.pop('tentativas_login', None)
                    user_dict.pop('bloqueado_ate', None)
                    
                    return True, "Autenticação bem-sucedida", user_dict
                else:
                    # Incrementar tentativas de login
                    tentativas = user_dict['tentativas_login'] + 1
                    bloqueado_ate = None
                    
                    if tentativas >= self.security_config.MAX_LOGIN_ATTEMPTS:
                        bloqueado_ate = datetime.now() + timedelta(minutes=30)
                    
                    conn.execute(
                        text("""
                        UPDATE usuarios 
                        SET tentativas_login = :tentativas, bloqueado_ate = :bloqueado_ate
                        WHERE id = :user_id
                        """),
                        {
                            "tentativas": tentativas,
                            "bloqueado_ate": bloqueado_ate,
                            "user_id": user_dict['id']
                        }
                    )
                    conn.commit()
                    
                    if bloqueado_ate:
                        return False, "Muitas tentativas incorretas. Usuário bloqueado por 30 minutos", {}
                    else:
                        return False, f"Senha incorreta. Tentativas restantes: {self.security_config.MAX_LOGIN_ATTEMPTS - tentativas}", {}
                        
        except Exception as e:
            return False, f"Erro na autenticação: {str(e)}", {}
    
    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """Busca usuário por ID"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                    SELECT id, username, email, nome_completo, ativo, admin, data_criacao, ultimo_login
                    FROM usuarios 
                    WHERE id = :user_id
                    """),
                    {"user_id": user_id}
                )
                
                user_data = result.fetchone()
                if user_data:
                    return dict(user_data._mapping)
                return None
                
        except Exception as e:
            print(f"Erro ao buscar usuário: {e}")
            return None
    
    def update_user_password(self, user_id: int, new_password: str) -> Tuple[bool, str]:
        """Atualiza senha do usuário"""
        try:
            is_valid, message = self._validate_password_strength(new_password)
            if not is_valid:
                return False, message
            
            password_hash, salt = self._hash_password(new_password)
            combined_hash = f"{password_hash}:{salt}"
            
            with self.engine.connect() as conn:
                conn.execute(
                    text("UPDATE usuarios SET password_hash = :password_hash WHERE id = :user_id"),
                    {"password_hash": combined_hash, "user_id": user_id}
                )
                conn.commit()
                
                return True, "Senha atualizada com sucesso"
                
        except Exception as e:
            return False, f"Erro ao atualizar senha: {str(e)}"
    
    def deactivate_user(self, user_id: int) -> Tuple[bool, str]:
        """Desativa um usuário"""
        try:
            with self.engine.connect() as conn:
                # Usar sintaxe compatível com PostgreSQL e SQLite
                if 'postgresql' in self.database_url:
                    conn.execute(
                        text("UPDATE usuarios SET ativo = FALSE WHERE id = :user_id"),
                        {"user_id": user_id}
                    )
                else:
                    conn.execute(
                        text("UPDATE usuarios SET ativo = 0 WHERE id = :user_id"),
                        {"user_id": user_id}
                    )
                conn.commit()
                
                return True, "Usuário desativado com sucesso"
                
        except Exception as e:
            return False, f"Erro ao desativar usuário: {str(e)}"
    
    def list_users(self) -> list:
        """Lista todos os usuários (sem senhas)"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                    SELECT id, username, email, nome_completo, ativo, admin, 
                           data_criacao, ultimo_login
                    FROM usuarios 
                    ORDER BY data_criacao DESC
                    """)
                )
                
                return [dict(row._mapping) for row in result.fetchall()]
                
        except Exception as e:
            print(f"Erro ao listar usuários: {e}")
            return []
    
    def create_admin_user(self) -> Tuple[bool, str]:
        """Cria usuário administrador padrão se não existir"""
        try:
            with self.engine.connect() as conn:
                # Usar sintaxe compatível com PostgreSQL e SQLite
                if 'postgresql' in self.database_url:
                    result = conn.execute(
                        text("SELECT COUNT(*) as count FROM usuarios WHERE admin = TRUE")
                    )
                else:
                    result = conn.execute(
                        text("SELECT COUNT(*) as count FROM usuarios WHERE admin = 1")
                    )
                admin_count = result.fetchone()[0]
                
                if admin_count == 0:
                    # Criar usuário admin padrão
                    success, message = self.create_user(
                        username="admin",
                        email="admin@sistema.com",
                        password="Admin@123",
                        nome_completo="Administrador do Sistema",
                        admin=True
                    )
                    
                    if success:
                        return True, "Usuário administrador criado: admin / Admin@123"
                    else:
                        return False, f"Erro ao criar admin: {message}"
                else:
                    return True, "Usuário administrador já existe"
                    
        except Exception as e:
            return False, f"Erro ao verificar/criar admin: {str(e)}"
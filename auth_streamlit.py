"""
Sistema de Autenticação para Streamlit
Gerencia login, logout, sessões e proteção de páginas
"""

import streamlit as st
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from user_manager import UserManager

class StreamlitAuth:
    """Classe para gerenciar autenticação no Streamlit"""
    
    def __init__(self):
        self.user_manager = UserManager()
        self.session_timeout = 30  # 30 minutos
        self._initialize_session_state()
    
    def _initialize_session_state(self):
        """Inicializa o session state de forma segura"""
        # Inicializar session state
        if 'authenticated' not in st.session_state:
            st.session_state.authenticated = False
        if 'user_data' not in st.session_state:
            st.session_state.user_data = {}
        if 'last_activity' not in st.session_state:
            st.session_state.last_activity = datetime.now()
    
    def check_session_timeout(self) -> bool:
        """Verifica se a sessão expirou"""
        if st.session_state.authenticated:
            last_activity = st.session_state.get('last_activity', datetime.now())
            if isinstance(last_activity, str):
                last_activity = datetime.fromisoformat(last_activity)
            
            time_diff = datetime.now() - last_activity
            if time_diff > timedelta(minutes=self.session_timeout):
                self.logout()
                return True
        return False
    
    def update_activity(self):
        """Atualiza timestamp da última atividade"""
        st.session_state.last_activity = datetime.now()
    
    def login(self, username: str, password: str) -> tuple[bool, str]:
        """Realiza login do usuário"""
        success, message, user_data = self.user_manager.authenticate_user(username, password)
        
        if success:
            st.session_state.authenticated = True
            st.session_state.user_data = user_data
            st.session_state.last_activity = datetime.now()
            return True, message
        else:
            return False, message
    
    def logout(self):
        """Realiza logout do usuário"""
        st.session_state.authenticated = False
        st.session_state.user_data = {}
        st.session_state.last_activity = datetime.now()
    
    def is_authenticated(self) -> bool:
        """Verifica se o usuário está autenticado"""
        # Garantir que o session_state está inicializado
        self._initialize_session_state()
        
        if self.check_session_timeout():
            return False
        
        self.update_activity()
        return st.session_state.authenticated
    
    def get_current_user(self) -> Dict[str, Any]:
        """Retorna dados do usuário atual"""
        self._initialize_session_state()
        return st.session_state.get('user_data', {})
    
    def is_admin(self) -> bool:
        """Verifica se o usuário atual é administrador"""
        self._initialize_session_state()
        user_data = self.get_current_user()
        return user_data.get('admin', False)
    
    def require_auth(self, admin_required: bool = False):
        """Decorator/função para exigir autenticação"""
        if not self.is_authenticated():
            self.show_login_page()
            st.stop()
        
        if admin_required and not self.is_admin():
            st.error("❌ Acesso negado. Privilégios de administrador necessários.")
            st.stop()
    
    def show_login_page(self):
        """Exibe página de login"""
        
        # CSS personalizado para a página de login
        st.markdown("""
        <style>
        .login-container {
            max-width: 400px;
            margin: 0 auto;
            padding: 2rem;
            background: white;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        .login-header {
            text-align: center;
            margin-bottom: 2rem;
        }
        .login-header h1 {
            color: #1f77b4;
            margin-bottom: 0.5rem;
        }
        .login-header p {
            color: #666;
            margin: 0;
        }
        .stButton > button {
            width: 100%;
            background-color: #1f77b4;
            color: white;
            border: none;
            padding: 0.5rem 1rem;
            border-radius: 5px;
            font-weight: bold;
        }
        .stButton > button:hover {
            background-color: #1565c0;
        }
        </style>
        """, unsafe_allow_html=True)
        
        # Container principal
        col1, col2, col3 = st.columns([1, 2, 1])
        
        with col2:
            st.markdown("""
            <div class="login-container">
                <div class="login-header">
                    <h1>🔐 Sistema de Notas Fiscais</h1>
                    <p>Faça login para acessar o sistema</p>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # Abas para Login e Cadastro
            tab_login, tab_cadastro = st.tabs(["🔑 Login", "👤 Cadastro"])
            
            with tab_login:
                self._show_login_form()
            
            with tab_cadastro:
                self._show_register_form()
    
    def _show_login_form(self):
        """Exibe formulário de login"""
        with st.form("login_form"):
            st.subheader("Entrar no Sistema")
            
            username = st.text_input(
                "Usuário ou Email",
                placeholder="Digite seu usuário ou email"
            )
            
            password = st.text_input(
                "Senha",
                type="password",
                placeholder="Digite sua senha"
            )
            
            col1, col2 = st.columns(2)
            with col1:
                login_button = st.form_submit_button("🔑 Entrar", use_container_width=True)
            
            if login_button:
                if username and password:
                    with st.spinner("Verificando credenciais..."):
                        success, message = self.login(username, password)
                    
                    if success:
                        st.success(f"✅ {message}")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"❌ {message}")
                else:
                    st.error("❌ Por favor, preencha todos os campos")
    
    def _show_register_form(self):
        """Exibe formulário de cadastro"""
        with st.form("register_form"):
            st.subheader("Criar Nova Conta")
            
            username = st.text_input(
                "Nome de Usuário",
                placeholder="Escolha um nome de usuário (mín. 3 caracteres)"
            )
            
            email = st.text_input(
                "Email",
                placeholder="Digite seu email"
            )
            
            nome_completo = st.text_input(
                "Nome Completo",
                placeholder="Digite seu nome completo"
            )
            
            password = st.text_input(
                "Senha",
                type="password",
                placeholder="Crie uma senha segura"
            )
            
            password_confirm = st.text_input(
                "Confirmar Senha",
                type="password",
                placeholder="Digite a senha novamente"
            )
            
            # Mostrar critérios de senha
            with st.expander("📋 Critérios de Senha Segura"):
                st.markdown("""
                - Mínimo 8 caracteres
                - Pelo menos 1 letra maiúscula
                - Pelo menos 1 letra minúscula  
                - Pelo menos 1 número
                - Pelo menos 1 caractere especial (!@#$%^&*(),.?":{}|<>)
                """)
            
            register_button = st.form_submit_button("👤 Criar Conta", use_container_width=True)
            
            if register_button:
                if not all([username, email, password, password_confirm]):
                    st.error("❌ Por favor, preencha todos os campos obrigatórios")
                elif password != password_confirm:
                    st.error("❌ As senhas não coincidem")
                else:
                    with st.spinner("Criando conta..."):
                        success, message = self.user_manager.create_user(
                            username=username,
                            email=email,
                            password=password,
                            nome_completo=nome_completo
                        )
                    
                    if success:
                        st.success(f"✅ {message}")
                        st.info("🔑 Agora você pode fazer login com suas credenciais")
                    else:
                        st.error(f"❌ {message}")
    
    def show_user_info(self):
        """Exibe informações do usuário logado"""
        if self.is_authenticated():
            user_data = self.get_current_user()
            
            with st.sidebar:
                st.markdown("---")
                st.markdown("### 👤 Usuário Logado")
                
                if user_data.get('nome_completo'):
                    st.write(f"**Nome:** {user_data['nome_completo']}")
                
                st.write(f"**Usuário:** {user_data.get('username', 'N/A')}")
                st.write(f"**Email:** {user_data.get('email', 'N/A')}")
                
                if user_data.get('admin'):
                    st.write("**Tipo:** 👑 Administrador")
                else:
                    st.write("**Tipo:** 👤 Usuário")
                
                # Botão de logout
                if st.button("🚪 Sair", use_container_width=True):
                    self.logout()
                    st.rerun()
                
                # Mostrar tempo de sessão restante
                last_activity = st.session_state.get('last_activity', datetime.now())
                if isinstance(last_activity, str):
                    last_activity = datetime.fromisoformat(last_activity)
                
                time_remaining = timedelta(minutes=self.session_timeout) - (datetime.now() - last_activity)
                if time_remaining.total_seconds() > 0:
                    minutes_remaining = int(time_remaining.total_seconds() / 60)
                    st.caption(f"⏱️ Sessão expira em: {minutes_remaining} min")
                
                st.markdown("---")
    
    def create_admin_if_needed(self):
        """Cria usuário administrador se necessário"""
        success, message = self.user_manager.create_admin_user()
        if "criado" in message:
            st.info(f"ℹ️ {message}")

# Instância global do sistema de autenticação
auth = StreamlitAuth()
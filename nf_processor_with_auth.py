#!/usr/bin/env python3
"""
Gestor Fiscal AI - Versão com Autenticação Completa e Correções
Mantém todas as funcionalidades de login e segurança, mas corrige problemas de session state
"""

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
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path
import tempfile
from dotenv import load_dotenv
import google.generativeai as genai
from decimal import Decimal, InvalidOperation
import re
import unicodedata
import io
import zipfile

# Importar módulos do sistema
from auth_streamlit import auth
from security_utils import SecurityConfig, DataSanitizer, SecurityAuditor
from secure_config import get_secure_config, SecureConfigError
from user_manager import UserManager
from nf_processor import XMLExtractor, PDFExtractor

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class NotaFiscal:
    numero: str
    serie: str
    data_emissao: datetime
    cnpj_emitente: str
    nome_emitente: str
    valor_total: Decimal
    chave_acesso: str
    natureza_operacao: str
    itens: List[Dict[str, Any]] = None
    xml_content: Optional[str] = None
    origem: str = 'upload'  # 'email' ou 'upload'
    
    def __post_init__(self):
        if self.itens is None:
            self.itens = []
    
    def to_dict(self):
        return {
            'numero': self.numero,
            'serie': self.serie,
            'data_emissao': self.data_emissao.isoformat() if self.data_emissao else None,
            'cnpj_emitente': self.cnpj_emitente,
            'nome_emitente': self.nome_emitente,
            'valor_total': float(self.valor_total),
            'chave_acesso': self.chave_acesso,
            'natureza_operacao': self.natureza_operacao,
            'itens': json.dumps(self.itens),
            'xml_content': self.xml_content,
            'origem': self.origem
        }

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
                    {"database_type": "PostgreSQL" if not secure_config.DATABASE_URL.startswith('sqlite') else "SQLite"},
                    "INFO"
                )
                
                # Criar tabelas se não existirem
                self._create_tables_if_not_exists()
                
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
    
    def _create_tables_if_not_exists(self):
        """Cria as tabelas necessárias se elas não existirem"""
        try:
            with self.engine.begin() as connection:
                # Detectar tipo de banco
                is_postgresql = not self.engine.url.drivername.startswith('sqlite')
                
                # Criar tabela notas_fiscais
                if is_postgresql:
                    create_notas_fiscais = text("""
                        CREATE TABLE IF NOT EXISTS notas_fiscais (
                            id SERIAL PRIMARY KEY,
                            numero VARCHAR(50) NOT NULL UNIQUE,
                            data_emissao TIMESTAMP NOT NULL,
                            cnpj_emitente VARCHAR(18) NOT NULL,
                            nome_emitente VARCHAR(255) NOT NULL,
                            valor_total DECIMAL(15,2) NOT NULL,
                            xml_content TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                else:
                    create_notas_fiscais = text("""
                        CREATE TABLE IF NOT EXISTS notas_fiscais (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            numero VARCHAR(50) NOT NULL UNIQUE,
                            data_emissao TIMESTAMP NOT NULL,
                            cnpj_emitente VARCHAR(18) NOT NULL,
                            nome_emitente VARCHAR(255) NOT NULL,
                            valor_total DECIMAL(15,2) NOT NULL,
                            xml_content TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                
                connection.execute(create_notas_fiscais)
                
                # Criar tabela itens_nota_fiscal
                if is_postgresql:
                    create_itens_nota_fiscal = text("""
                        CREATE TABLE IF NOT EXISTS itens_nota_fiscal (
                            id SERIAL PRIMARY KEY,
                            nota_fiscal_id INTEGER NOT NULL,
                            codigo VARCHAR(50),
                            descricao TEXT NOT NULL,
                            ncm VARCHAR(10),
                            quantidade DECIMAL(10,3) NOT NULL,
                            valor_unitario DECIMAL(15,2) NOT NULL,
                            valor_total DECIMAL(15,2) NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (nota_fiscal_id) REFERENCES notas_fiscais(id) ON DELETE CASCADE
                        )
                    """)
                else:
                    create_itens_nota_fiscal = text("""
                        CREATE TABLE IF NOT EXISTS itens_nota_fiscal (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            nota_fiscal_id INTEGER NOT NULL,
                            codigo VARCHAR(50),
                            descricao TEXT NOT NULL,
                            ncm VARCHAR(10),
                            quantidade DECIMAL(10,3) NOT NULL,
                            valor_unitario DECIMAL(15,2) NOT NULL,
                            valor_total DECIMAL(15,2) NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (nota_fiscal_id) REFERENCES notas_fiscais(id) ON DELETE CASCADE
                        )
                    """)
                
                connection.execute(create_itens_nota_fiscal)
                
                logger.info("Tabelas criadas com sucesso (se não existiam)")
                
        except Exception as e:
            logger.error(f"Erro ao criar tabelas: {e}")
            raise
    
    def buscar_dados(self, tabela, filtros=None):
        try:
            query = f"SELECT * FROM {tabela}"
            params = {}
            
            if filtros:
                conditions = []
                for key, value in filtros.items():
                    if key == 'data_emissao_inicio':
                        conditions.append("DATE(data_emissao) >= :data_inicio")
                        params['data_inicio'] = value
                    elif key == 'data_emissao_fim':
                        conditions.append("DATE(data_emissao) <= :data_fim")
                        params['data_fim'] = value
                    else:
                        conditions.append(f"{key} = :{key}")
                        params[key] = value
                
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)
            
            with self.engine.connect() as conn:
                result = conn.execute(text(query), params)
                return [dict(row._mapping) for row in result]
                
        except Exception as e:
            logger.error(f"Erro ao buscar dados: {e}")
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

    def salvar_dados(self, tabela, dados):
        """Salva dados em uma tabela específica"""
        try:
            # Construir query de inserção dinamicamente
            colunas = list(dados.keys())
            placeholders = [f":{col}" for col in colunas]
            
            query = text(f"""
                INSERT INTO {tabela} ({', '.join(colunas)})
                VALUES ({', '.join(placeholders)})
            """)
            
            with self.engine.begin() as connection:
                connection.execute(query, dados)
                return True
        except Exception as e:
            logger.error(f"Erro ao salvar dados na tabela {tabela}: {e}")
            return False

# --- MÓDULOS DE IA ---

class GeminiChat:
    """Classe para interação com a API do Google Gemini para análise de notas fiscais"""
    
    def __init__(self, config):
        """Inicializa o chat com Gemini"""
        if not hasattr(config, 'GEMINI_API_KEY') or not config.GEMINI_API_KEY or "AIza" not in config.GEMINI_API_KEY:
            raise ValueError("A chave da API do Gemini não foi configurada corretamente.")
        
        genai.configure(api_key=config.GEMINI_API_KEY)
        self.model = genai.GenerativeModel('gemini-2.5-flash')
        
    def responder_pergunta(self, pergunta: str, df_notas: pd.DataFrame) -> str:
        """Responde perguntas sobre as notas fiscais usando IA"""
        if df_notas.empty:
            return "❌ Não há dados de notas fiscais para analisar. Por favor, faça upload de arquivos ou ajuste os filtros de período."
        
        try:
            # Preparar dados para análise (limitando a 100 registros para performance)
            df_analise = df_notas.head(100).copy()
            
            # Converter para CSV para enviar ao Gemini
            dados_csv = df_analise.to_csv(index=False, sep=';')
            
            # Criar prompt estruturado
            prompt = f"""
Você é um assistente especializado em análise fiscal e contábil. Analise os dados das notas fiscais fornecidos em formato CSV e responda à pergunta do usuário de forma clara e objetiva.

DADOS DAS NOTAS FISCAIS (CSV):
{dados_csv}

PERGUNTA DO USUÁRIO:
{pergunta}

INSTRUÇÕES:
- Forneça uma resposta precisa e baseada nos dados
- Use formatação em markdown para melhor legibilidade
- Inclua números e estatísticas relevantes
- Se necessário, sugira análises adicionais
- Mantenha um tom profissional e técnico
- Se a pergunta não puder ser respondida com os dados disponíveis, explique claramente

RESPOSTA:
"""
            
            # Chamar a API do Gemini
            response = self.model.generate_content(prompt)
            
            if response and response.text:
                return response.text
            else:
                return "❌ Não foi possível gerar uma resposta. Tente reformular sua pergunta."
                
        except Exception as e:
            logger.error(f"Erro ao chamar a API do Gemini: {e}")
            return f"❌ Ocorreu um erro ao processar sua pergunta: {str(e)}"

class Dashboard:
    def __init__(self):
        # Inicializar session state primeiro
        self._init_session_state()
        
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
            self.db_manager = DatabaseManager(secure_config=self.config)
            
        except SecureConfigError as e:
            st.error(f"Erro de configuração: {e}")
            st.stop()
        except Exception as e:
            st.error(f"Erro ao inicializar dashboard: {e}")
            st.stop()
    
    def _init_session_state(self):
        """Inicializa o session state de forma segura"""
        # Inicializar variáveis essenciais do session state
        if 'data_loaded' not in st.session_state:
            st.session_state.data_loaded = False
        if 'df_notas' not in st.session_state:
            st.session_state.df_notas = pd.DataFrame()
        if 'last_load_time' not in st.session_state:
            st.session_state.last_load_time = None
        if 'load_error' not in st.session_state:
            st.session_state.load_error = None

    def run(self):
        # Auto-refresh a cada 10 minutos
        st_autorefresh(interval=600000, key="datarefresher")
        
        # Sidebar com informações do usuário
        st.sidebar.title("Gestor Fiscal AI 🤖")
        auth.show_user_info()
        
        st.sidebar.header("Filtros de Período")
        self.data_inicio = st.sidebar.date_input("Data Início", datetime.now().date() - timedelta(days=30))
        self.data_fim = st.sidebar.date_input("Data Fim", datetime.now().date())
        
        # Botão para recarregar dados
        if st.sidebar.button("🔄 Recarregar Dados"):
            st.session_state.data_loaded = False
            st.rerun()
        
        # Informações de debug na sidebar
        st.sidebar.markdown("---")
        st.sidebar.subheader("🔍 Status do Sistema")
        
        # Carregar dados
        self.carregar_dados()
        
        # Mostrar status na sidebar
        if st.session_state.data_loaded:
            st.sidebar.success(f"✅ {len(st.session_state.df_notas)} notas carregadas")
        elif st.session_state.load_error:
            st.sidebar.error(f"❌ Erro: {st.session_state.load_error}")
        else:
            st.sidebar.info("⏳ Carregando dados...")
        
        st.sidebar.write(f"📅 Período: {self.data_inicio} a {self.data_fim}")
        if st.session_state.last_load_time:
            st.sidebar.write(f"🕒 Última atualização: {st.session_state.last_load_time.strftime('%H:%M:%S')}")
        
        # Todos os usuários têm acesso completo ao sistema
        user_data = auth.get_current_user()
        is_admin = user_data.get('admin', False)
        
        # Mostrar todas as abas para todos os usuários
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "📊 Visão Geral", 
            "📄 Análise Detalhada", 
            "💬 Chat Fiscal (Gemini)", 
            "📋 Logs", 
            "📤 Upload de Notas", 
            "👥 Gerenciar Usuários"
        ])
        
        with tab1:
            self.render_visao_geral()
        with tab2:
            self.render_analise_detalhada()
        with tab3:
            self.render_chat_fiscal()
        with tab4:
            self.render_logs()
        with tab5:
            self.render_upload_notas()
        with tab6:
            self.render_gerenciar_usuarios()

    def carregar_dados(self):
        """Carrega dados do banco com cache inteligente"""
        try:
            logger.info(f"🔍 DEBUG: Iniciando carregar_dados()")
            logger.info(f"🔍 DEBUG: self.data_inicio = {self.data_inicio}")
            logger.info(f"🔍 DEBUG: self.data_fim = {self.data_fim}")
            
            # Verificar se precisa recarregar
            current_filters = (self.data_inicio, self.data_fim)
            logger.info(f"🔍 DEBUG: current_filters = {current_filters}")
            
            if (st.session_state.data_loaded and 
                hasattr(st.session_state, 'last_filters') and 
                st.session_state.last_filters == current_filters):
                logger.info(f"🔍 DEBUG: Dados já carregados com os mesmos filtros, pulando...")
                return  # Dados já carregados com os mesmos filtros
            
            # Mostrar progresso
            with st.spinner("Carregando dados do banco..."):
                filtros = {
                    'data_emissao_inicio': self.data_inicio.isoformat(), 
                    'data_emissao_fim': self.data_fim.isoformat()
                }
                
                # Log de debug dos filtros
                logger.info(f"🔍 DEBUG: Filtros aplicados - início: {filtros['data_emissao_inicio']}, fim: {filtros['data_emissao_fim']}")
                
                logger.info(f"🔍 DEBUG: Chamando self.db_manager.buscar_dados()")
                notas_data = self.db_manager.buscar_dados('notas_fiscais', filtros)
                logger.info(f"🔍 DEBUG: Dados retornados do banco: {len(notas_data) if notas_data else 0} registros")
                
                if notas_data:
                    logger.info(f"🔍 DEBUG: Primeiro registro: {notas_data[0] if notas_data else 'None'}")
                
                df_notas = pd.DataFrame(notas_data) if notas_data else pd.DataFrame()
                
                # Log de debug dos resultados
                logger.info(f"🔍 DEBUG: DataFrame criado com {len(df_notas)} linhas")
                if not df_notas.empty:
                    logger.info(f"🔍 DEBUG: Colunas do DataFrame: {list(df_notas.columns)}")
                
                # Atualizar session state
                st.session_state.df_notas = df_notas
                st.session_state.data_loaded = True
                st.session_state.last_filters = current_filters
                st.session_state.last_load_time = datetime.now()
                st.session_state.load_error = None
                
                # Log para debug
                logger.info(f"Dados carregados: {len(df_notas)} notas")
                
                # Se não há dados no período, verificar se há dados no banco
                if df_notas.empty:
                    todas_notas = self.db_manager.buscar_dados('notas_fiscais', {})
                    if todas_notas:
                        st.session_state.total_notas_banco = len(todas_notas)
                    else:
                        st.session_state.total_notas_banco = 0
                
        except Exception as e:
            error_msg = f"Erro ao carregar dados: {e}"
            logger.error(error_msg)
            logger.error(f"🔍 DEBUG: Traceback completo:", exc_info=True)
            st.session_state.load_error = str(e)
            st.session_state.data_loaded = False
            st.session_state.df_notas = pd.DataFrame()

    def render_visao_geral(self):
        """Renderiza a visão geral"""
        st.header("📊 Visão Geral do Período")
        
        if not st.session_state.data_loaded:
            st.warning("⏳ Carregando dados...")
            return
        
        df_notas = st.session_state.df_notas
        
        # Verificar se existem dados para exibir
        if df_notas.empty:
            # Verificar se há dados no banco total
            total_notas_banco = st.session_state.get('total_notas_banco', 0)
            if total_notas_banco > 0:
                st.warning("📅 Nenhuma nota fiscal encontrada para o período selecionado.")
                st.info(f"💡 Existem {total_notas_banco} notas no banco. Ajuste o período de filtro para visualizar os dados ou faça upload de novos arquivos na aba 'Upload de Notas'.")
            else:
                st.info("📋 Nenhuma nota fiscal encontrada no banco de dados.")
                st.markdown("""
                ### 🚀 Como começar:
                1. **Faça upload** de suas notas fiscais na aba 'Upload de Notas'
                2. **Formatos aceitos**: PDF (DANFE), XML (NFe), CSV ou ZIP
                3. **Após o upload**, os dados aparecerão automaticamente aqui
                """)
            return
        
        # Converter valores para numérico
        df_notas['valor_total'] = pd.to_numeric(df_notas['valor_total'], errors='coerce').fillna(0)
        
        # Métricas principais
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total de Notas", f"{df_notas.shape[0]:,}")
        
        with col2:
            total_valor = df_notas['valor_total'].sum()
            st.metric("Valor Total", f"R$ {total_valor:,.2f}")
        
        with col3:
            ticket_medio = df_notas['valor_total'].mean()
            st.metric("Ticket Médio", f"R$ {ticket_medio:,.2f}")
        
        with col4:
            fornecedores = df_notas['cnpj_emitente'].nunique()
            st.metric("Fornecedores Únicos", f"{fornecedores:,}")
        
        st.markdown("---")
        
        # Gráficos
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.subheader("💰 Valor por Fornecedor (Top 10)")
            if 'nome_emitente' in df_notas.columns:
                valor_por_fornecedor = df_notas.groupby('nome_emitente')['valor_total'].sum().nlargest(10).sort_values()
                if not valor_por_fornecedor.empty:
                    fig = px.bar(
                        valor_por_fornecedor, 
                        x='valor_total', 
                        y=valor_por_fornecedor.index, 
                        orientation='h', 
                        text_auto='.2s',
                        title="Top 10 Fornecedores por Valor"
                    )
                    fig.update_layout(height=400)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Dados insuficientes para gráfico")
            else:
                st.info("Coluna 'nome_emitente' não encontrada")
        
        with col2:
            st.subheader("📈 Evolução Diária de Valores")
            if 'data_emissao' in df_notas.columns:
                try:
                    df_notas['data_emissao_dt'] = pd.to_datetime(df_notas['data_emissao'])
                    valores_por_dia = df_notas.groupby(df_notas['data_emissao_dt'].dt.date)['valor_total'].sum()
                    if not valores_por_dia.empty:
                        fig = px.line(
                            valores_por_dia, 
                            x=valores_por_dia.index, 
                            y='valor_total', 
                            markers=True,
                            title="Evolução Diária dos Valores"
                        )
                        fig.update_layout(height=400)
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("Dados insuficientes para gráfico")
                except Exception as e:
                    st.error(f"Erro ao processar datas: {e}")
            else:
                st.info("Coluna 'data_emissao' não encontrada")
        
        # Nova seção: Distribuição por Origem
        if 'origem' in df_notas.columns:
            st.markdown("---")
            st.subheader("📊 Distribuição por Origem")
            
            col1, col2 = st.columns([1, 1])
            
            with col1:
                # Gráfico de pizza - Quantidade por origem
                origem_count = df_notas['origem'].value_counts()
                if not origem_count.empty:
                    fig = px.pie(
                        values=origem_count.values, 
                        names=origem_count.index,
                        title="Distribuição de Notas por Origem"
                    )
                    fig.update_layout(height=400)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Dados insuficientes para gráfico")
            
            with col2:
                # Gráfico de barras - Valor por origem
                origem_valor = df_notas.groupby('origem')['valor_total'].sum()
                if not origem_valor.empty:
                    fig = px.bar(
                        x=origem_valor.index,
                        y=origem_valor.values,
                        title="Valor Total por Origem",
                        labels={'x': 'Origem', 'y': 'Valor Total (R$)'}
                    )
                    fig.update_layout(height=400)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Dados insuficientes para gráfico")

    def render_analise_detalhada(self):
        """Renderiza análise detalhada"""
        st.header("📄 Análise Detalhada das Notas Fiscais")
        
        if not st.session_state.data_loaded:
            st.warning("⏳ Carregando dados...")
            return
        
        df_notas = st.session_state.df_notas
        
        if df_notas.empty:
            # Verificar se há dados no banco total
            total_notas_banco = st.session_state.get('total_notas_banco', 0)
            if total_notas_banco > 0:
                st.warning("📅 Nenhuma nota fiscal encontrada para o período selecionado.")
                st.info(f"💡 Existem {total_notas_banco} notas no banco. Ajuste o período de filtro para visualizar os dados.")
            else:
                st.info("📋 Nenhuma nota fiscal encontrada no banco de dados.")
                st.markdown("""
                ### 🚀 Como começar:
                1. **Faça upload** de suas notas fiscais na aba 'Upload de Notas'
                2. **Formatos aceitos**: PDF (DANFE), XML (NFe), CSV ou ZIP
                3. **Após o upload**, os dados aparecerão automaticamente aqui
                """)
            return
        
        # Filtros adicionais
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            if 'nome_emitente' in df_notas.columns:
                fornecedores = ['Todos'] + list(df_notas['nome_emitente'].unique())
                fornecedor_selecionado = st.selectbox("Filtrar por Fornecedor", fornecedores)
            else:
                fornecedor_selecionado = 'Todos'
        
        with col2:
            if 'origem' in df_notas.columns:
                origens = ['Todos'] + list(df_notas['origem'].unique())
                origem_selecionada = st.selectbox("Filtrar por Origem", origens)
            else:
                origem_selecionada = 'Todos'
        
        with col3:
            valor_minimo = st.number_input("Valor Mínimo", min_value=0.0, value=0.0)
        
        with col4:
            valor_maximo = st.number_input("Valor Máximo", min_value=0.0, value=0.0)
        
        # Aplicar filtros
        df_filtrado = df_notas.copy()
        df_filtrado['valor_total'] = pd.to_numeric(df_filtrado['valor_total'], errors='coerce').fillna(0)
        
        if fornecedor_selecionado != 'Todos':
            df_filtrado = df_filtrado[df_filtrado['nome_emitente'] == fornecedor_selecionado]
        
        if origem_selecionada != 'Todos':
            df_filtrado = df_filtrado[df_filtrado['origem'] == origem_selecionada]
        
        if valor_minimo > 0:
            df_filtrado = df_filtrado[df_filtrado['valor_total'] >= valor_minimo]
        
        if valor_maximo > 0:
            df_filtrado = df_filtrado[df_filtrado['valor_total'] <= valor_maximo]
        
        # Mostrar dados filtrados
        st.subheader(f"📊 Dados Filtrados ({len(df_filtrado)} notas)")
        
        if not df_filtrado.empty:
            # Configurar colunas para exibição
            colunas_exibir = ['numero', 'data_emissao', 'nome_emitente', 'valor_total', 'origem']
            colunas_disponiveis = [col for col in colunas_exibir if col in df_filtrado.columns]
            
            if colunas_disponiveis:
                # Formatar valores para exibição
                df_display = df_filtrado[colunas_disponiveis].copy()
                if 'valor_total' in df_display.columns:
                    df_display['valor_total'] = df_display['valor_total'].apply(lambda x: f"R$ {x:,.2f}")
                
                st.dataframe(
                    df_display.head(100),
                    use_container_width=True
                )
            else:
                st.dataframe(df_filtrado.head(100), use_container_width=True)
            
            # Estatísticas do filtro
            st.subheader("📈 Estatísticas dos Dados Filtrados")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Notas Filtradas", len(df_filtrado))
            
            with col2:
                total_filtrado = df_filtrado['valor_total'].sum()
                st.metric("Valor Total Filtrado", f"R$ {total_filtrado:,.2f}")
            
            with col3:
                media_filtrada = df_filtrado['valor_total'].mean()
                st.metric("Valor Médio Filtrado", f"R$ {media_filtrada:,.2f}")
        
        else:
            st.info("Nenhuma nota atende aos critérios de filtro.")

    def render_chat_fiscal(self):
        """Renderiza o chat fiscal com Gemini"""
        st.header("💬 Chat Fiscal com IA (Gemini)")
        st.markdown("🤖 **Converse com a IA sobre suas notas fiscais!** Faça perguntas sobre fornecedores, valores, períodos e muito mais.")
        
        # Verificar configuração da API
        if not hasattr(self.config, 'GEMINI_API_KEY') or not self.config.GEMINI_API_KEY or "AIza" not in self.config.GEMINI_API_KEY:
            st.error("🔑 **Configuração necessária:** A chave da API do Gemini não foi configurada.")
            st.info("💡 Configure a variável de ambiente `GEMINI_API_KEY` no arquivo `.env` para habilitar o chat com IA.")
            return
        
        # Verificar se há dados disponíveis
        if not st.session_state.data_loaded or st.session_state.df_notas.empty:
            st.warning("📊 **Nenhum dado disponível para análise**")
            st.info("💡 Ajuste os filtros de período na barra lateral para carregar dados ou faça upload de novas notas fiscais na aba '📤 Upload de Notas'.")
            return
        
        # Inicializar o chat com Gemini
        try:
            gemini_chat = GeminiChat(self.config)
        except ValueError as e:
            st.error(f"❌ Erro na configuração do Gemini: {e}")
            return
        except Exception as e:
            st.error(f"❌ Erro ao inicializar o chat: {e}")
            return
        
        # Mostrar informações dos dados disponíveis
        st.success(f"✅ **Dados carregados:** {len(st.session_state.df_notas)} notas fiscais disponíveis para análise")
        
        # Informações sobre o período
        if not st.session_state.df_notas.empty and 'data_emissao' in st.session_state.df_notas.columns:
            try:
                df_temp = st.session_state.df_notas.copy()
                df_temp['data_emissao'] = pd.to_datetime(df_temp['data_emissao'], errors='coerce')
                data_min = df_temp['data_emissao'].min()
                data_max = df_temp['data_emissao'].max()
                if pd.notna(data_min) and pd.notna(data_max):
                    st.info(f"📅 **Período dos dados:** {data_min.strftime('%d/%m/%Y')} a {data_max.strftime('%d/%m/%Y')}")
            except:
                pass
        
        # Sugestões de perguntas
        st.markdown("### 💡 Sugestões de perguntas:")
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("""
            **📊 Análises Gerais:**
            - Qual o fornecedor com maior valor total?
            - Quantas notas fiscais foram emitidas este mês?
            - Qual o valor médio das notas fiscais?
            - Mostre um resumo dos principais fornecedores
            """)
            
        with col2:
            st.markdown("""
            **🔍 Análises Específicas:**
            - Quais fornecedores têm valores acima de R$ 10.000?
            - Qual a distribuição de valores por mês?
            - Identifique possíveis outliers nos valores
            - Compare os valores de ICMS e IPI
            """)
        
        # Inicializar histórico de mensagens
        if "chat_messages" not in st.session_state:
            st.session_state.chat_messages = []
        
        # Exibir histórico de mensagens
        for message in st.session_state.chat_messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
        
        # Input do usuário
        if prompt := st.chat_input("Digite sua pergunta sobre as notas fiscais..."):
            # Adicionar mensagem do usuário
            st.session_state.chat_messages.append({"role": "user", "content": prompt})
            
            # Exibir mensagem do usuário
            with st.chat_message("user"):
                st.markdown(prompt)
            
            # Gerar resposta da IA
            with st.chat_message("assistant"):
                with st.spinner("🤖 Analisando seus dados..."):
                    try:
                        response = gemini_chat.responder_pergunta(prompt, st.session_state.df_notas)
                        st.markdown(response)
                        
                        # Adicionar resposta ao histórico
                        st.session_state.chat_messages.append({"role": "assistant", "content": response})
                        
                    except Exception as e:
                        error_msg = f"❌ Erro ao processar sua pergunta: {str(e)}"
                        st.error(error_msg)
                        st.session_state.chat_messages.append({"role": "assistant", "content": error_msg})
        
        # Botão para limpar histórico
        if st.session_state.chat_messages:
            st.markdown("---")
            if st.button("🗑️ Limpar Histórico do Chat"):
                st.session_state.chat_messages = []
                st.rerun()

    def render_logs(self):
        """Renderiza os logs do sistema"""
        st.header("📋 Logs do Sistema")
        st.info("🚧 Visualização de logs em desenvolvimento.")

    def render_upload_notas(self):
        """Renderiza seção de upload com suporte completo a múltiplos tipos de arquivo"""
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
        
        # Mostrar informações do banco se existem dados
        st.markdown("---")
        st.subheader("📊 Informações do Banco de Dados")
        
        try:
            todas_notas = self.db_manager.buscar_dados('notas_fiscais', {})
            if todas_notas:
                df_todas = pd.DataFrame(todas_notas)
                
                # Armazenar total de notas no session_state para uso em outras seções
                st.session_state.total_notas_banco = len(df_todas)
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.metric("Total de Notas no Banco", len(df_todas))
                    
                with col2:
                    if 'valor_total' in df_todas.columns:
                        df_todas['valor_total'] = pd.to_numeric(df_todas['valor_total'], errors='coerce').fillna(0)
                        total_geral = df_todas['valor_total'].sum()
                        st.metric("Valor Total Geral", f"R$ {total_geral:,.2f}")
                
                # Mostrar amostra dos dados
                st.subheader("📋 Amostra dos Dados (10 primeiras)")
                st.dataframe(df_todas.head(10), use_container_width=True)
                
            else:
                st.warning("Nenhuma nota encontrada no banco de dados.")
                st.session_state.total_notas_banco = 0
                
        except Exception as e:
            st.error(f"Erro ao consultar banco: {e}")
            st.session_state.total_notas_banco = 0

    def render_gerenciar_usuarios(self):
        """Renderiza interface de gerenciamento de usuários (acesso para todos os usuários)"""
        st.header("👥 Gerenciamento de Usuários")
        
        # Todos os usuários podem acessar esta seção
        user_data = auth.get_current_user()
        is_admin = user_data.get('admin', False)
        
        # Mostrar informação sobre o tipo de usuário
        if is_admin:
            st.info("👑 Você está logado como administrador")
        else:
            st.info("👤 Você está logado como usuário padrão")
        
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
                                else:  # Arquivo vazio ou sem dados válidos
                                    resultados['erros'] += 1
                                    resultados['detalhes'].append(f"❌ {file_name}: Nenhum dado válido encontrado")
                            else:  # Erro no processamento
                                resultados['erros'] += 1
                                resultados['detalhes'].append(f"❌ {file_name}: Erro no processamento CSV")
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
        """Salva uma nota fiscal no banco de dados"""
        try:
            # Converter NotaFiscal para dicionário
            if hasattr(nota_fiscal, '__dict__'):
                dados = asdict(nota_fiscal)
            else:
                dados = nota_fiscal
            
            # Garantir que data_emissao seja string no formato correto
            if isinstance(dados.get('data_emissao'), datetime):
                dados['data_emissao'] = dados['data_emissao'].strftime('%Y-%m-%d')
            
            # Salvar no banco
            return self.db_manager.salvar_dados('notas_fiscais', dados)
        except Exception as e:
            logger.error(f"Erro ao salvar nota fiscal: {e}")
            return False

    def mostrar_resultados_processamento(self, resultados):
        """Mostra os resultados do processamento de upload"""
        st.markdown("---")
        st.subheader("📊 Resultados do Processamento")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("✅ Processados", resultados['processados'])
        with col2:
            st.metric("❌ Erros", resultados['erros'])
        with col3:
            total = resultados['processados'] + resultados['erros']
            taxa_sucesso = (resultados['processados'] / total * 100) if total > 0 else 0
            st.metric("📈 Taxa de Sucesso", f"{taxa_sucesso:.1f}%")
        
        # Definir que upload foi realizado se houve processamentos bem-sucedidos
        if resultados['processados'] > 0:
            st.session_state.upload_realizado = True
            st.success("🎉 Upload realizado com sucesso! As informações do banco de dados agora estão disponíveis abaixo.")
        
        # Mostrar detalhes
        if resultados['detalhes']:
            st.subheader("📋 Detalhes do Processamento")
            for detalhe in resultados['detalhes']:
                if "✅" in detalhe:
                    st.success(detalhe)
                elif "❌" in detalhe:
                    st.error(detalhe)
                else:
                     st.info(detalhe)

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

if __name__ == "__main__":
    try:
        dashboard = Dashboard()
        dashboard.run()
    except Exception as e:
        logger.critical(f"A aplicação falhou: {e}")
        st.error(f"Ocorreu um erro crítico na aplicação: {e}")
        import traceback
        st.code(traceback.format_exc())
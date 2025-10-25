#!/usr/bin/env python3
"""
Script para adicionar coluna 'origem' na tabela notas_fiscais
"""

import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def add_origem_column():
    """Adiciona coluna origem na tabela notas_fiscais"""
    
    # Carregar configurações
    load_dotenv()
    database_url = os.getenv('DATABASE_URL')
    
    if not database_url:
        logger.error("DATABASE_URL não encontrada no arquivo .env")
        return False
    
    try:
        # Conectar ao banco
        engine = create_engine(database_url)
        
        with engine.connect() as conn:
            # Verificar se a coluna já existe
            logger.info("Verificando se a coluna 'origem' já existe...")
            
            result = conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'notas_fiscais' 
                AND column_name = 'origem'
            """))
            
            if result.fetchone():
                logger.info("✅ Coluna 'origem' já existe na tabela notas_fiscais")
                return True
            
            # Adicionar a coluna
            logger.info("Adicionando coluna 'origem' na tabela notas_fiscais...")
            
            conn.execute(text("""
                ALTER TABLE notas_fiscais 
                ADD COLUMN origem VARCHAR(20) DEFAULT 'upload'
            """))
            
            # Confirmar a transação
            conn.commit()
            
            logger.info("✅ Coluna 'origem' adicionada com sucesso!")
            
            # Verificar quantos registros existem
            result = conn.execute(text("SELECT COUNT(*) FROM notas_fiscais"))
            count = result.fetchone()[0]
            
            logger.info(f"📊 Total de registros na tabela: {count}")
            
            if count > 0:
                logger.info("ℹ️  Registros existentes foram marcados como 'upload' por padrão")
                logger.info("ℹ️  Novos registros do email serão marcados como 'email'")
            
            return True
            
    except Exception as e:
        logger.error(f"❌ Erro ao adicionar coluna: {e}")
        return False

if __name__ == "__main__":
    print("=== ADICIONANDO COLUNA ORIGEM ===")
    success = add_origem_column()
    
    if success:
        print("\n✅ Operação concluída com sucesso!")
        print("A coluna 'origem' foi adicionada à tabela notas_fiscais")
        print("- Registros existentes: marcados como 'upload'")
        print("- Novos registros do email: serão marcados como 'email'")
    else:
        print("\n❌ Falha na operação!")
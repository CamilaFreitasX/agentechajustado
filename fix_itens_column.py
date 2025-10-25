#!/usr/bin/env python3
"""
Script para adicionar a coluna 'itens' na tabela notas_fiscais
"""

from secure_config import get_secure_config
from sqlalchemy import create_engine, text, inspect

def main():
    """Adiciona a coluna itens na tabela"""
    try:
        # Carregar configuração
        config = get_secure_config()
        print(f"🔧 Conectando ao banco: {config.DATABASE_URL[:50]}...")
        
        # Criar engine
        engine = create_engine(config.DATABASE_URL)
        
        # Verificar estrutura atual
        inspector = inspect(engine)
        columns = inspector.get_columns('notas_fiscais')
        
        print("\n📊 Estrutura atual da tabela 'notas_fiscais':")
        column_names = []
        for column in columns:
            column_names.append(column['name'])
            print(f"   - {column['name']}: {column['type']}")
        
        # Verificar se a coluna 'itens' existe
        if 'itens' not in column_names:
            print("\n🔧 Adicionando coluna 'itens'...")
            
            with engine.begin() as connection:
                # Adicionar a coluna itens como TEXT para armazenar JSON
                alter_query = text("""
                    ALTER TABLE notas_fiscais 
                    ADD COLUMN itens TEXT
                """)
                
                connection.execute(alter_query)
                print("   ✅ Coluna 'itens' adicionada com sucesso!")
        else:
            print("\n⚠️ Coluna 'itens' já existe")
        
        # Verificar estrutura final
        print("\n📊 Estrutura final da tabela:")
        inspector = inspect(engine)
        columns = inspector.get_columns('notas_fiscais')
        
        for column in columns:
            print(f"   - {column['name']}: {column['type']} {'(NOT NULL)' if not column['nullable'] else '(NULL)'}")
        
    except Exception as e:
        print(f"❌ Erro: {e}")

if __name__ == "__main__":
    main()
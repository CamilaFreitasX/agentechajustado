#!/usr/bin/env python3
"""
Script para verificar e adicionar todas as colunas faltantes na tabela notas_fiscais
"""

import psycopg2
from secure_config import get_secure_config

def main():
    try:
        # Obter configuração
        config = get_secure_config()
        
        # Conectar ao banco
        conn = psycopg2.connect(config.DATABASE_URL)
        cursor = conn.cursor()
        
        print("✅ Conectado ao banco de dados PostgreSQL")
        
        # Verificar estrutura atual da tabela
        cursor.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns 
            WHERE table_name = 'notas_fiscais'
            ORDER BY ordinal_position;
        """)
        
        colunas_existentes = cursor.fetchall()
        print("\n📋 Estrutura atual da tabela notas_fiscais:")
        for coluna in colunas_existentes:
            print(f"  - {coluna[0]} ({coluna[1]}) - Nullable: {coluna[2]}")
        
        # Lista de todas as colunas esperadas baseadas no código
        colunas_esperadas = {
            'id': 'SERIAL PRIMARY KEY',
            'numero': 'VARCHAR(50) NOT NULL',
            'serie': 'VARCHAR(10)',
            'data_emissao': 'DATE',
            'cnpj_emitente': 'VARCHAR(18)',
            'nome_emitente': 'VARCHAR(255)',
            'valor_total': 'DECIMAL(15,2)',
            'chave_acesso': 'VARCHAR(44)',
            'natureza_operacao': 'VARCHAR(255)',
            'situacao': 'VARCHAR(50)',
            'data_vencimento': 'DATE',
            'cnpj_destinatario': 'VARCHAR(18)',
            'nome_destinatario': 'VARCHAR(255)',
            'valor_icms': 'DECIMAL(15,2)',
            'valor_ipi': 'DECIMAL(15,2)',
            'valor_pis': 'DECIMAL(15,2)',
            'valor_cofins': 'DECIMAL(15,2)',
            'xml_original': 'TEXT',
            'processado_em': 'TIMESTAMP',
            'itens': 'TEXT',
            'xml_content': 'TEXT'
        }
        
        # Verificar quais colunas estão faltando
        nomes_existentes = [col[0] for col in colunas_existentes]
        colunas_faltantes = []
        
        for nome_coluna, tipo_coluna in colunas_esperadas.items():
            if nome_coluna not in nomes_existentes:
                colunas_faltantes.append((nome_coluna, tipo_coluna))
        
        if colunas_faltantes:
            print(f"\n⚠️  Encontradas {len(colunas_faltantes)} colunas faltantes:")
            for nome, tipo in colunas_faltantes:
                print(f"  - {nome} ({tipo})")
            
            # Adicionar colunas faltantes
            print("\n🔧 Adicionando colunas faltantes...")
            for nome_coluna, tipo_coluna in colunas_faltantes:
                try:
                    # Remover PRIMARY KEY se existir (só para id)
                    if 'PRIMARY KEY' in tipo_coluna:
                        tipo_coluna = tipo_coluna.replace(' PRIMARY KEY', '')
                    
                    sql = f"ALTER TABLE notas_fiscais ADD COLUMN {nome_coluna} {tipo_coluna};"
                    print(f"  Executando: {sql}")
                    cursor.execute(sql)
                    print(f"  ✅ Coluna '{nome_coluna}' adicionada com sucesso")
                except Exception as e:
                    print(f"  ❌ Erro ao adicionar coluna '{nome_coluna}': {e}")
            
            # Commit das alterações
            conn.commit()
            print("\n✅ Todas as alterações foram salvas")
        else:
            print("\n✅ Todas as colunas necessárias já existem na tabela")
        
        # Verificar estrutura final
        cursor.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns 
            WHERE table_name = 'notas_fiscais'
            ORDER BY ordinal_position;
        """)
        
        colunas_finais = cursor.fetchall()
        print(f"\n📋 Estrutura final da tabela notas_fiscais ({len(colunas_finais)} colunas):")
        for coluna in colunas_finais:
            print(f"  - {coluna[0]} ({coluna[1]}) - Nullable: {coluna[2]}")
        
        cursor.close()
        conn.close()
        print("\n🔒 Conexão fechada")
        
    except Exception as e:
        print(f"❌ Erro: {e}")

if __name__ == "__main__":
    main()
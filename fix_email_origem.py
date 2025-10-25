#!/usr/bin/env python3
"""
Script para corrigir a origem de registros que vieram de email
mas estão marcados incorretamente como 'upload'
"""

import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

def main():
    # Carregar configurações
    load_dotenv()
    DATABASE_URL = os.getenv('DATABASE_URL')
    
    if not DATABASE_URL:
        print("Erro: DATABASE_URL não configurada")
        return
    
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        # Primeiro, verificar quais registros têm xml_original (indicativo de email)
        result = conn.execute(text("""
            SELECT id, numero, nome_emitente, origem 
            FROM notas_fiscais 
            WHERE xml_original IS NOT NULL AND xml_original != ''
        """))
        registros_email = list(result)
        
        print(f"Encontrados {len(registros_email)} registros com XML original (provavelmente de email):")
        for row in registros_email:
            print(f"  ID: {row[0]} - Nota {row[1]} - {row[2]} - Origem atual: {row[3]}")
        
        # Atualizar esses registros para origem 'email'
        if registros_email:
            result = conn.execute(text("""
                UPDATE notas_fiscais 
                SET origem = 'email' 
                WHERE xml_original IS NOT NULL AND xml_original != ''
            """))
            conn.commit()
            print(f"\nAtualizados {len(registros_email)} registros para origem 'email'")
        
        # Verificar o resultado final
        result = conn.execute(text("SELECT origem, COUNT(*) FROM notas_fiscais GROUP BY origem"))
        print("\nDistribuição atualizada por origem:")
        for row in result:
            origem = row[0] if row[0] is not None else 'NULL'
            print(f"  {origem}: {row[1]} registros")

if __name__ == "__main__":
    main()
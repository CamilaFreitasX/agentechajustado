import imaplib
import os
from dotenv import load_dotenv
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_email_connection():
    """Testa a conexão IMAP com as configurações do .env"""
    
    # Limpar cache de variáveis de ambiente relacionadas ao email
    for key in ['EMAIL_USER', 'EMAIL_PASSWORD', 'IMAP_SERVER', 'IMAP_PORT']:
        if key in os.environ:
            del os.environ[key]
    
    # Carregar variáveis do .env forçando override
    load_dotenv(override=True)
    
    email_user = os.getenv('EMAIL_USER')
    email_password = os.getenv('EMAIL_PASSWORD')
    imap_server = os.getenv('IMAP_SERVER')
    imap_port = int(os.getenv('IMAP_PORT', 993))
    
    print("=== TESTE DE CONEXÃO EMAIL ===")
    print(f"Servidor IMAP: {imap_server}")
    print(f"Porta: {imap_port}")
    print(f"Usuário: {email_user}")
    print(f"Senha: {email_password[:4]}...{email_password[-4:] if email_password and len(email_password) > 8 else 'Não configurada'}")
    print()
    
    if not all([email_user, email_password, imap_server]):
        print("❌ ERRO: Configurações de email incompletas no arquivo .env")
        print("Verifique se EMAIL_USER, EMAIL_PASSWORD e IMAP_SERVER estão definidos")
        return False
    
    try:
        print("🔄 Tentando conectar ao servidor IMAP...")
        mail = imaplib.IMAP4_SSL(imap_server, imap_port)
        
        print("🔄 Tentando fazer login...")
        mail.login(email_user, email_password)
        
        print("✅ Login realizado com sucesso!")
        
        print("🔄 Selecionando caixa de entrada...")
        mail.select('inbox')
        
        print("🔄 Verificando emails não lidos...")
        status, messages = mail.search(None, 'UNSEEN')
        
        if status == 'OK':
            email_ids = messages[0].split() if messages[0] else []
            print(f"📧 Encontrados {len(email_ids)} emails não lidos")
        else:
            print("⚠️ Não foi possível buscar emails não lidos")
        
        print("🔄 Verificando total de emails...")
        status, messages = mail.search(None, 'ALL')
        
        if status == 'OK':
            total_emails = len(messages[0].split()) if messages[0] else 0
            print(f"📧 Total de emails na caixa de entrada: {total_emails}")
        
        mail.logout()
        print("✅ Conexão testada com sucesso!")
        return True
        
    except imaplib.IMAP4.error as e:
        print(f"❌ ERRO IMAP: {e}")
        print("Possíveis causas:")
        print("- Credenciais incorretas")
        print("- Servidor IMAP incorreto")
        print("- Porta incorreta")
        print("- Autenticação de 2 fatores ativada (use senha de app)")
        return False
        
    except Exception as e:
        print(f"❌ ERRO GERAL: {e}")
        return False

if __name__ == "__main__":
    test_email_connection()
import imaplib
import email
from email.header import decode_header
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Lista de palavras-chave para filtrar no assunto (em minúsculo)
PALAVRAS_CHAVE = ["danfe", "nf-e", "nfc-e", "nf", "nfe", "xml", "nota fiscal"]

def buscar_emails_recentes():
    """Busca emails dos últimos 7 dias que contenham palavras-chave"""
    
    # Carregar variáveis do .env
    load_dotenv(override=True)
    
    email_user = os.getenv('EMAIL_USER')
    email_password = os.getenv('EMAIL_PASSWORD')
    imap_server = os.getenv('IMAP_SERVER')
    imap_port = int(os.getenv('IMAP_PORT', 993))
    
    print("=== BUSCA DE EMAILS RECENTES COM PALAVRAS-CHAVE ===")
    print(f"Servidor: {imap_server}")
    print(f"Usuário: {email_user}")
    print(f"Palavras-chave: {', '.join(PALAVRAS_CHAVE)}")
    print()
    
    try:
        # Conectar ao servidor
        mail = imaplib.IMAP4_SSL(imap_server, imap_port)
        mail.login(email_user, email_password)
        mail.select('inbox')
        
        # Calcular data de 7 dias atrás
        data_limite = datetime.now() - timedelta(days=7)
        data_limite_str = data_limite.strftime("%d-%b-%Y")
        
        print(f"🔍 Buscando emails desde: {data_limite_str}")
        
        # Buscar emails dos últimos 7 dias
        status, messages = mail.search(None, f'SINCE {data_limite_str}')
        
        if status != 'OK' or not messages[0]:
            print("❌ Nenhum email encontrado nos últimos 7 dias")
            mail.logout()
            return
        
        email_ids = messages[0].split()
        print(f"📧 Encontrados {len(email_ids)} emails nos últimos 7 dias")
        print()
        
        emails_com_palavras_chave = []
        emails_nao_lidos = []
        
        for email_id in email_ids:
            try:
                # Buscar informações do email
                status, msg_data = mail.fetch(email_id, '(RFC822 FLAGS)')
                if status != 'OK': 
                    continue
                
                # Verificar se é não lido
                flags_data = msg_data[0][0].decode()
                is_unread = '\\Seen' not in flags_data
                
                if is_unread:
                    emails_nao_lidos.append(email_id)
                
                # Processar mensagem
                msg = email.message_from_bytes(msg_data[0][1])
                
                # Decodificar assunto
                subject_parts = decode_header(msg["Subject"])
                subject_decoded = []
                
                for part, enc in subject_parts:
                    if isinstance(part, bytes):
                        if not enc or enc.lower() == "unknown-8bit":
                            enc = "utf-8"
                        try:
                            subject_decoded.append(part.decode(enc, errors="ignore"))
                        except LookupError:
                            subject_decoded.append(part.decode("utf-8", errors="ignore"))
                    else:
                        subject_decoded.append(part)
                
                subject = " ".join(subject_decoded).strip()
                subject_lower = subject.lower() if subject else ""
                
                # Verificar palavras-chave
                palavras_encontradas = [palavra for palavra in PALAVRAS_CHAVE if palavra in subject_lower]
                
                if palavras_encontradas:
                    # Obter data do email
                    date_str = msg.get('Date', 'Data não disponível')
                    
                    # Verificar anexos
                    tem_anexos = False
                    anexos_xml_pdf = []
                    
                    for part in msg.walk():
                        if part.get_content_maintype() == 'multipart' or part.get('Content-Disposition') is None:
                            continue
                        
                        filename = part.get_filename()
                        if filename:
                            tem_anexos = True
                            filename_lower = filename.lower()
                            if filename_lower.endswith('.xml') or filename_lower.endswith('.pdf'):
                                anexos_xml_pdf.append(filename)
                    
                    emails_com_palavras_chave.append({
                        'id': email_id.decode(),
                        'subject': subject,
                        'date': date_str,
                        'palavras_encontradas': palavras_encontradas,
                        'is_unread': is_unread,
                        'tem_anexos': tem_anexos,
                        'anexos_xml_pdf': anexos_xml_pdf
                    })
                    
            except Exception as e:
                logger.error(f"Erro ao processar email {email_id}: {e}")
                continue
        
        # Relatório
        print(f"📊 RELATÓRIO:")
        print(f"   • Total de emails nos últimos 7 dias: {len(email_ids)}")
        print(f"   • Emails não lidos: {len(emails_nao_lidos)}")
        print(f"   • Emails com palavras-chave: {len(emails_com_palavras_chave)}")
        print()
        
        if emails_com_palavras_chave:
            print("📋 EMAILS COM PALAVRAS-CHAVE ENCONTRADOS:")
            print("-" * 80)
            
            for i, email_info in enumerate(emails_com_palavras_chave, 1):
                status_leitura = "🔴 NÃO LIDO" if email_info['is_unread'] else "🔵 LIDO"
                anexos_info = f"📎 {len(email_info['anexos_xml_pdf'])} XML/PDF" if email_info['anexos_xml_pdf'] else "❌ Sem anexos XML/PDF"
                
                print(f"{i}. {status_leitura}")
                print(f"   Assunto: {email_info['subject']}")
                print(f"   Data: {email_info['date']}")
                print(f"   Palavras encontradas: {', '.join(email_info['palavras_encontradas'])}")
                print(f"   Anexos: {anexos_info}")
                if email_info['anexos_xml_pdf']:
                    print(f"   Arquivos: {', '.join(email_info['anexos_xml_pdf'])}")
                print()
        else:
            print("❌ Nenhum email com palavras-chave encontrado nos últimos 7 dias")
        
        mail.logout()
        
    except Exception as e:
        print(f"❌ ERRO: {e}")

if __name__ == "__main__":
    buscar_emails_recentes()
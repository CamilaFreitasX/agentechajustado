import imaplib
import email
from email.header import decode_header
import logging
from datetime import datetime, timedelta

from nf_processor import DatabaseManager, XMLExtractor, ValidadorNF, PDFExtractor
from security_utils import (
    SecurityAuditor, 
    SecurityConfig, 
    DataSanitizer,
    rate_limiter
)
from secure_config import get_secure_config, SecureConfigError

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Lista de palavras-chave para filtrar no assunto (em minúsculo)
PALAVRAS_CHAVE = ["danfe", "nf-e", "nfc-e", "nf", "nfe", "xml", "nota fiscal"]

def buscar_e_processar_emails():
    """
    Busca e processa emails com validações de segurança
    """
    # Verificar rate limiting
    if not rate_limiter.is_allowed("email_processing", max_requests=10, window_minutes=60):
        logger.warning("ROBÔ: Rate limit excedido para processamento de emails")
        return
    
    # Log de início de sessão
    SecurityAuditor.log_security_event(
        "EMAIL_PROCESSING_START",
        {"timestamp": datetime.now().isoformat()},
        "INFO"
    )
    
    try:
        config = get_secure_config()
        db_manager = DatabaseManager(config)
    except SecureConfigError as e:
        logger.error(f"ROBÔ: Erro ao carregar configuração segura: {e}")
        SecurityAuditor.log_security_event(
            "CONFIG_ERROR",
            {"error": str(e)},
            "ERROR"
        )
        return
    except Exception as e:
        logger.error(f"ROBÔ: Erro ao conectar ao banco: {e}")
        SecurityAuditor.log_security_event(
            "CONFIG_ERROR",
            {"error": str(e)},
            "ERROR"
        )
        return

    logger.info("ROBÔ: Iniciando processo de busca de notas fiscais no e-mail...")
    try:
        mail = imaplib.IMAP4_SSL(config.IMAP_SERVER, config.IMAP_PORT)
        mail.login(config.EMAIL_USER, config.EMAIL_PASSWORD)
        mail.select('inbox')
        
        # Busca e-mails não lidos
        status, messages = mail.search(None, 'UNSEEN')
        
        if status != 'OK' or not messages[0]:
            logger.info("ROBÔ: Nenhuma mensagem nova encontrada.")
            mail.logout()
            return
            
        email_ids = messages[0].split()
        logger.info(f"ROBÔ: Encontrados {len(email_ids)} e-mails novos.")

        for email_id in email_ids:
            status, msg_data = mail.fetch(email_id, '(RFC822)')
            if status != 'OK': continue

            msg = email.message_from_bytes(msg_data[0][1])

            # Decodifica o assunto
            subject_parts = decode_header(msg["Subject"])
            subject_decoded = []

            for part, enc in subject_parts:
                if isinstance(part, bytes):
                    # Se o encoding for None, 'unknown-8bit' ou inválido, usa fallback
                    if not enc or enc.lower() == "unknown-8bit":
                        enc = "utf-8"
                    try:
                        subject_decoded.append(part.decode(enc, errors="ignore"))
                    except LookupError:  # caso encoding não seja reconhecido
                        subject_decoded.append(part.decode("utf-8", errors="ignore"))
                else:
                    subject_decoded.append(part)

            # Junta tudo em uma string
            subject = " ".join(subject_decoded).strip()
            subject_lower = subject.lower() if subject else ""

            # Verifica se contém alguma palavra-chave
            if not any(palavra in subject_lower for palavra in PALAVRAS_CHAVE):
                logger.info(f"ROBÔ: E-mail ignorado (assunto sem palavras-chave): {subject}")
                # Marca como lido para não processar de novo
                mail.store(email_id, '+FLAGS', '\\Seen')
                continue

            logger.info(f"ROBÔ: Processando e-mail com assunto: {subject}")

            for part in msg.walk():
                if part.get_content_maintype() == 'multipart' or part.get('Content-Disposition') is None:
                    continue
                
                filename = part.get_filename()
                if not filename:
                    continue

                # Sanitizar nome do arquivo
                filename_safe = DataSanitizer.sanitize_string(filename)
                filename_lower = filename_safe.lower()

                # Validar extensão de arquivo
                if not (filename_lower.endswith('.xml') or filename_lower.endswith('.pdf')):
                    logger.warning(f"ROBÔ: Tipo de arquivo não permitido: {filename_safe}")
                    SecurityAuditor.log_security_event(
                        "INVALID_FILE_TYPE",
                        {"filename": filename_safe, "email_subject": subject},
                        "WARNING"
                    )
                    continue

                # Obter conteúdo do anexo
                try:
                    file_content = part.get_payload(decode=True)
                    if not file_content:
                        logger.warning(f"ROBÔ: Conteúdo vazio no arquivo: {filename_safe}")
                        continue
                except Exception as e:
                    logger.error(f"ROBÔ: Erro ao decodificar anexo {filename_safe}: {e}")
                    continue

                # Validar tamanho do arquivo
                file_size = len(file_content)
                max_size = SecurityConfig.MAX_XML_SIZE if filename_lower.endswith('.xml') else SecurityConfig.MAX_PDF_SIZE
                
                if file_size > max_size:
                    logger.warning(f"ROBÔ: Arquivo muito grande: {filename_safe} ({file_size} bytes)")
                    SecurityAuditor.log_security_event(
                        "FILE_SIZE_EXCEEDED",
                        {"filename": filename_safe, "size": file_size, "max_size": max_size},
                        "WARNING"
                    )
                    continue

                # 📄 XML
                if filename_lower.endswith('.xml'):
                    logger.info(f"ROBÔ: Anexo XML encontrado: {filename_safe}")
                    
                    # Usar extrator seguro com nome do arquivo
                    nota = XMLExtractor.extrair_dados_xml(file_content, filename_safe)
                    
                    if nota and ValidadorNF.validar_nota_fiscal(nota):
                        try:
                            db_manager.salvar_nota_fiscal(nota)
                            SecurityAuditor.log_security_event(
                                "NF_PROCESSED_SUCCESS",
                                {"filename": filename_safe, "nf_numero": nota.numero, "type": "XML"},
                                "INFO"
                            )
                        except Exception as e:
                            logger.error(f"ROBÔ: Erro ao salvar NF do XML {filename_safe}: {e}")
                            SecurityAuditor.log_security_event(
                                "DATABASE_ERROR",
                                {"filename": filename_safe, "error": str(e)},
                                "ERROR"
                            )
                    elif nota:
                        logger.warning(f"ROBÔ: NF {nota.numero or 'S/N'} inválida do arquivo {filename_safe}")
                        SecurityAuditor.log_security_event(
                            "INVALID_NF",
                            {"filename": filename_safe, "nf_numero": nota.numero},
                            "WARNING"
                        )
                    else:
                        logger.error(f"ROBÔ: Falha ao extrair dados do XML '{filename_safe}'")

                # 📄 PDF
                elif filename_lower.endswith('.pdf'):
                    logger.info(f"ROBÔ: Anexo PDF encontrado: {filename_safe}")
                    
                    # Validar tamanho específico para PDF
                    if file_size > SecurityConfig.MAX_PDF_SIZE:
                        logger.warning(f"ROBÔ: PDF muito grande: {filename_safe}")
                        continue
                    
                    nota = PDFExtractor.extrair_dados_pdf(file_content)
                    if nota and ValidadorNF.validar_nota_fiscal(nota):
                        try:
                            db_manager.salvar_nota_fiscal(nota)
                            SecurityAuditor.log_security_event(
                                "NF_PROCESSED_SUCCESS",
                                {"filename": filename_safe, "nf_numero": nota.numero, "type": "PDF"},
                                "INFO"
                            )
                        except Exception as e:
                            logger.error(f"ROBÔ: Erro ao salvar NF do PDF {filename_safe}: {e}")
                            SecurityAuditor.log_security_event(
                                "DATABASE_ERROR",
                                {"filename": filename_safe, "error": str(e)},
                                "ERROR"
                            )
                    elif nota:
                        logger.warning(f"ROBÔ: NF {nota.numero or 'S/N'} inválida do arquivo {filename_safe}")
                        SecurityAuditor.log_security_event(
                            "INVALID_NF",
                            {"filename": filename_safe, "nf_numero": nota.numero},
                            "WARNING"
                        )
                    else:
                        logger.error(f"ROBÔ: Falha ao extrair dados do PDF '{filename_safe}'")

            # Marca como lido
            mail.store(email_id, '+FLAGS', '\\Seen')

        mail.logout()
    except imaplib.IMAP4.error as e:
        logger.error(f"ROBÔ: Erro de IMAP: {e}")
    except Exception as e:
        logger.error(f"ROBÔ: Ocorreu um erro inesperado: {e}")

if __name__ == "__main__":
    buscar_e_processar_emails()

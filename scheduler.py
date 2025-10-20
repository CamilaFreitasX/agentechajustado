import schedule
import time
import logging
from processar_emails import buscar_e_processar_emails

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def job():
    logger.info("--- AGENDADOR: Iniciando tarefa de verificação de e-mails... ---")
    try:
        buscar_e_processar_emails()
        logger.info("--- AGENDADOR: Tarefa finalizada. Próxima execução em 5 minutos. ---")
    except Exception as e:
        logger.error(f"--- AGENDADOR: Erro na execução da tarefa: {e} ---")

if __name__ == "__main__":
    logger.info("--> Agendador iniciado. Executando a primeira verificação agora...")
    job() # Executa a primeira vez imediatamente
    
    schedule.every(5).minutes.do(job)

    while True:
        schedule.run_pending()
        time.sleep(1)
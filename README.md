# Agente Fiscal com IA 🤖

Este projeto é um sistema de automação inteligente projetado para processar notas fiscais eletrônicas (NF-e) de forma contínua. O agente monitora uma caixa de entrada de e-mail, extrai dados de anexos XML de NF-e, os valida, armazena em um banco de dados na nuvem e apresenta as informações em um dashboard interativo. Além disso, utiliza a IA do Google Gemini para permitir análises dos dados fiscais através de linguagem natural.

## ✨ Funcionalidades

* **Automação Contínua:** Um robô agendado verifica a caixa de entrada de e-mails a cada 5 minutos em busca de novas notas fiscais.
* **Processamento Inteligente:** Extração automática de todos os dados relevantes do XML da NF-e, incluindo itens, valores e impostos.
* **Dashboard Interativo:** Uma interface web criada com Streamlit para visualização de métricas, gráficos e análise detalhada das notas.
* **Chat Fiscal com IA:** Converse com seus dados! Faça perguntas em português sobre seus gastos, fornecedores e produtos, com respostas geradas pela API do Google Gemini.
* **Sistema de Autenticação:** Controle de acesso com login/logout, sessões seguras e diferentes níveis de permissão.
* **Gerenciamento de Usuários:** Interface administrativa para criar, listar, ativar/desativar usuários e resetar senhas.
* **Armazenamento na Nuvem:** Utiliza um banco de dados PostgreSQL robusto e gratuito hospedado na plataforma Render.com.
* **Segurança Avançada:** Sistema completo de segurança com validação XML, sanitização de dados, auditoria, rate limiting e gerenciamento seguro de credenciais.

## 🚀 Tecnologias Utilizadas

* **Backend:** Python
* **Interface Web:** Streamlit
* **Banco de Dados:** PostgreSQL (hospedado no Render.com)
* **Inteligência Artificial:** Google Gemini
* **Manipulação de Dados:** Pandas
* **Comunicação com DB:** SQLAlchemy
* **Agendamento de Tarefas:** Schedule
* **Segurança:** defusedxml, bleach, validators, cryptography

---

## 🔒 Funcionalidades de Segurança

O sistema implementa múltiplas camadas de segurança para proteger seus dados fiscais:

### Validação XML Segura
* **Proteção contra XXE:** Utiliza `defusedxml` para prevenir ataques XML External Entity
* **Validação de estrutura:** Verifica a integridade dos arquivos XML de NF-e
* **Limite de tamanho:** Rejeita arquivos XML excessivamente grandes

### Sanitização de Dados
* **Limpeza de strings:** Remove caracteres maliciosos e scripts
* **Validação de CNPJ:** Verifica formato e dígitos verificadores
* **Sanitização de chaves de acesso:** Valida formato das chaves de NF-e
* **Validação numérica:** Garante que valores monetários sejam seguros

### Auditoria e Monitoramento
* **Log de segurança:** Registra todas as operações críticas
* **Rastreamento de processamento:** Monitora arquivos processados
* **Detecção de anomalias:** Identifica padrões suspeitos

### Rate Limiting
* **Controle de requisições:** Limita número de operações por período
* **Proteção contra spam:** Previne sobrecarga do sistema
* **Configuração flexível:** Ajustável via variáveis de ambiente

### Gerenciamento Seguro de Credenciais
* **Criptografia:** Senhas e chaves são criptografadas
* **Mascaramento:** Dados sensíveis são ocultados nos logs
* **Validação de ambiente:** Verifica configurações obrigatórias

---

## ⚙️ Guia de Instalação e Uso

Siga os passos abaixo para ter o projeto rodando em sua máquina.

### Etapa 1: Pré-requisitos

* Python 3.9 ou superior.
* Git instalado em sua máquina.

### Etapa 2: Obter o Projeto

Clone este repositório para a sua máquina local:

```bash
git clone https://github.com/CamilaFreitasX/agentechajustado.git
cd agentechajustado
```

### Etapa 3: Instalar as Dependências
Execute o comando abaixo para instalar todas as bibliotecas que o projeto precisa:

```Bash

pip install -r requirements.txt
```

### Etapa 4: Configurar as Variáveis de Ambiente (.env)
As chaves secretas (senhas, APIs) são gerenciadas através de um arquivo .env. Primeiro, crie sua cópia pessoal deste arquivo:

```Bash

# No Windows
copy .env.example .env

# No Linux ou macOS
cp .env.example .env

```

Agora, abra o arquivo .env recém-criado e preencha os valores de acordo com as instruções abaixo.

#### 1. DATABASE_URL (Banco de Dados na Nuvem)
**Esta é a URL de conexão para o seu banco de dados PostgreSQL.**

 1.1 Acesse render.com e crie uma conta.

 1.2 No seu dashboard, clique em New + e selecione PostgreSQL.

 1.3 Preencha as informações solicitadas (Nome, Região, etc.) e escolha o plano Free.

 1.4 Clique em Create Database e aguarde alguns minutos.

 1.5 Após a criação, na página do seu banco de dados, vá para a seção Connections.

 1.6 Localize o campo External Connection String e clique para copiar o valor.

 1.7 Ação: Cole esta URL completa no seu arquivo .env, na variável DATABASE_URL.

#### 2. GEMINI_API_KEY (Inteligência Artificial)
**Esta chave dá acesso à IA do Google Gemini para a funcionalidade de chat.**

 2.1 Acesse o Google AI Studio.

 2.2 Faça login com sua conta Google.

 2.3 Clique em Get API key no menu à esquerda e depois em Create API key in new project.

 2.4 Copie a chave gerada.

 2.5 Ação: Cole esta chave no seu arquivo .env, na variável GEMINI_API_KEY.

#### 3. EMAIL_USER e EMAIL_PASSWORD (Credenciais do Gmail)
**Estas são as credenciais para que o robô possa ler os e-mails com as notas fiscais.**

EMAIL_USER

 3.1 Ação: Preencha com seu endereço de e-mail completo do Gmail. (Ex: seu.email@gmail.com).

EMAIL_PASSWORD

**⚠️ ATENÇÃO: Você não deve usar sua senha normal do Gmail. Por segurança, o Google exige uma "Senha de App" para aplicações de terceiros.**

 3.2 Como gerar uma Senha de App:

 3.3 Acesse as configurações da sua Conta Google.

 3.4 Vá para a seção Segurança.

 3.5 Certifique-se de que a Verificação em duas etapas está ativada. Ela é um pré-requisito obrigatório.

 3.6 Na mesma página de Segurança, procure e clique na opção Senhas de app.

 3.7 Dê um nome para a senha (ex: Agente Fiscal Python) e clique em Gerar.

 3.8 O Google irá gerar uma senha de 16 letras, sem espaços. Copie esta senha.

 3.9 Ação: Cole esta senha de 16 letras no seu arquivo .env, na variável EMAIL_PASSWORD.

#### 4. IMAP_SERVER e IMAP_PORT (Configurações Opcionais do Gmail)
Estas variáveis definem o servidor e a porta para conexão com o serviço de e-mail.

Os valores padrão para o Gmail (imap.gmail.com e 993) já estão no arquivo .env.example.

Ação: Para uma conta padrão do Gmail, você não precisa alterar esses valores. Eles já estão corretos.

#### 5. Configurações de Segurança (Opcionais)
O sistema inclui configurações avançadas de segurança que podem ser personalizadas:

```bash
# Limite de tentativas de login
MAX_LOGIN_ATTEMPTS=3

# Timeout da sessão em minutos
SESSION_TIMEOUT_MINUTES=30

# Habilitar log de auditoria
ENABLE_AUDIT_LOG=true

# Limite de emails por hora
MAX_EMAILS_PER_HOUR=100

# Limite de arquivos por requisição
MAX_FILES_PER_REQUEST=10

# Tamanho máximo de arquivo em MB
MAX_FILE_SIZE_MB=50
```

**Nota:** Estas configurações são opcionais e o sistema funcionará com valores padrão se não forem especificadas.

### Etapa 5: Configurar o Sistema
Com o arquivo .env preenchido, o sistema criará automaticamente as tabelas necessárias no banco de dados na primeira execução.

**Importante:** O sistema inclui autenticação de usuários. Na primeira execução, será criado automaticamente um usuário administrador padrão:
- **Usuário:** `admin`
- **Senha:** `admin123`

⚠️ **Recomendação de Segurança:** Altere a senha padrão imediatamente após o primeiro login através da funcionalidade de gerenciamento de usuários.

### ▶️ Como Executar a Aplicação

#### Opção 1: Aplicação Completa com Autenticação (Recomendado)
Execute o sistema principal com autenticação e gerenciamento de usuários:

```bash
streamlit run nf_processor_with_auth.py --server.port 8505
```

Após executar, acesse: **http://localhost:8505**

**Primeiro Acesso:**
1. Faça login com as credenciais padrão: `admin` / `admin123`
2. Vá para a aba "👥 Gerenciar Usuários" para alterar a senha
3. Crie novos usuários conforme necessário

#### Opção 2: Robô Agendador (Opcional)
Para processamento automático de e-mails, execute em terminal separado:

```bash
python scheduler.py
```

Este processo verifica e-mails a cada 5 minutos e pode rodar em segundo plano.

#### Funcionalidades Disponíveis:
- **📊 Dashboard:** Visualização de métricas e gráficos
- **📁 Upload:** Envio manual de arquivos XML/PDF
- **🤖 Chat Fiscal:** Análise de dados com IA
- **👥 Gerenciar Usuários:** Criação e administração de usuários (apenas admins)
- **📧 Processar E-mails:** Verificação manual da caixa de entrada







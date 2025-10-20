# Documentação de Segurança - Agente Fiscal com IA 🔒

Este documento detalha as implementações de segurança do sistema Agente Fiscal com IA.

## 📋 Visão Geral

O sistema implementa múltiplas camadas de segurança para proteger dados fiscais sensíveis, incluindo validação XML, sanitização de dados, auditoria, rate limiting e gerenciamento seguro de credenciais.

## 🛡️ Componentes de Segurança

### 1. XMLSecurityValidator (`security_utils.py`)

**Propósito:** Validação segura de arquivos XML de NF-e

**Funcionalidades:**
- Proteção contra ataques XXE (XML External Entity)
- Validação de estrutura XML
- Limite de tamanho de arquivo (50MB padrão)
- Verificação de encoding

**Métodos principais:**
- `parse_xml_safely()`: Parse seguro usando defusedxml
- `validate_xml_structure()`: Validação de estrutura
- `_check_file_size()`: Verificação de tamanho

### 2. DataSanitizer (`security_utils.py`)

**Propósito:** Sanitização e validação de dados de entrada

**Funcionalidades:**
- Limpeza de strings maliciosas
- Validação de CNPJ com dígitos verificadores
- Sanitização de chaves de acesso NF-e
- Validação de valores numéricos

**Métodos principais:**
- `sanitize_string()`: Remove HTML/scripts maliciosos
- `sanitize_cnpj()`: Valida formato e dígitos do CNPJ
- `sanitize_chave_acesso()`: Valida chaves de 44 dígitos
- `sanitize_numeric_value()`: Valida valores monetários

### 3. SecurityAuditor (`security_utils.py`)

**Propósito:** Auditoria e logging de segurança

**Funcionalidades:**
- Log de eventos de segurança
- Rastreamento de processamento de arquivos
- Detecção de anomalias
- Armazenamento seguro de logs

**Métodos principais:**
- `log_security_event()`: Registra eventos de segurança
- `log_file_processing()`: Monitora processamento de arquivos

### 4. RateLimiter (`security_utils.py`)

**Propósito:** Controle de taxa de requisições

**Funcionalidades:**
- Limite configurável de requisições por período
- Proteção contra spam e ataques DDoS
- Janela deslizante de tempo
- Configuração flexível via ambiente

**Métodos principais:**
- `is_allowed()`: Verifica se requisição é permitida
- `_cleanup_old_requests()`: Remove requisições antigas

### 5. CredentialManager (`secure_config.py`)

**Propósito:** Gerenciamento seguro de credenciais

**Funcionalidades:**
- Criptografia de senhas e chaves
- Mascaramento de dados sensíveis
- Validação de configurações obrigatórias
- Carregamento seguro de variáveis de ambiente

**Métodos principais:**
- `encrypt_credential()`: Criptografa credenciais
- `decrypt_credential()`: Descriptografa credenciais
- `mask_sensitive_data()`: Mascara dados nos logs

## 🔧 Configuração de Segurança

### Variáveis de Ambiente

```bash
# Configurações de Rate Limiting
MAX_EMAILS_PER_HOUR=100
MAX_FILES_PER_REQUEST=10
MAX_FILE_SIZE_MB=50

# Configurações de Sessão
MAX_LOGIN_ATTEMPTS=3
SESSION_TIMEOUT_MINUTES=30

# Auditoria
ENABLE_AUDIT_LOG=true
```

### Dependências de Segurança

```
defusedxml>=0.7.1      # XML seguro
bleach>=6.0.0          # Sanitização HTML
validators>=0.20.0     # Validação de dados
cryptography>=41.0.0   # Criptografia
```

## 🧪 Testes de Segurança

O arquivo `test_security.py` contém testes abrangentes para todas as funcionalidades:

### Testes Implementados:
1. **XML Security**: Parse seguro, proteção XXE, limite de tamanho
2. **Data Sanitization**: Strings, CNPJ, chaves de acesso, valores numéricos
3. **Rate Limiting**: Controle de requisições, bloqueio de spam
4. **Security Auditing**: Logs de eventos e processamento
5. **Secure Configuration**: Carregamento e mascaramento de dados

### Executar Testes:
```bash
python test_security.py
```

## 📊 Monitoramento de Segurança

### Logs de Auditoria
- Localização: `security_audit.log`
- Formato: JSON estruturado
- Conteúdo: Eventos de segurança, processamento de arquivos, anomalias

### Métricas de Segurança
- Taxa de requisições bloqueadas
- Tentativas de acesso inválidas
- Arquivos rejeitados por validação
- Eventos de segurança por período

## 🚨 Alertas e Incidentes

### Cenários de Alerta:
1. **XML Malicioso**: Tentativa de XXE ou estrutura inválida
2. **Rate Limiting**: Excesso de requisições
3. **Dados Inválidos**: CNPJ ou chave de acesso malformados
4. **Falha de Autenticação**: Credenciais inválidas

### Resposta a Incidentes:
1. Log automático do evento
2. Bloqueio temporário (se aplicável)
3. Notificação via log de auditoria
4. Análise posterior via dashboard

## 🔄 Manutenção de Segurança

### Atualizações Regulares:
- Dependências de segurança
- Configurações de rate limiting
- Revisão de logs de auditoria
- Testes de penetração

### Backup de Segurança:
- Logs de auditoria
- Configurações de segurança
- Chaves de criptografia (se aplicável)

## 📞 Contato de Segurança

Para reportar vulnerabilidades ou questões de segurança, entre em contato através dos canais oficiais do projeto.

---

**Última atualização:** Janeiro 2025
**Versão:** 1.0.0
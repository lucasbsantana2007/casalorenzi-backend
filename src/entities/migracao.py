"""Migração única dos dados da Vulto (src/migracao_vulto). Cada problema encontrado num dado vira
uma ocorrência (migracao_ocorrencias), base do registro de decisões (docs/registro_decisoes.md)."""

# Etapas do pipeline, na ordem em que rodam (python -m src.migracao_vulto --dominio <nome>). "staging"
# é a cópia crua do legado no schema legado_vulto; os outros são os domínios da plataforma.
DOMINIOS_MIGRACAO = ("staging", "lojas", "produtos", "clientes", "usuarios", "vendas", "estoque", "fidelidade", "atendimento")

# O que a migração fez com o dado problemático
ACOES_OCORRENCIA = ("CORRIGIDO", "DESCARTADO", "ESTIMADO", "MANTIDO", "PENDENTE")

# Unidade do impacto de uma ocorrência no número final
UNIDADES_IMPACTO = ("REAIS", "PONTOS", "UNIDADES", "REGISTROS")

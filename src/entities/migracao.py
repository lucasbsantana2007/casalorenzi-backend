"""Migração única dos dados da Vulto (src/migracao_vulto). Cada problema encontrado num dado vira
uma ocorrência (migracao_ocorrencias), base do registro de decisões (docs/registro_decisoes.md)."""

# Domínios do pipeline, na ordem em que rodam (python -m src.migracao_vulto --dominio <nome>)
DOMINIOS_MIGRACAO = ("lojas", "produtos", "clientes", "usuarios", "vendas", "estoque", "fidelidade", "atendimento")

# O que a migração fez com o dado problemático
ACOES_OCORRENCIA = ("CORRIGIDO", "DESCARTADO", "ESTIMADO", "MANTIDO", "PENDENTE")

# Unidade do impacto de uma ocorrência no número final
UNIDADES_IMPACTO = ("REAIS", "PONTOS", "UNIDADES", "REGISTROS")

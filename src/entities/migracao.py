"""Migração única dos dados da Vulto para a plataforma.

A limpeza foi feita no repositório da Vulto (copy.vulto-legado-back): o data/vulto_corrigido.db e as
tabelas *_padronizadas do data/vulto.db são a fonte. Aqui ficam:
- decisoes_migracao: o registro de decisões (o que encontramos, onde, quantos registros, o que
  decidimos, por quê e o impacto no número final), na numeração do registro da Vulto (1 a 65) e
  continuando com as da união (66 em diante, docs/registro_decisoes_uniao.md);
- de_para: de onde veio cada registro migrado (origem + id na origem → tabela + id aqui).

Não há lista de pendências: o que estava nas abas "Pendências" das planilhas virou decisão.
"""

AREAS_MIGRACAO = ("CATALOGO", "CLIENTES", "FIDELIDADE", "VENDAS", "ESTOQUE", "ATENDIMENTO", "GERAL")

# Tipo da decisão, como no registro da Vulto: automático (óbvio, sem conflito), padrão assumido (barato
# de errar, fácil de desfazer) ou negócio (custa caro ou não dá para desfazer; decidido com a diretoria)
TIPOS_DECISAO = ("AUTOMATICO", "PADRAO_ASSUMIDO", "NEGOCIO")
# A_DECIDIR: decisão registrada mas ainda não aplicada nos números (ex.: decisões 40 e 41 da Vulto)
SITUACOES_DECISAO = ("APLICADA", "A_DECIDIR")

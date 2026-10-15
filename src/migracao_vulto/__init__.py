"""Migração única dos dados da Vulto para a plataforma (uma marca a mais, no mesmo schema).

Três camadas: staging cru no schema legado_vulto → transformação (um módulo por domínio, com as
funções de normalizacao.py) → carga no schema public. O legado é só leitura.

Idempotente: cada domínio pode rodar de novo e chega ao mesmo resultado (de_para evita duplicar;
as ocorrências do domínio são refeitas). Nunca apaga dados da Casa Lorenzi.

    python -m src.migracao_vulto --tudo
    python -m src.migracao_vulto --dominio lojas
"""

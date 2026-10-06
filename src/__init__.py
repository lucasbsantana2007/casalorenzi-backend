"""Casa Lorenzi API. A organização das pastas segue o padrão de boas práticas da Insper Jr.:

config/        o que muda por ambiente (.env)
database/      conexão com o banco e dados de demonstração
models/        como cada dado vira tabela (um arquivo por tabela)
entities/      regras do próprio dado (status, transições, cálculos puros)
repositories/  a única parte que busca e salva no banco
use_cases/     o que o sistema faz: as regras de negócio
schemas/       contratos da API: o que entra e o que sai
routers/       rotas HTTP, finas: recebem, chamam o use case e respondem
middlewares/   login (JWT), permissões e registro das requisições
utils/         funções pequenas e genéricas (datas, texto, senhas, e-mail)
"""

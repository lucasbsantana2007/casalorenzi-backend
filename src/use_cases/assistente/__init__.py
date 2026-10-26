"""Assistentes de IA da plataforma (docs/assistente_ia.md).

- conversas: abrir, ler e encerrar conversas, com o controle de quem é o dono;
- orquestrador: uma rodada (mensagem do usuário -> regras ou modelo + ferramentas -> resposta);
- ferramentas, ferramentas_cliente, ferramentas_gerenciais: as consultas que os assistentes podem fazer;
- regras_cliente, regras_gerenciais: as respostas sem modelo de linguagem (determinísticas);
- catalogo: busca de peças e disponibilidade para o assistente do site;
- prompts: as instruções fixas e o contexto de cada rodada.
"""

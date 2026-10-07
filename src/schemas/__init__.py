"""Contratos da API, um arquivo por módulo:

- classes *Entrada: o que o frontend pode enviar (validado pelo Pydantic, em camelCase);
- funções *_saida: o JSON devolvido, no formato da camada de serviços do frontend
  (camelCase, datas em milissegundos, objetos relacionados embutidos).

Separar entrada e saída evita expor campos internos (hash de senha, por exemplo).
"""

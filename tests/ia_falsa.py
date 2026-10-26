"""Modelo de linguagem falso para os testes: devolve respostas roteirizadas e guarda o que recebeu.

Cada item do roteiro é uma RespostaIA, uma exceção (ErroIA, para simular timeout/erro) ou uma função
(recebe o pedido e devolve RespostaIA), consumidos em ordem a cada chamada a gerar()."""

from src.integrations.ia import ChamadaFerramentaIA, ErroIA, RespostaIA


def texto(conteudo: str) -> RespostaIA:
    return RespostaIA(
        texto=conteudo,
        chamadas=[],
        parada="end_turn",
        conteudo=[{"type": "text", "text": conteudo}],
        modelo="claude-haiku-5-5",
        tokens_entrada=1000,
        tokens_saida=50,
        tokens_cache_leitura=800,
    )


def ferramenta(nome: str, argumentos, id_: str = "toolu_1", fala: str = "") -> RespostaIA:
    conteudo = [{"type": "tool_use", "id": id_, "name": nome, "input": argumentos}]
    if fala:
        conteudo.insert(0, {"type": "text", "text": fala})
    return RespostaIA(
        texto=fala,
        chamadas=[ChamadaFerramentaIA(id=id_, nome=nome, argumentos=argumentos)],
        parada="tool_use",
        conteudo=conteudo,
        modelo="claude-haiku-5-5",
        tokens_entrada=1200,
        tokens_saida=60,
    )


def varias(*chamadas: tuple[str, dict]) -> RespostaIA:
    """Várias ferramentas na mesma resposta (chamadas paralelas)."""
    lista = [ChamadaFerramentaIA(id=f"toolu_{i}", nome=nome, argumentos=args) for i, (nome, args) in enumerate(chamadas, 1)]
    conteudo = [{"type": "tool_use", "id": c.id, "name": c.nome, "input": c.argumentos} for c in lista]
    return RespostaIA(
        texto="",
        chamadas=lista,
        parada="tool_use",
        conteudo=conteudo,
        modelo="claude-haiku-5-5",
        tokens_entrada=1200,
        tokens_saida=60,
    )


def recusa() -> RespostaIA:
    return RespostaIA(
        texto="", chamadas=[], parada="refusal", conteudo=[], modelo="claude-haiku-5-5", tokens_entrada=900, tokens_saida=5
    )


class ProvedorFalso:
    nome = "falso"
    modelo = "claude-haiku-5-5"

    def __init__(self, *roteiro):
        self.roteiro = list(roteiro)
        self.pedidos: list[dict] = []

    def gerar(self, *, sistema, ferramentas, mensagens, sem_ferramentas=False) -> RespostaIA:
        pedido = {
            "sistema": sistema,
            "ferramentas": ferramentas,
            "mensagens": list(mensagens),
            "sem_ferramentas": sem_ferramentas,
        }
        self.pedidos.append(pedido)
        if not self.roteiro:
            return texto("Fim do roteiro.")
        proximo = self.roteiro.pop(0)
        if isinstance(proximo, Exception):
            raise proximo
        if callable(proximo):
            return proximo(pedido)
        return proximo

    def nomes_oferecidos(self, indice: int = 0) -> set[str]:
        return {f["name"] for f in self.pedidos[indice]["ferramentas"]}

    def resultados_de_ferramenta(self) -> list[dict]:
        """Os tool_result que o backend devolveu ao modelo, em ordem."""
        resultados = []
        for pedido in self.pedidos:
            for mensagem in pedido["mensagens"]:
                if mensagem["role"] == "user" and isinstance(mensagem["content"], list):
                    resultados.extend(b for b in mensagem["content"] if isinstance(b, dict) and b.get("type") == "tool_result")
        # Os pedidos repetem o histórico: tira as repetições
        vistos, unicos = set(), []
        for resultado in resultados:
            if resultado["tool_use_id"] not in vistos:
                vistos.add(resultado["tool_use_id"])
                unicos.append(resultado)
        return unicos


def erro(tipo: str = "TIMEOUT") -> ErroIA:
    return ErroIA(tipo, f"falha simulada ({tipo})", 25000 if tipo == "TIMEOUT" else 10)

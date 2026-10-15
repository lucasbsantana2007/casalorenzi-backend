"""Resultado de cada domínio da migração e o relatório impresso no fim."""

from dataclasses import dataclass, field


@dataclass
class Resultado:
    """lidos: registros de origem; carregados: entraram na plataforma (novos ou atualizados);
    corrigidos: entraram com algum valor ajustado; descartados: não entraram (sempre com ocorrência)."""

    dominio: str
    lidos: int = 0
    carregados: int = 0
    corrigidos: int = 0
    descartados: int = 0
    ocorrencias: dict[str, int] = field(default_factory=dict)
    # Detalhe impresso depois da tabela (ex.: linhas por origem no staging)
    notas: list[str] = field(default_factory=list)


def formatar(resultados: list[Resultado]) -> str:
    cabecalho = f"{'domínio':<12} {'lidos':>8} {'carregados':>11} {'corrigidos':>11} {'descartados':>12}  ocorrências"
    linhas = [cabecalho, "-" * len(cabecalho)]
    for r in resultados:
        ocorrencias = ", ".join(f"{acao} {n}" for acao, n in sorted(r.ocorrencias.items())) or "—"
        linhas.append(f"{r.dominio:<12} {r.lidos:>8} {r.carregados:>11} {r.corrigidos:>11} {r.descartados:>12}  {ocorrencias}")
    for r in resultados:
        if r.notas:
            linhas += ["", f"[{r.dominio}]", *r.notas]
    return "\n".join(linhas)

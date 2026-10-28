"""A bateria da Lúcia (tests/bateria_lucia.py) sem o Claude: as regras, que respondem quando não há chave e quando
o modelo cai. Toda mudança na Lúcia passa por aqui. Com o Claude de verdade: scripts/avaliar_lucia.py."""

import pytest

from tests.bateria_lucia import CASOS, rodar


@pytest.mark.parametrize("caso", [c for c in CASOS if not c.so_com_modelo], ids=lambda c: f"{c.numero:02d}-{c.assunto}")
def test_bateria_sem_o_claude(client, caso):
    resposta, faltas = rodar(client, caso)
    assert not faltas, f"#{caso.numero} {caso.pergunta!r}: {faltas}. Resposta: {resposta['texto']!r}"

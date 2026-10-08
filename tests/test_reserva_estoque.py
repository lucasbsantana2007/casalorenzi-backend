"""Reserva no checkout: a peça vendida fica prometida até o envio, mesmo antes de sair do estoque.
Sem isso, dois clientes comprariam a mesma última peça e o segundo pedido travaria na expedição."""

import threading
import time

from fastapi.testclient import TestClient

from src.app import app
from src.database.seed import SENHA_DEMO
from src.use_cases import checkout

PECA = {
    "nome": "Camisa Última Peça",
    "categoria": "Camisaria",
    "precoBase": 300,
    "ativo": True,
    "genero": "Masculino",
    "variacoes": [{"sku": "CL-ULT-AZU-M", "tamanho": "M", "cor": "Azul", "precoCusto": 120}],
}
ENDERECO = {"cep": "01310-100", "rua": "Av. Paulista", "numero": "1", "bairro": "Bela Vista", "cidade": "São Paulo", "uf": "SP"}


def _entrar(client, email):
    r = client.post("/api/auth/login", json={"email": email, "senha": SENHA_DEMO})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _peca_com_estoque(client, admin, por_loja: dict[int, int]) -> int:
    """Cria a peça e dá entrada das quantidades em cada loja. Devolve o id da variação."""
    variacao_id = client.post("/api/produtos", headers=admin, json=PECA).json()["variacoes"][0]["id"]
    for loja_id, quantidade in por_loja.items():
        estoque = client.get(f"/api/estoque?variacaoId={variacao_id}&lojaId={loja_id}", headers=admin).json()[0]
        mov = {"estoqueId": estoque["id"], "tipo": "ENTRADA", "quantidade": quantidade, "origem": "NF"}
        assert client.post("/api/movimentacoes", headers=admin, json=mov).status_code == 201
    return variacao_id


def _comprar(client, headers, variacao_id, quantidade=1):
    compra = {
        "endereco": ENDERECO,
        "freteTipo": "PADRAO",
        "pagamento": {"metodo": "PIX"},
        "itens": [{"variacaoId": variacao_id, "quantidade": quantidade}],
    }
    return client.post("/api/checkout", headers=headers, json=compra)


def _variacao(client, variacao_id):
    produtos = client.get("/api/produtos").json()
    return next(v for p in produtos for v in p["variacoes"] if v["id"] == variacao_id)


def test_a_ultima_peca_nao_e_vendida_duas_vezes(client, admin, mariana):
    variacao_id = _peca_com_estoque(client, admin, {1: 1})
    ricardo = _entrar(client, "ricardo.fonseca@outlook.com")

    primeiro = _comprar(client, mariana, variacao_id)
    assert primeiro.status_code == 201, primeiro.text
    # A peça continua na loja até o envio, mas a vitrine já a mostra esgotada
    peca = _variacao(client, variacao_id)
    assert peca["estoqueTotal"] == 1 and peca["disponivel"] == 0

    segundo = _comprar(client, ricardo, variacao_id)
    assert segundo.status_code == 409 and "esgotou" in segundo.json()["detail"]

    # Cancelar o primeiro libera a peça para outra compra
    pedido = client.get(f"/api/pedidos?busca={primeiro.json()['numero']}", headers=admin).json()[0]
    assert client.patch(f"/api/pedidos/{pedido['id']}", headers=admin, json={"status": "CANCELADO"}).status_code == 200
    assert _variacao(client, variacao_id)["disponivel"] == 1
    assert _comprar(client, ricardo, variacao_id).status_code == 201


def test_dois_pedidos_nao_puxam_a_mesma_peca(client, admin, mariana):
    """Uma peça em cada loja: cada pedido fica com uma, sem transferência prometendo a peça do outro."""
    variacao_id = _peca_com_estoque(client, admin, {1: 1, 2: 1})
    ricardo = _entrar(client, "ricardo.fonseca@outlook.com")

    numeros = [_comprar(client, h, variacao_id).json()["numero"] for h in (mariana, ricardo)]
    pedidos = [client.get(f"/api/pedidos?busca={n}", headers=admin).json()[0] for n in numeros]
    assert pedidos[0]["lojaId"] != pedidos[1]["lojaId"]  # o segundo vai para a loja com a peça livre

    # As duas peças são enviadas: cada pedido tem a sua na própria loja de expedição
    for pedido in pedidos:
        r = client.patch(f"/api/pedidos/{pedido['id']}", headers=admin, json={"status": "ENVIADO", "codigoRastreio": "BR1"})
        assert r.status_code == 200, r.text

    assert _comprar(client, mariana, variacao_id).status_code == 409


def test_falta_vira_transferencia_da_peca_livre(client, admin, mariana):
    """Duas peças pedidas, uma em cada loja: a expedição recebe a outra por transferência."""
    variacao_id = _peca_com_estoque(client, admin, {1: 1, 3: 1})
    r = _comprar(client, mariana, variacao_id, quantidade=2)
    assert r.status_code == 201, r.text
    pedido_id = client.get(f"/api/pedidos?busca={r.json()['numero']}", headers=admin).json()[0]["id"]
    transferencias = client.get(f"/api/pedidos/{pedido_id}", headers=admin).json()["transferencias"]
    assert sum(t["quantidade"] for t in transferencias) == 1
    assert _variacao(client, variacao_id)["disponivel"] == 0


def test_compras_simultaneas_da_ultima_peca(admin, monkeypatch):
    """Dois checkouts ao mesmo tempo: a trava faz um esperar o outro, e só um leva a peça."""
    conferir = checkout.disponiveis_na_rede

    def conferir_devagar(db, variacao_ids):
        # Alarga a janela entre conferir o estoque e gravar o pedido, para as duas compras se cruzarem
        disponivel = conferir(db, variacao_ids)
        time.sleep(0.5)
        return disponivel

    monkeypatch.setattr(checkout, "disponiveis_na_rede", conferir_devagar)
    client = TestClient(app)
    variacao_id = _peca_com_estoque(client, admin, {1: 1})
    clientes = [_entrar(client, "mariana.costa@gmail.com"), _entrar(client, "ricardo.fonseca@outlook.com")]
    status = []
    largada = threading.Barrier(len(clientes))

    def comprar(headers):
        largada.wait()
        status.append(_comprar(TestClient(app), headers, variacao_id).status_code)

    threads = [threading.Thread(target=comprar, args=(h,)) for h in clientes]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(status) == [201, 409]

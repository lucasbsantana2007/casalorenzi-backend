"""Padronização dos dados da Vulto (src/migracao_vulto/normalizacao.py), com os exemplos reais
encontrados nas origens. Valor vazio vira None; valor que não converte com segurança levanta
ValorInvalido (quem chama registra a ocorrência)."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.migracao_vulto import normalizacao as n


def invalido(funcao, *args, **kwargs):
    with pytest.raises(n.ValorInvalido):
        funcao(*args, **kwargs)


# ---------- Dinheiro ----------


@pytest.mark.parametrize(
    ("origem", "esperado"),
    [
        ("R$ 149,90", "149.90"),
        ("379,80", "379.80"),
        ("129.8", "129.80"),
        ("1.234,56", "1234.56"),
        ("-289,90", "-289.90"),
        ("19081", "19081.00"),
        (149.9, "149.90"),
        (52, "52.00"),
    ],
)
def test_dinheiro_em_reais_com_duas_casas(origem, esperado):
    assert n.dinheiro(origem) == Decimal(esperado)


def test_dinheiro_vazio_e_invalido():
    assert n.dinheiro(None) is None and n.dinheiro("") is None and n.dinheiro("  ") is None
    invalido(n.dinheiro, "abc")
    invalido(n.dinheiro, "12,3,4")


def test_centavos_so_como_interpretacao_possivel_de_um_inteiro():
    """O app grava "19081" para R$ 190,81: o texto sozinho não diz qual é; a venda decide."""
    assert n.escalas("19081") == {"reais": Decimal("19081.00"), "centavos": Decimal("190.81")}
    assert n.escalas("190,81") == {"reais": Decimal("190.81")}
    assert n.escalas(None) == {}


# ---------- Datas ----------


def test_datas_sem_fuso_sao_de_brasilia_e_z_e_utc():
    local = n.data_hora("2025-01-01 12:47:42")
    assert local.momento == datetime(2025, 1, 1, 12, 47, 42, tzinfo=n.FUSO_ORIGEM) and local.precisao == "segundo"
    utc = n.data_hora("2025-01-01T12:04:39Z")
    assert utc.momento == datetime(2025, 1, 1, 12, 4, 39, tzinfo=UTC)
    assert utc.momento.astimezone(n.FUSO_ORIGEM).hour == 9
    assert n.data_hora("2025-02-27T19:42:00-03:00").momento == datetime(2025, 2, 27, 22, 42, tzinfo=UTC)
    assert n.data_hora("2025-09-01T10:38:41.000000").momento.tzinfo is not None


@pytest.mark.parametrize(
    ("origem", "dia", "precisao"),
    [
        ("01/01/2025 14:02", date(2025, 1, 1), "minuto"),
        ("05/01/2025", date(2025, 1, 5), "dia"),
        ("19/03/25", date(2025, 3, 19), "dia"),
        ("2025-03-19", date(2025, 3, 19), "dia"),
        ("jan/23", date(2023, 1, 1), "mes"),
        ("set/2023", date(2023, 9, 1), "mes"),
        (44351, date(2021, 6, 4), "dia"),  # número de série do Excel
        (datetime(2026, 2, 3), date(2026, 2, 3), "dia"),
    ],
)
def test_formatos_de_data_da_vulto(origem, dia, precisao):
    lida = n.data_hora(origem)
    assert (lida.momento.date(), lida.precisao) == (dia, precisao)


def test_data_sem_ano_so_com_ano_padrao_e_data_inexistente_e_invalida():
    invalido(n.data_hora, "02/03")
    assert n.data_hora("02/03", ano_padrao=2026).momento.date() == date(2026, 3, 2)
    assert n.data_hora("44351", serial_excel=True).momento.date() == date(2021, 6, 4)
    invalido(n.data_hora, "44351")  # texto só de dígitos não é data sem o aviso de que veio do Excel
    invalido(n.data_hora, "31/02/2025")
    invalido(n.data_hora, "ontem")


def test_datas_ordenam_pelo_momento_e_nao_pelo_texto():
    """Como texto, "20/01/2025" vem antes de "2025-..." e "2026-10-01T02:28:31Z" é o maior; no tempo, não."""
    textos = ["2026-10-01T02:28:31Z", "20/01/2025 15:21", "2025-01-01T12:04:39Z", "30/09/2026 22:00"]
    em_ordem = sorted(textos, key=lambda t: n.data_hora(t).momento)
    assert em_ordem == ["2025-01-01T12:04:39Z", "20/01/2025 15:21", "30/09/2026 22:00", "2026-10-01T02:28:31Z"]
    # 02:28 UTC de 1º/10 ainda é 30/09 em Brasília
    assert n.data_hora("2026-10-01T02:28:31Z").momento.astimezone(n.FUSO_ORIGEM).date() == date(2026, 9, 30)


# ---------- Pessoas e contato ----------


def test_cpf_sem_mascara_e_com_digito_validado():
    assert n.cpf("936.216.440-08") == "93621644008"
    assert n.cpf(" 441 954 145 80") == "44195414580"
    assert n.cpf(27773285284) == "27773285284"
    assert n.cpf(1234567890) == "01234567890"  # o Excel comeu o zero à esquerda
    assert n.cpf("1234567890", numero_excel=True) == "01234567890"
    assert n.cpf("") is None
    invalido(n.cpf, "117.120.379-61")  # dígito verificador errado (está na planilha de clientes)
    invalido(n.cpf, "1234567890")  # texto com 10 dígitos: sem o aviso do Excel, não completa
    invalido(n.cpf, "fulano@gmail.com")
    invalido(n.cpf, "111.111.111-11")


def test_email_minusculo_sem_espacos():
    assert n.email(" Larissa.Batista87@BOL.com.br ") == "larissa.batista87@bol.com.br"
    assert n.email("ana @gmail.com") == "ana@gmail.com"
    invalido(n.email, "nao tem")
    invalido(n.email, "-")


@pytest.mark.parametrize(
    ("origem", "esperado"),
    [
        ("11951021527", "+5511951021527"),
        ("+55 11 91217-2644", "+5511912172644"),
        ("85960465366", "+5585960465366"),
        ("(11) 98369-1660", "+5511983691660"),
        ("11 33334444", "+551133334444"),
    ],
)
def test_telefone_em_e164(origem, esperado):
    assert n.telefone(origem) == esperado


def test_telefone_sem_ddd_nao_e_adivinhado():
    invalido(n.telefone, "90429-6274")
    invalido(n.telefone, "123")


def test_instagram_nome_e_texto():
    assert n.instagram("@nicole.lima") == "nicole.lima"
    assert n.instagram("https://instagram.com/Nicole.Lima/") == "nicole.lima"
    invalido(n.instagram, "@nome com espaço")
    assert n.nome_pessoa("  ALINE   BARROS ") == "ALINE BARROS"
    assert n.nome_pessoa("Larissa V. Batista") == "Larissa V. Batista"
    assert n.texto_livre("  oi\r\nquero trocar  ") == "oi\nquero trocar"
    assert n.texto_livre("   ") is None


def test_referencia_do_cliente_mistura_cpf_email_e_telefone():
    assert n.referencia_cliente("401.324.108-00") == n.Referencia("cpf", "40132410800")
    assert n.referencia_cliente("Henrique.Silva25@gmail.com") == n.Referencia("email", "henrique.silva25@gmail.com")
    assert n.referencia_cliente("11951021527") == n.Referencia("telefone", "+5511951021527")
    # 11 dígitos que passam no dígito do CPF e também parecem celular: fica CPF, marcado como ambíguo
    assert n.referencia_cliente("11951021517") == n.Referencia("cpf", "11951021517", ambigua=True)
    assert n.referencia_cliente(None) is None
    invalido(n.referencia_cliente, "NAO INFORMADO")
    invalido(n.referencia_cliente, "consumidor")


# ---------- Produto ----------


@pytest.mark.parametrize(
    ("grafia", "canonico"),
    [
        ("VLT-BER-004-JES-36", "VLT-BER-004-JES-36"),
        ("vlt-cal-001-vin-38", "VLT-CAL-001-VIN-38"),
        ("BER001B40", "VLT-BER-001-BRA-40"),
        ("CAM016GP", "VLT-CAM-016-BEG-P"),
        ("MOL014VGG", "VLT-MOL-014-OLI-GG"),
        ("ACE010GU", "VLT-ACE-010-BEG-U"),
        ("vlt ber 001 branco 38", "VLT-BER-001-BRA-38"),
        ("vlt cam 012 verde oliva p", "VLT-CAM-012-OLI-P"),
        ("vlt ves 010 off white p", "VLT-VES-010-OFF-P"),
    ],
)
def test_todas_as_grafias_de_sku_chegam_no_canonico(grafia, canonico):
    assert n.interpretar_sku(grafia).canonico == canonico


def test_grafia_sem_tamanho_e_grafia_ilegivel():
    sem_tamanho = n.interpretar_sku("vlt ves 006 marrom")  # linha de vários tamanhos no Inverno 25
    assert (sem_tamanho.modelo, sem_tamanho.cor, sem_tamanho.tamanho) == ("VES-006", "MRR", None)
    invalido(lambda: sem_tamanho.canonico)
    invalido(n.interpretar_sku, "DIVERSO")
    invalido(n.interpretar_sku, "VLT-MOL-001-RMR-G")  # erro de digitação na contagem
    assert n.alias_normalizado("  vlt  ber 001   branco 38 ") == "VLT BER 001 BRANCO 38"


def test_ean_13_digitos_com_verificador():
    assert n.ean(7897969295881) == "7897969295881"
    assert n.ean("7897969295881") == "7897969295881"
    invalido(n.ean, "7890000000000")  # o "EAN" que aparece em várias peças diferentes
    invalido(n.ean, "7890231000000")  # dígito verificador errado
    invalido(n.ean, "123")
    assert n.ean(None) is None


def test_cor_tamanho_e_categoria_no_padrao():
    assert {n.cor(c) for c in ("White", "BRANCO", "Branco", "bco")} == {"BRANCO"}
    assert {n.cor(c) for c in ("BEGE", "bege", "Areia")} == {"BEGE"}
    assert n.cor("vd oliva") == "VERDE OLIVA" and n.codigo_cor("Dark Denim") == "JES"
    invalido(n.cor, "roxo")
    assert n.tamanho("gg ") == "GG" and n.tamanho("Unico") == "U" and n.tamanho("ÚNICO") == "U" and n.tamanho("XL") == "GG"
    assert n.tamanhos("P/M/G/GG") == ["P", "M", "G", "GG"] and n.tamanhos("36/38/40/42/44")[-1] == "44"
    invalido(n.tamanho, "XXG")
    for texto in ("BERMUDA/SHORT", "Bermudas", "Bottoms > Short", "shorts"):
        assert n.categoria(texto) == "Bermudas e Shorts"
    for texto in ("Tops > Camiseta", "camiseta básica", "Camisetas", "Camiseta/Regata", "Moletons", "TOP/CROPPED"):
        assert n.categoria(texto) == "Malharia"
    assert n.categoria("Tops > Camisa") == "Camisaria" and n.categoria("Bottoms > Calça") == "Calças"
    assert n.categoria("Acessorios > Bonés") == "Acessórios"
    invalido(n.categoria, "Diversos")
    assert n.categoria_do_sku(n.interpretar_sku("TRI012CM")) == "Tricô"


# ---------- Venda e genéricos ----------


def test_canal_vem_da_loja_e_nao_do_texto():
    assert [n.canal(i) for i in (1, 2, 3, 4)] == ["Loja física"] * 4
    assert (n.canal(5), n.canal("6")) == ("E-commerce", "App")
    invalido(n.canal, 7)  # o CD não vende


def test_status_do_legado():
    for texto in ("pago", "PAGO", "Pago", "aprovado"):
        assert n.status(texto) == ("ENTREGUE", "APROVADO")
    assert n.status("aguardando") == ("PROCESSANDO", "PENDENTE")
    assert n.status("cancelado") == n.status("CANCELADA") == ("CANCELADO", None)
    assert n.status("estornado") == n.status("chargeback") == ("CANCELADO", "ESTORNADO")
    assert n.status("") is None  # o vazio é decidido na migração das vendas
    invalido(n.status, "devolvido")


def test_booleano():
    assert all(n.booleano(v) is True for v in ("1", "x", "S", "sim", 1))
    assert all(n.booleano(v) is False for v in ("N", "0", "não", "nao", 0))
    assert n.booleano("") is None and n.booleano(None) is None
    invalido(n.booleano, "talvez")

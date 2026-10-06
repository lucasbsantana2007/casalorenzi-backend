"""Dados fixos de demonstração: os mesmos de src/data/seed do frontend."""

SENHA_DEMO = "lorenzi2026"
# PIN de "Meus pedidos" de todos os clientes de demonstração (PIN_DEMO do frontend)
PIN_DEMO = "1234"
DIA = 86_400_000
HISTORICO_DIAS = 75

LOJAS = [
    (1, "Oscar Freire", "São Paulo", "SP"),
    (2, "Lago Sul", "Brasília", "DF"),
    (3, "Leblon", "Rio de Janeiro", "RJ"),
    (4, "Pátio Batel", "Curitiba", "PR"),
    (5, "Belvedere", "Belo Horizonte", "MG"),
]

CATEGORIAS = ["Camisaria", "Alfaiataria", "Vestidos", "Tricô", "Malharia", "Saias", "Outerwear", "Acessórios"]

USUARIOS = [
    (1, "Helena Lorenzi", "helena@casalorenzi.com.br", "ADMINISTRADOR", None),
    (2, "Rafael Monteiro", "rafael.monteiro@casalorenzi.com.br", "LOJISTA", 1),
    (3, "Beatriz Carvalho", "beatriz.carvalho@casalorenzi.com.br", "LOJISTA", 2),
    (4, "André Siqueira", "andre.siqueira@casalorenzi.com.br", "LOJISTA", 3),
    (5, "Camila Rocha", "camila.rocha@casalorenzi.com.br", "LOJISTA", 4),
    (6, "Diego Almeida", "diego.almeida@casalorenzi.com.br", "OPERADOR", 1),
    (7, "Carla Nunes", "carla.nunes@casalorenzi.com.br", "OPERADOR", 3),
    (8, "Marina Duarte", "marina.duarte@casalorenzi.com.br", "LOJISTA", 5),
]

# id, nome, email, telefone, cliente desde, loja preferida
CLIENTES = [
    (101, "Mariana Costa", "mariana.costa@gmail.com", "(11) 98422-1937", "2021-03-14", 1),
    (102, "Ricardo Fonseca", "ricardo.fonseca@outlook.com", "(61) 99710-4402", "2019-11-02", 2),
    (103, "Juliana Prado", "ju.prado@gmail.com", "(21) 98134-7750", "2022-06-21", 3),
    (104, "Felipe Andrade", "felipe.andrade@icloud.com", "(41) 99288-3016", "2023-01-09", 4),
    (105, "Luiza Bastos", "luiza.bastos@gmail.com", "(21) 99640-2281", "2020-08-30", 3),
    (106, "Gustavo Tavares", "gustavo.tavares@gmail.com", "(31) 97455-6190", "2024-02-17", 5),
    (107, "Patrícia Moreira", "patricia.moreira@uol.com.br", "(61) 98820-5573", "2018-05-05", 2),
    (108, "Thiago Ribeiro", "thiago.ribeiro@gmail.com", "(41) 99107-8834", "2023-09-12", 4),
]

# As variações são tamanhos × cores. genero/estacao alimentam a vitrine.
PRODUTOS = [
    dict(
        id=1,
        genero="Masculino",
        estacao="Verão",
        nome="Camisa de Linho Toscana",
        categoria="Camisaria",
        preco=489,
        codigo="CML",
        tamanhos=["P", "M", "G"],
        cores=["Branco", "Azul Céu"],
    ),
    dict(
        id=2,
        genero="Masculino",
        estacao="Atemporal",
        nome="Camisa de Linho Positano",
        categoria="Camisaria",
        preco=369,
        codigo="COX",
        tamanhos=["P", "M", "G"],
        cores=["Marinho"],
    ),
    dict(
        id=3,
        genero="Masculino",
        estacao="Verão",
        nome="Calça de Linho Amalfi",
        categoria="Alfaiataria",
        preco=649,
        codigo="CAL",
        tamanhos=["40", "42", "44"],
        cores=["Grafite", "Marinho"],
    ),
    dict(
        id=4,
        genero="Masculino",
        estacao="Inverno",
        nome="Blazer Milano",
        categoria="Alfaiataria",
        preco=1490,
        codigo="BLZ",
        tamanhos=["48", "50", "52"],
        cores=["Marinho"],
    ),
    dict(
        id=5,
        genero="Feminino",
        estacao="Verão",
        nome="Vestido Midi de Seda",
        categoria="Vestidos",
        preco=1190,
        codigo="VMS",
        tamanhos=["P", "M", "G"],
        cores=["Off-white", "Verde Oliva"],
    ),
    dict(
        id=6,
        genero="Feminino",
        estacao="Inverno",
        nome="Suéter de Cashmere Gola Careca",
        categoria="Tricô",
        preco=1290,
        codigo="SCC",
        tamanhos=["P", "M", "G"],
        cores=["Camel"],
    ),
    dict(
        id=7,
        genero="Feminino",
        estacao="Inverno",
        nome="Cardigã de Lã Merino",
        categoria="Tricô",
        preco=789,
        codigo="CLM",
        tamanhos=["P", "M", "G"],
        cores=["Cinza Mescla"],
    ),
    dict(
        id=8,
        genero="Masculino",
        estacao="Verão",
        nome="Polo Piquet Pima",
        categoria="Malharia",
        preco=329,
        codigo="PPP",
        tamanhos=["P", "M", "G"],
        cores=["Marinho", "Branco"],
    ),
    dict(
        id=9,
        genero="Feminino",
        estacao="Atemporal",
        nome="Saia Plissada Midi",
        categoria="Saias",
        preco=559,
        codigo="SPM",
        tamanhos=["36", "38", "40"],
        cores=["Preto"],
    ),
    dict(
        id=10,
        genero="Feminino",
        estacao="Inverno",
        nome="Trench Coat Gabardine",
        categoria="Outerwear",
        preco=2190,
        codigo="TRC",
        tamanhos=["P", "M", "G"],
        cores=["Bege"],
    ),
    dict(
        id=11,
        genero="Masculino",
        estacao="Atemporal",
        nome="Cinto de Couro Trançado",
        categoria="Acessórios",
        preco=279,
        codigo="CCT",
        tamanhos=["90", "100"],
        cores=["Conhaque"],
    ),
    dict(
        id=12,
        genero="Feminino",
        estacao="Verão",
        nome="Lenço de Seda Estampado",
        categoria="Acessórios",
        preco=349,
        codigo="LSE",
        tamanhos=["Único"],
        cores=["Azul Riviera"],
    ),
    dict(
        id=13,
        genero="Masculino",
        estacao="Verão",
        nome="Bermuda de Sarja Resort",
        categoria="Alfaiataria",
        preco=399,
        codigo="BSR",
        tamanhos=["40", "42", "44"],
        cores=["Areia"],
        ativo=False,
    ),
]

# id, titulo, categoria, exige venda, ordem, descricao, conta no pós-venda
TIPOS_SOLICITACAO = [
    (1, "Troca de produto", "Pós-venda", True, 1, "Troca por outro tamanho, cor ou modelo.", "TROCA"),
    (2, "Devolução e reembolso", "Pós-venda", True, 2, "Devolução em até 30 dias após o recebimento.", "DEVOLUCAO"),
    (3, "Acompanhamento de entrega", "Pedidos", True, 3, "Dúvidas sobre prazo ou status do envio.", None),
    (4, "Ajuste de costura", "Serviços", True, 4, "Barra, ajuste de cintura ou mangas.", None),
    (5, "Reserva em outra loja", "Disponibilidade", False, 5, "Reservar uma peça disponível em outra unidade.", None),
    (6, "Dúvida sobre produto", "Informações", False, 6, "Medidas, composição e cuidados com a peça.", None),
    (7, "Reclamação", "Qualidade", False, 7, "Relate um problema com produto ou atendimento.", None),
]

# Roteiros de atendimento escritos à mão. autorTipo: CLIENTE | ATENDENTE | SISTEMA
ROTEIROS = [
    dict(
        cliente=101,
        tipo=1,
        status="EM_ANDAMENTO",
        responsavel=2,
        dias=2,
        pedido=0,
        mensagens=[
            (
                "CLIENTE",
                "Olá! Comprei o item {produto} ({cor}, tamanho {tamanho}), mas ficou grande. Gostaria de trocar por um tamanho menor, na mesma cor.",
                0,
            ),
            (
                "ATENDENTE",
                "Oi, Mariana! Tudo bem? Verifiquei aqui e temos a numeração menor disponível na Oscar Freire. Posso separar para você retirar a partir de amanhã?",
                3,
            ),
            ("CLIENTE", "Perfeito, pode separar sim. Passo aí na quinta à tarde.", 5),
        ],
    ),
    dict(
        cliente=101,
        tipo=4,
        status="CONCLUIDO",
        responsavel=2,
        dias=21,
        pedido=1,
        mensagens=[
            ("CLIENTE", "Preciso de um pequeno ajuste no item {produto}. Vocês fazem na loja?", 0),
            (
                "ATENDENTE",
                "Fazemos sim! O ajuste é cortesia e fica pronto em até 5 dias úteis. Pode trazer a peça na Oscar Freire.",
                2,
            ),
            ("SISTEMA", "Peça recebida para ajuste na loja Oscar Freire.", 30),
            ("ATENDENTE", "Mariana, sua peça já está pronta para retirada. Obrigado pela preferência!", 120),
        ],
    ),
    dict(
        cliente=102,
        tipo=3,
        status="ABERTO",
        responsavel=None,
        dias=0,
        pedido=0,
        mensagens=[
            (
                "CLIENTE",
                "Meu pedido consta como enviado, mas o rastreio não atualiza há mais de uma semana. Podem verificar com a transportadora?",
                0,
            ),
        ],
    ),
    dict(
        cliente=103,
        tipo=5,
        status="AGUARDANDO_CLIENTE",
        responsavel=4,
        dias=1,
        pedido=None,
        mensagens=[
            (
                "CLIENTE",
                "Vi no site o vestido midi de seda verde oliva no tamanho P. Tem no Leblon? Se não tiver, conseguem trazer de outra loja?",
                0,
            ),
            (
                "ATENDENTE",
                "Oi, Juliana! No Leblon não temos o P, mas a Oscar Freire tem uma peça. Consigo solicitar a transferência e ela chega em até 3 dias úteis. Posso seguir?",
                4,
            ),
        ],
    ),
    dict(
        cliente=104,
        tipo=2,
        status="EM_ANDAMENTO",
        responsavel=5,
        dias=3,
        pedido=0,
        mensagens=[
            (
                "CLIENTE",
                "Gostaria de devolver o item {produto}. O tamanho {tamanho} não serviu e não há numeração disponível para troca.",
                0,
            ),
            (
                "ATENDENTE",
                "Felipe, recebemos sua solicitação. O reembolso é feito na mesma forma de pagamento após a conferência da peça na loja Pátio Batel.",
                6,
            ),
        ],
    ),
    dict(
        cliente=105,
        tipo=7,
        status="ABERTO",
        responsavel=None,
        dias=0,
        pedido=None,
        mensagens=[
            (
                "CLIENTE",
                "O suéter de cashmere que comprei começou a formar bolinhas depois de duas lavagens à mão, seguindo a etiqueta. Gostaria de uma avaliação.",
                0,
            ),
        ],
    ),
    dict(
        cliente=106,
        tipo=6,
        status="CONCLUIDO",
        responsavel=8,
        dias=9,
        pedido=None,
        mensagens=[
            ("CLIENTE", "Qual a composição do blazer Milano? Ele amassa muito em viagem?", 0),
            (
                "ATENDENTE",
                "Gustavo, o Blazer Milano é 98% lã fria e 2% elastano, com ótima recuperação. Recomendamos transportá-lo em capa e pendurá-lo ao chegar.",
                1,
            ),
            ("CLIENTE", "Ótimo, obrigado!", 2),
        ],
    ),
    dict(
        cliente=107,
        tipo=1,
        status="ABERTO",
        responsavel=None,
        dias=1,
        pedido=0,
        mensagens=[
            (
                "CLIENTE",
                "Ganhei o item {produto} de presente no tamanho {tamanho} e preciso trocar por outro tamanho. Tenho a nota fiscal.",
                0,
            ),
        ],
    ),
    dict(
        cliente=108,
        tipo=3,
        status="CONCLUIDO",
        responsavel=1,
        dias=15,
        pedido=1,
        mensagens=[
            ("CLIENTE", "Meu pedido ainda está em separação. Há previsão de envio?", 0),
            ("ATENDENTE", "Thiago, seu pedido foi despachado hoje. O código de rastreio já está disponível no portal.", 5),
        ],
    ),
    dict(
        cliente=103,
        tipo=4,
        status="EM_ANDAMENTO",
        responsavel=4,
        dias=5,
        pedido=0,
        mensagens=[
            ("CLIENTE", "Gostaria de ajustar a cintura do item {produto}. É possível?", 0),
            (
                "ATENDENTE",
                "É possível sim, Juliana. Nossa costureira atende no Leblon às terças e quintas. Pode trazer a peça quando quiser.",
                3,
            ),
            ("SISTEMA", "Peça recebida para ajuste na loja Leblon.", 50),
        ],
    ),
    dict(
        cliente=102,
        tipo=6,
        status="AGUARDANDO_CLIENTE",
        responsavel=3,
        dias=4,
        pedido=None,
        mensagens=[
            ("CLIENTE", "O trench coat tem forro removível?", 0),
            (
                "ATENDENTE",
                "Ricardo, o forro não é removível, mas é em viscose leve, ideal para meia-estação. Quer que eu reserve um para você provar no Lago Sul?",
                2,
            ),
        ],
    ),
    dict(
        cliente=101,
        tipo=6,
        status="CONCLUIDO",
        responsavel=1,
        dias=40,
        pedido=None,
        mensagens=[
            ("CLIENTE", "O lenço de seda pode ser lavado à mão?", 0),
            ("ATENDENTE", "Recomendamos lavagem a seco para preservar a estampa e o brilho da seda.", 1),
        ],
    ),
]

# Textos da página de produto, por id (src/data/seed/detalhesProdutos.js do frontend)
DETALHES_PRODUTOS = {
    1: dict(
        descricao="Camisa em linho italiano de toque seco e caimento leve, pensada para os dias quentes. Gola italiana, botões de madrepérola e barra arredondada que funciona por dentro ou por fora da calça.",
        composicao="100% linho",
        cuidados="Lavar à mão em água fria. Secar à sombra. Passar a ferro morno com o tecido ainda úmido.",
    ),
    2: dict(
        descricao="Camisa de manga longa em linho lavado, de toque macio e caimento solto. Colarinho clássico e punhos que ficam bem dobrados, para os dias de sol na costa.",
        composicao="100% linho",
        cuidados="Lavar à mão em água fria. Secar à sombra. Passar a ferro morno com o tecido ainda úmido.",
    ),
    3: dict(
        descricao="Calça em linho com cós de elástico e cordão, bolsos laterais e barra reta. Leve e fresca, vai da praia ao jantar à beira-mar.",
        composicao="100% linho",
        cuidados="Lavar à mão ou na máquina em ciclo delicado, em água fria. Secar à sombra.",
    ),
    4: dict(
        descricao="Blazer de dois botões com construção meio-forrada e ombros naturais, inspirado na alfaiataria de Milão. Lapela entalhada e bolsos com lapela.",
        composicao="Tecido: 100% lã. Forro: 100% cupro",
        cuidados="Somente lavagem a seco. Guardar em cabide de ombro largo.",
    ),
    5: dict(
        descricao="Vestido midi em seda pura com decote em V e cintura marcada por amarração. O tecido fluido acompanha o movimento e brilha discretamente à luz do sol.",
        composicao="100% seda",
        cuidados="Lavar à mão em água fria com sabão neutro. Secar na horizontal, à sombra.",
    ),
    6: dict(
        descricao="Suéter em cashmere de fio fino, macio e leve, com gola careca e punhos canelados. Uma peça de base para os dias frios que dura temporadas.",
        composicao="100% cashmere",
        cuidados="Lavar à mão em água fria. Secar na horizontal. Guardar dobrado.",
    ),
    7: dict(
        descricao="Cardigã em lã merino com botões de chifre e bolsos chapados. Modelagem levemente ampla, para usar sobre camisas ou vestidos.",
        composicao="100% lã merino",
        cuidados="Lavar à mão em água fria. Secar na horizontal, longe do sol.",
    ),
    8: dict(
        descricao="Polo em piquet de algodão Pima, de fibra longa e toque sedoso. Gola e punhos em ribana e fenda lateral na barra.",
        composicao="100% algodão Pima",
        cuidados="Lavar na máquina a 30 °C, do avesso. Não usar secadora.",
    ),
    9: dict(
        descricao="Saia midi plissada com cós alto e zíper invisível. As pregas permanentes mantêm o movimento depois de muitas lavagens.",
        composicao="100% poliéster reciclado",
        cuidados="Lavar na máquina em ciclo delicado. Pendurar para secar, sem torcer.",
    ),
    10: dict(
        descricao="Trench coat em gabardine com acabamento repelente à água, abotoamento duplo e cinto. Dragonas, pala nas costas e forro removível.",
        composicao="Tecido: 100% algodão. Forro: 100% viscose",
        cuidados="Somente lavagem a seco.",
    ),
    11: dict(
        descricao="Cinto em couro legítimo trançado à mão, com fivela em metal escovado. Sem furos: a trama permite ajustar em qualquer ponto.",
        composicao="100% couro bovino",
        cuidados="Limpar com pano seco. Hidratar o couro a cada seis meses.",
    ),
    12: dict(
        descricao="Lenço quadrado em seda com estampa exclusiva inspirada na costa italiana. Bainha enrolada à mão.",
        composicao="100% seda",
        cuidados="Somente lavagem a seco.",
    ),
    13: dict(
        descricao="Bermuda em sarja leve com pregas frontais e barra italiana.",
        composicao="97% algodão, 3% elastano",
        cuidados="Lavar na máquina a 30 °C.",
    ),
}

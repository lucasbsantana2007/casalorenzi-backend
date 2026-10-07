"""Login único (equipe e clientes), cadastro do cliente e "esqueci a senha"."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from src.database.connection import get_db
from src.entities.cliente import normalizar_email
from src.middlewares import limite
from src.middlewares.autenticacao import Sessao, sessao_atual
from src.schemas.autenticacao import (
    CadastroClienteEntrada,
    EsqueciSenhaEntrada,
    LoginEntrada,
    RedefinirSenhaEntrada,
    conta_saida,
)
from src.use_cases import autenticacao

router = APIRouter(prefix="/auth", tags=["Autenticação"])

# "Esqueci a senha": por e-mail e por IP, numa janela de 15 minutos
ESQUECI_SENHA_POR_EMAIL = 3
ESQUECI_SENHA_POR_IP = 10
JANELA_ESQUECI_SENHA = 15 * 60


@router.post("/login")
def login(dados: LoginEntrada, db: Session = Depends(get_db)):
    """Login da equipe e dos clientes. Devolve o token JWT para o cabeçalho Authorization: Bearer
    e o usuário; para cliente, papel "CLIENTE". Mesma mensagem para e-mail inexistente e senha errada (401)."""
    token, conta = autenticacao.entrar(db, dados.email, dados.senha)
    return {"token": token, "usuario": conta_saida(conta)}


@router.post("/cadastro", status_code=201)
def cadastrar_cliente(dados: CadastroClienteEntrada, db: Session = Depends(get_db)):
    """Cria a conta do cliente (feita no checkout) e já devolve a sessão, como o login.
    CPF só com dígitos ou com máscara. CPF ou e-mail já cadastrados: 409."""
    token, cliente = autenticacao.cadastrar_cliente(
        db,
        nome=dados.nome,
        cpf=dados.cpf,
        email=dados.email,
        telefone=dados.telefone,
        senha=dados.senha,
        senha_confirmacao=dados.senha_confirmacao,
    )
    return {"token": token, "usuario": conta_saida(cliente)}


@router.post("/esqueci-senha")
def esqueci_senha(dados: EsqueciSenhaEntrada, request: Request, db: Session = Depends(get_db)):
    """Envia o link de troca de senha (por enquanto, no log da API). A resposta é a mesma exista ou
    não a conta. linkDemo só vem com LINK_SENHA_NA_RESPOSTA=true. Mais de 3 pedidos para o mesmo
    e-mail ou 10 do mesmo IP em 15 minutos: 429."""
    ip = request.client.host if request.client else "desconhecido"
    limite.conferir(
        f"esqueci-senha:email:{normalizar_email(dados.email)}",
        maximo=ESQUECI_SENHA_POR_EMAIL,
        janela_segundos=JANELA_ESQUECI_SENHA,
    )
    limite.conferir(f"esqueci-senha:ip:{ip}", maximo=ESQUECI_SENHA_POR_IP, janela_segundos=JANELA_ESQUECI_SENHA)
    return {"enviado": True, "linkDemo": autenticacao.solicitar_nova_senha(db, dados.email)}


@router.post("/redefinir-senha")
def redefinir_senha(dados: RedefinirSenhaEntrada, db: Session = Depends(get_db)):
    """Link vencido ou já usado: 410."""
    return {"email": autenticacao.redefinir_senha(db, dados.token, dados.senha, dados.senha_confirmacao)}


@router.get("/me")
def eu(sessao: Sessao = Depends(sessao_atual)):
    """Dados da conta do token (equipe ou cliente), útil para validar uma sessão salva."""
    return conta_saida(sessao.usuario or sessao.cliente)

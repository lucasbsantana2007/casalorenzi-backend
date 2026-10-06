from src.schemas.comum import Entrada


class LoginEntrada(Entrada):
    email: str
    senha: str

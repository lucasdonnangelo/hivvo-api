from typing import Optional

from sqlmodel import Session, select

from app.models.category import CategoriaCustomizada
from app.schemas.category import CategoriaResponse

# Categorias padrão do produto (Hivvo_Referencia §5). Compartilhadas entre o
# router de categorias e a sugestão por IA — única fonte, sem import entre routers.
CATEGORIAS_PADRAO: list[CategoriaResponse] = [
    CategoriaResponse(nome="Alimentação",  icone="🍔", tipo="despesa", is_padrao=True),
    CategoriaResponse(nome="Moradia",      icone="🏠", tipo="despesa", is_padrao=True),
    CategoriaResponse(nome="Transporte",   icone="🚗", tipo="despesa", is_padrao=True),
    CategoriaResponse(nome="Saúde",        icone="💊", tipo="despesa", is_padrao=True),
    CategoriaResponse(nome="Educação",     icone="📚", tipo="despesa", is_padrao=True),
    CategoriaResponse(nome="Lazer",        icone="🎮", tipo="despesa", is_padrao=True),
    CategoriaResponse(nome="Roupas",       icone="👕", tipo="despesa", is_padrao=True),
    CategoriaResponse(nome="Assinaturas",  icone="📱", tipo="despesa", is_padrao=True),
    CategoriaResponse(nome="Viagem",       icone="✈️",  tipo="despesa", is_padrao=True),
    CategoriaResponse(nome="Pets",         icone="🐾", tipo="despesa", is_padrao=True),
    CategoriaResponse(nome="Outros",       icone="📦", tipo="despesa", is_padrao=True),
    CategoriaResponse(nome="Salário",      icone="💰", tipo="receita", is_padrao=True),
    CategoriaResponse(nome="Freelance",    icone="💻", tipo="receita", is_padrao=True),
    CategoriaResponse(nome="Investimentos",icone="📈", tipo="receita", is_padrao=True),
    CategoriaResponse(nome="Outros",       icone="📦", tipo="receita", is_padrao=True),
]


def nomes_categorias_do_usuario(
    session: Session, usuario_id: int, tipo: Optional[str] = None
) -> list[str]:
    """Categorias VÁLIDAS para o usuário: padrão + customizadas ativas.

    Fonte única do "universo de categorias que o cliente conhece" nas chamadas
    ao modelo — /ai/suggest-category (uma transação) e a categorização em LOTE
    do import de extrato (N linhas numa chamada). `tipo=None` traz os dois tipos
    (e então "Outros" aparece duas vezes, uma por tipo — irrelevante para o
    casamento; quem monta prompt deduplica).
    """
    nomes = [c.nome for c in CATEGORIAS_PADRAO if tipo is None or c.tipo == tipo]
    stmt = select(CategoriaCustomizada).where(
        CategoriaCustomizada.usuario_id == usuario_id,
        CategoriaCustomizada.ativa == True,  # noqa: E712
    )
    if tipo is not None:
        stmt = stmt.where(CategoriaCustomizada.tipo == tipo)
    for c in session.exec(stmt).all():
        if c.nome not in nomes:
            nomes.append(c.nome)
    return nomes


def casar_categoria(resposta: str, nomes: list[str]) -> str:
    """Garante que a sugestão é uma categoria que o cliente conhece.

    Match exato (case-insensitive, sem decoração) -> substring -> fallback
    "Outros" (que existe nos dois tipos em CATEGORIAS_PADRAO). Guarda-corpo de
    TODA sugestão por IA: o picker do frontend nunca recebe nome inventado.
    """
    limpo = resposta.strip().strip(".\"'")
    for nome in nomes:
        if limpo.casefold() == nome.casefold():
            return nome
    for nome in nomes:
        if nome.casefold() in resposta.casefold():
            return nome
    return "Outros"

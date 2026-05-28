from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models.category import CategoriaCustomizada
from app.models.user import Usuario
from app.schemas.category import CategoriaCreate, CategoriaResponse

router = APIRouter(prefix="/categories", tags=["categories"])

_CATEGORIAS_PADRAO: list[CategoriaResponse] = [
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


@router.get("", response_model=list[CategoriaResponse])
def list_categories(
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    custom = session.exec(
        select(CategoriaCustomizada)
        .where(CategoriaCustomizada.usuario_id == current_user.id)
        .where(CategoriaCustomizada.ativa == True)  # noqa: E712
    ).all()

    return _CATEGORIAS_PADRAO + [CategoriaResponse.model_validate(c) for c in custom]


@router.post("", response_model=CategoriaResponse, status_code=status.HTTP_201_CREATED)
def create_category(
    body: CategoriaCreate,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    categoria = CategoriaCustomizada(
        usuario_id=current_user.id,
        nome=body.nome,
        icone=body.icone,
        tipo=body.tipo,
    )
    session.add(categoria)
    session.commit()
    session.refresh(categoria)
    return CategoriaResponse.model_validate(categoria)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    id: int,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    categoria = session.get(CategoriaCustomizada, id)
    if not categoria or categoria.usuario_id != current_user.id:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")

    # Soft delete — mantém histórico de transações existentes
    categoria.ativa = False
    session.add(categoria)
    session.commit()

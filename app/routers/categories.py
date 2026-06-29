from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models.category import CategoriaCustomizada
from app.models.user import Usuario
from app.schemas.category import CategoriaCreate, CategoriaResponse
from app.services.categorias import CATEGORIAS_PADRAO

router = APIRouter(prefix="/categories", tags=["categories"])


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

    return CATEGORIAS_PADRAO + [CategoriaResponse.model_validate(c) for c in custom]


@router.post("", response_model=CategoriaResponse, status_code=status.HTTP_201_CREATED)
def create_category(
    body: CategoriaCreate,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    # T-11: a regra real, dado o soft delete, é "não duas categorias ATIVAS com o
    # mesmo nome" (normalizado por lower(trim), igual ao índice parcial). Guarda no
    # app para devolver 409/reativar em vez de deixar virar IntegrityError/500.
    nome_norm = body.nome.strip().lower()
    existentes = session.exec(
        select(CategoriaCustomizada)
        .where(
            CategoriaCustomizada.usuario_id == current_user.id,
            func.lower(func.trim(CategoriaCustomizada.nome)) == nome_norm,
        )
        .order_by(CategoriaCustomizada.id)
    ).all()

    if any(c.ativa for c in existentes):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe uma categoria ativa com esse nome",
        )

    inativa = next((c for c in existentes if not c.ativa), None)
    if inativa is not None:
        # Reativa a MESMA linha em vez de inserir uma 2ª — não acumula histórico de
        # soft delete. Atualiza ícone e tipo com os do request.
        inativa.ativa = True
        inativa.icone = body.icone
        inativa.tipo = body.tipo
        categoria = inativa
    else:
        categoria = CategoriaCustomizada(
            usuario_id=current_user.id,
            nome=body.nome,
            icone=body.icone,
            tipo=body.tipo,
        )

    session.add(categoria)
    try:
        session.commit()
    except IntegrityError:
        # Corrida concorrente que passou pela checagem acima e bateu no índice
        # parcial — traduz para 409, nunca 500.
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe uma categoria ativa com esse nome",
        )
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

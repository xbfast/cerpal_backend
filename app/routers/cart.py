import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.cart_schemas import CartOut, CartReplaceIn
from app.database import get_db
from app.deps import get_current_user
from app.models import AuthAccount, Cart, CartLine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/me/cart", tags=["cart"])


@router.get("", response_model=CartOut)
def obtener_carrito(
    user: AuthAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CartOut:
    cart = db.scalar(select(Cart).where(Cart.auth_id == user.id))
    if cart is None:
        return CartOut(lines=[])
    rows = db.scalars(
        select(CartLine)
        .where(CartLine.cart_id == cart.id)
        .order_by(CartLine.line_index.asc())
    ).all()
    return CartOut(lines=[dict(r.line_data) for r in rows])


@router.put("", response_model=CartOut)
def reemplazar_carrito(
    payload: CartReplaceIn,
    user: AuthAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CartOut:
    cart = db.scalar(select(Cart).where(Cart.auth_id == user.id))
    try:
        if not payload.lines:
            if cart is not None:
                db.execute(delete(CartLine).where(CartLine.cart_id == cart.id))
                db.delete(cart)
                db.commit()
            return CartOut(lines=[])

        if cart is None:
            cart = Cart(auth_id=user.id)
            db.add(cart)
            db.flush()
        else:
            db.execute(delete(CartLine).where(CartLine.cart_id == cart.id))

        for idx, item in enumerate(payload.lines):
            row = CartLine(
                id=item.id,
                cart_id=cart.id,
                line_index=idx,
                line_data=item.model_dump(mode="json"),
            )
            db.add(row)
        db.commit()
    except DBAPIError as e:
        db.rollback()
        logger.exception("Error al guardar carrito")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo guardar el carrito. Inténtalo de nuevo.",
        ) from e

    rows = db.scalars(
        select(CartLine)
        .where(CartLine.cart_id == cart.id)
        .order_by(CartLine.line_index.asc())
    ).all()
    return CartOut(lines=[dict(r.line_data) for r in rows])

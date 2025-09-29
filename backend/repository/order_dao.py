from datetime import datetime
from sqlalchemy.orm import Session
import models, schemas
from models import OrderDetails, Products
from fastapi import HTTPException
from sqlalchemy import text, func

def get_order_details(order_id: int, db: Session):
	response = (
        db.query(
            OrderDetails.order_id,
            Products.product_id,
            Products.name,
            OrderDetails.quantity,
            OrderDetails.total_price
        )
        .join(Products, OrderDetails.product_id == Products.product_id)
        .filter(OrderDetails.order_id == order_id)
        .all()
    )

	return response

def get_orders(db: Session):
	response = db.query(models.Orders).all()
	return response

def insert_new_order(request: schemas.FullOrder, db: Session):
    # Validate customer and product
    customer = db.query(models.Customers).filter(models.Customers.customer_name == request.customer_name).first()
    product = db.query(models.Products).filter(models.Products.product_id == request.product_id).first()

    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Check if orderdetails already has this product for the customer
    existing_order_detail = (
        db.query(models.OrderDetails)
        .filter(
            models.OrderDetails.order_id == customer.customer_id,
            models.OrderDetails.product_id == request.product_id
        )
        .first()
    )

    if existing_order_detail:
        # Update quantity and total_price
        existing_order_detail.quantity += request.quantity
        existing_order_detail.total_price = existing_order_detail.quantity * product.price_per_unit
        db.add(existing_order_detail)
    else:
        # Insert new row
        total_price = request.quantity * product.price_per_unit
        new_order_detail = models.OrderDetails(
            order_id=customer.customer_id,
            product_id=request.product_id,
            quantity=request.quantity,
            total_price=total_price
        )
        db.add(new_order_detail)

    db.commit()

    # Recalculate total cost for the order
    total_cost = (
        db.query(func.sum(models.OrderDetails.total_price))
        .filter(models.OrderDetails.order_id == customer.customer_id)
        .scalar() or 0.0
    )

    # Upsert into Orders table
    current_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    new_order = models.Orders(
        order_id=customer.customer_id,
        customer_name=request.customer_name,
        date=current_date,
        total_cost=total_cost
    )
    persistent_order = db.merge(new_order)
    db.commit()
    db.refresh(persistent_order)

    return "Data Inserted or Updated Successfully"

def delete_order_detail(request: schemas.OrderDetailDeleteRequest, db: Session):
    order_detail = db.query(models.OrderDetails).filter_by(
        order_id=request.order_id,
        product_id=request.product_id
    ).first()

    if not order_detail:
        raise HTTPException(status_code=404, detail="Order detail not found")

    order = db.query(models.Orders).filter_by(order_id=request.order_id).first()
    if order:
        order.total_cost -= order_detail.total_price
        order.date = datetime.now()
        db.commit()

    db.delete(order_detail)
    db.commit()

    if order and order.total_cost <= 0:
        db.delete(order)
        db.commit()

    return "Deleted Successfully"

def delete_order(request: schemas.OrderDeleteRequest, db: Session):
    order = db.query(models.Orders).filter_by(order_id=request.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    db.query(models.OrderDetails).filter_by(order_id=request.order_id).delete()
    
    db.delete(order)
    db.commit()
    
    return "Deleted Successfully"

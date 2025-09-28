from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from repository import product_dao, customer_dao, order_dao
from sql_connection import get_db
import generic_helper
from sqlalchemy.orm import Session
from schemas import CustomerCreate, FullOrder, ProductCreate, ProductDeleteRequest

import redis
import os
import json

r = redis.from_url(os.getenv("REDIS_URL"), decode_responses=True)

SESSION_EXPIRE_SECONDS = 3600  # 1 hour expiration for sessions

router = APIRouter()


@router.post("/")
async def handle_webhook_request(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    intent = payload['queryResult']['intent']['displayName']
    parameters = payload['queryResult']['parameters']
    output_contexts = payload['queryResult']['outputContexts']
    session_id = generic_helper.extract_session_id(output_contexts)

    intent_handler_dict = {
        'product.search': handle_product_search,
        'order.start': handle_order_start,
        'order.add': handle_add_to_order,
        'order.remove': handle_remove_from_order,
        'order.cancel': handle_cancel_order,
        'order.cancel - context: ongoing-order': handle_cancel_order,
        'order.complete': handle_order_complete,
        'product.create': handle_product_create,
        'product.delete': handle_product_delete
    }
    if intent in intent_handler_dict:
        return intent_handler_dict[intent](parameters, session_id, db, output_contexts)
    return JSONResponse(content={"fulfillmentText": f"Intent '{intent}' is not handled."})


def get_order(session_id: str):
    data = r.get(session_id)
    return json.loads(data) if data else None


def save_order(session_id: str, order_data: dict):
    r.set(session_id, json.dumps(order_data), ex=SESSION_EXPIRE_SECONDS)


def delete_order(session_id: str):
    r.delete(session_id)


def handle_product_delete(parameters: dict, session_id: str, db: Session, output_contexts: list):
    product_name = parameters.get('product-name')
    product_list = product_dao.get_some_product(product_name, db)
    
    if not product_list:
        text = f"Sorry, I couldn't find a product named '{product_name}' to delete."
        return JSONResponse(content={"fulfillmentText": text})
    
    try:
        product_to_delete = product_list[0]
        delete_request = ProductDeleteRequest(product_id=product_to_delete.product_id)
        product_dao.delete_product(delete_request, db)
        text = f"Successfully deleted the product '{product_name}' from the catalog."
    except Exception as e:
        print(f"Error deleting product: {e}")
        text = f"Sorry, there was an error deleting the product '{product_name}'. Please try again."
        
    return JSONResponse(content={"fulfillmentText": text})


def handle_product_create(parameters: dict, session_id: str, db: Session, output_contexts: list):
    product_name = parameters.get('product-name')
    price = parameters.get('price')
    uom = parameters.get('unit-of-measure')

    uom_map = {"kg": 1, "each": 2}
    uom_id = uom_map.get(uom.lower())

    if not uom_id:
        text = f"Sorry, '{uom}' is not a valid unit of measure. Please use 'kg' or 'each'."
        return JSONResponse(content={"fulfillmentText": text})

    try:
        product_schema = ProductCreate(name=product_name, uom_id=uom_id, price_per_unit=price)
        product_dao.insert_new_product(product_schema, db)
        text = f"Great! I've added '{product_name}' to the product catalog at a price of ₹{price} per {uom}."
    except Exception as e:
        print(f"Error creating product: {e}")
        text = f"Sorry, there was an error creating the product '{product_name}'. Please try again."
    return JSONResponse(content={"fulfillmentText": text})


def handle_add_to_order(parameters: dict, session_id: str, db: Session, output_contexts: list):
    order_data = get_order(session_id)
    if not order_data:
        return JSONResponse(content={"fulfillmentText": "I can't find an active order. Please start a new one."})

    product_name = parameters.get('product-name', [None])[0]
    quantity = parameters.get('number', [0])[0]

    product_list = product_dao.get_some_product(product_name, db)
    if not product_list:
        available_products = ", ".join([p.name for p in product_dao.get_all_products(db)])
        text = (f"Sorry, I can't find '{product_name}'. You can choose from: {available_products}.")
        return JSONResponse(content={"fulfillmentText": text})

    items = order_data["items"]
    items[product_name] = items.get(product_name, 0) + quantity
    order_data["items"] = items
    save_order(session_id, order_data)

    order_str = generic_helper.get_str_from_item_dict(items)
    text = f"OK. So far, your order includes: {order_str}. Anything else?"
    return JSONResponse(content={"fulfillmentText": text})


def handle_product_search(parameters: dict, session_id: str, db: Session, output_contexts: list):
    pname = parameters.get('product-name', '') or parameters.get('any', '')
    products = product_dao.get_some_product(pname, db) if pname else product_dao.get_all_products(db)
    if not products:
        text = f"Sorry, I couldn't find any products matching '{pname}'."
    else:
        product_list = [f"{p.name} (₹{p.price_per_unit}/{p.uom_name})" for p in products]
        text = "Here are the products I found: " + ", ".join(product_list)
    return JSONResponse(content={"fulfillmentText": text})


def handle_order_start(parameters: dict, session_id: str, db: Session, output_contexts: list):
    customer_name = parameters.get('customer-name', {}).get('name')
    if not customer_name:
        return JSONResponse(content={"fulfillmentText": "I'll need a customer name to start an order."})

    order_data = {"customer_name": customer_name, "items": {}}
    save_order(session_id, order_data)

    text = f"Starting a new order for {customer_name.title()}. What would you like to add?"
    return JSONResponse(content={"fulfillmentText": text})


def handle_remove_from_order(parameters: dict, session_id: str, db: Session, output_contexts: list):
    order_data = get_order(session_id)
    if not order_data:
        return JSONResponse(content={"fulfillmentText": "I can't find an active order."})

    product_name = parameters.get('product-name', [None])[0]
    items = order_data["items"]

    if product_name not in items:
        text = f"I couldn't find '{product_name}' in your current order."
    else:
        del items[product_name]
        if not items:
            text = f"Removed {product_name}. Your order is now empty."
        else:
            order_str = generic_helper.get_str_from_item_dict(items)
            text = f"Removed {product_name}. Your order now includes: {order_str}."

    order_data["items"] = items
    save_order(session_id, order_data)
    return JSONResponse(content={"fulfillmentText": text})


def handle_order_complete(parameters: dict, session_id: str, db: Session, output_contexts: list):
    order_data = get_order(session_id)
    if not order_data or not order_data["items"]:
        return JSONResponse(content={"fulfillmentText": "There's nothing in your order to complete."})

    customer_name = order_data["customer_name"]
    items = order_data["items"]
    total_cost = 0

    try:
        customer = customer_dao.get_customer_by_name(customer_name, db)
        if not customer:
            customer = customer_dao.insert_new_customer(CustomerCreate(customer_name=customer_name), db)

        for name, qty in items.items():
            product_list = product_dao.get_some_product(name, db)
            if product_list:
                product = product_list[0]
                total_cost += product.price_per_unit * qty
                order_dao.insert_new_order(
                    FullOrder(product_id=product.product_id, quantity=qty, customer_name=customer.customer_name), db
                )

        text = f"Excellent! Your order for {customer_name.title()} is complete. The total is ₹{total_cost:.2f}. Thank you!"
        delete_order(session_id)

    except Exception as e:
        print(f"Error saving to DB: {e}")
        text = "I'm sorry, there was an error saving your order. Please try again."

    return JSONResponse(content={"fulfillmentText": text})


def handle_cancel_order(parameters: dict, session_id: str, db: Session, output_contexts: list):
    context = generic_helper.get_context(output_contexts, 'ongoing-order')
    if context:
        delete_order(session_id)
        text = "Your current order has been canceled. You can start a new one anytime."
    else:
        customer_name = parameters.get('customer-name', {}).get('name')
        if not customer_name:
            return JSONResponse(content={"fulfillmentText": "Please specify which customer's order you want to cancel."})
        customer = customer_dao.get_customer_by_name(customer_name, db)
        if not customer:
            return JSONResponse(content={"fulfillmentText": f"I can't find a customer named {customer_name}."})
        order_dao.delete_all_orders_for_customer(customer.customer_id, db)
        text = f"All past orders for {customer_name} have been deleted."
    return JSONResponse(content={"fulfillmentText": text})

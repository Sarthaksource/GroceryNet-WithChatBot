from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from repository import product_dao, customer_dao, order_dao
from sql_connection import get_db
import generic_helper
from sqlalchemy.orm import Session
from schemas import CustomerCreate, FullOrder, ProductCreate, ProductDeleteRequest

router = APIRouter()

inprogress_orders = {}


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
        'product.delete': handle_product_delete # New handler for deleting products
    }
    if intent in intent_handler_dict:
        return intent_handler_dict[intent](parameters, session_id, db, output_contexts)
    return JSONResponse(content={"fulfillmentText": f"Intent '{intent}' is not handled."})

def handle_product_delete(parameters: dict, session_id: str, db: Session, output_contexts: list):
    product_name = parameters.get('product-name')

    # Find the product first to get its ID
    product_list = product_dao.get_some_product(product_name, db)
    
    if not product_list:
        text = f"Sorry, I couldn't find a product named '{product_name}' to delete."
        return JSONResponse(content={"fulfillmentText": text})
    
    try:
        product_to_delete = product_list[0]
        product_id = product_to_delete.product_id
        
        # Your DAO expects a Pydantic object, so we create one
        delete_request = ProductDeleteRequest(product_id=product_id)
        
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
    if session_id not in inprogress_orders:
        return JSONResponse(content={"fulfillmentText": "I can't find an active order. Please start a new one."})
    product_name = parameters.get('product-name', [None])[0]
    quantity = parameters.get('number', [0])[0]
    product_list = product_dao.get_some_product(product_name, db)
    if not product_list:
        available_products = ", ".join([p.name for p in product_dao.get_all_products(db)])
        text = (f"Sorry, I can't find '{product_name}'. You can choose from: {available_products}.")
        return JSONResponse(content={"fulfillmentText": text})
    current_items = inprogress_orders[session_id]["items"]
    current_items[product_name] = current_items.get(product_name, 0) + quantity
    order_str = generic_helper.get_str_from_item_dict(current_items)
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
    inprogress_orders[session_id] = {"customer_name": customer_name, "items": {}}
    text = f"Starting a new order for {customer_name.title()}. What would you like to add?"
    return JSONResponse(content={"fulfillmentText": text})

def handle_remove_from_order(parameters: dict, session_id: str, db: Session, output_contexts: list):
    if session_id not in inprogress_orders:
        return JSONResponse(content={"fulfillmentText": "I can't find an active order."})
    product_name = parameters.get('product-name', [None])[0]
    current_items = inprogress_orders[session_id]["items"]
    if product_name not in current_items:
        text = f"I couldn't find '{product_name}' in your current order."
    else:
        del current_items[product_name]
        if not current_items:
            text = f"Removed {product_name}. Your order is now empty."
        else:
            order_str = generic_helper.get_str_from_item_dict(current_items)
            text = f"Removed {product_name}. Your order now includes: {order_str}."
    return JSONResponse(content={"fulfillmentText": text})

def handle_order_complete(parameters: dict, session_id: str, db: Session, output_contexts: list):
    if session_id not in inprogress_orders or not inprogress_orders[session_id]["items"]:
        return JSONResponse(content={"fulfillmentText": "There's nothing in your order to complete."})
    order_data = inprogress_orders[session_id]
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
                order_dao.insert_new_order(FullOrder(product_id=product.product_id, quantity=qty, customer_name=customer.customer_name), db)
        text = f"Excellent! Your order for {customer_name.title()} is complete. The total is ₹{total_cost:.2f}. Thank you!"
        del inprogress_orders[session_id]
    except Exception as e:
        print(f"Error saving to DB: {e}")
        text = "I'm sorry, there was an error saving your order. Please try again."
    return JSONResponse(content={"fulfillmentText": text})

def handle_cancel_order(parameters: dict, session_id: str, db: Session, output_contexts: list):
    context = generic_helper.get_context(output_contexts, 'ongoing-order')
    if context:
        if session_id in inprogress_orders:
            del inprogress_orders[session_id]
            text = "Your current order has been canceled. You can start a new one anytime."
        else:
            text = "There is no active order to cancel."
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